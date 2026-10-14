"""Тесты веб-поиска: backend SearXNG и подготовка контекста для модели.

Проверяют:
1. разбор JSON-ответа SearXNG и отображение сбоев на стабильные коды;
2. отдельно — 403, который возникает, когда формат json не включён в
   `settings.yml` (самая частая ошибка развёртывания);
3. что контекст обрезается по длине (иначе стоимость запроса непредсказуема) и
   что источники помечены как данные, а не как инструкции;
4. что нумерация цитат совпадает с маркерами `[n]` в контексте.

Платные API не используются: SearXNG подменяется локальным mock HTTP-сервером.
"""
from __future__ import annotations

import json

import pytest

from personal_hub.websearch.base import WebSearchError
from personal_hub.websearch.searxng import SearxngProvider
from personal_hub.websearch.service import (
    build_citations,
    build_search_context,
    build_search_system_prompt,
    format_search_warnings,
)

# Фикстура ответа SearXNG: структура повторяет реальный JSON API
# (результаты с title/url/content/engine и список недоступных движков).
_SEARXNG_BODY = {
    "query": "что такое RAG",
    "results": [
        {
            "title": "Retrieval-augmented generation",
            "url": "https://example.org/rag",
            "content": "RAG объединяет поиск и генерацию.",
            "engine": "duckduckgo",
        },
        {
            "title": "RAG простыми словами",
            "url": "https://example.org/rag-ru",
            "content": "Объяснение на русском.",
            "engine": "google",
        },
    ],
    "unresponsive_engines": [["brave", "timeout"]],
}


def _provider(mock_provider, **kwargs) -> SearxngProvider:
    """Провайдер, направленный на локальный mock-сервер."""
    host, port = mock_provider.server_address
    return SearxngProvider(f"http://{host}:{port}", **kwargs)


def _spec_json(mock_provider, body: dict, status: int = 200) -> None:
    """Регистрирует ответ mock-сервера с заданным телом.

    Ключ строится через callable: путь включает query string, поэтому точное
    совпадение по "GET /search?..." было бы хрупким.
    """

    def handler(_method: str, _path: str, _body: bytes):
        return (status, json.dumps(body))

    mock_provider.spec["GET /search"] = handler


@pytest.mark.asyncio
async def test_search_parses_results(mock_provider) -> None:
    """Разбирает результаты и замечание о недоступном движке."""
    _spec_json(mock_provider, _SEARXNG_BODY)

    response = await _provider(mock_provider).search("что такое RAG", limit=5)

    assert response.query == "что такое RAG"
    assert [r.title for r in response.results] == [
        "Retrieval-augmented generation",
        "RAG простыми словами",
    ]
    assert response.results[0].url == "https://example.org/rag"
    assert response.results[0].engine == "duckduckgo"
    # Недоступный движок — предупреждение, а не ошибка: выдача неполная, но
    # пользователь должен об этом знать.
    assert response.warnings
    assert "brave" in response.warnings[0]


@pytest.mark.asyncio
async def test_search_respects_limit(mock_provider) -> None:
    """Число результатов ограничивается параметром limit."""
    _spec_json(mock_provider, _SEARXNG_BODY)

    response = await _provider(mock_provider).search("что такое RAG", limit=1)

    assert len(response.results) == 1


@pytest.mark.asyncio
async def test_search_skips_results_without_url(mock_provider) -> None:
    """Записи без адреса отбрасываются: цитата без ссылки бесполезна."""
    _spec_json(
        mock_provider,
        {
            "results": [
                {"title": "без ссылки", "content": "текст"},
                {"title": "со ссылкой", "url": "https://example.org/ok"},
            ]
        },
    )

    response = await _provider(mock_provider).search("q", limit=5)

    assert len(response.results) == 1
    assert response.results[0].url == "https://example.org/ok"


@pytest.mark.asyncio
async def test_search_forbidden_reports_json_disabled(mock_provider) -> None:
    """403 — это выключенный формат json; код и подсказка должны быть точными."""
    _spec_json(mock_provider, {"error": "forbidden"}, status=403)

    with pytest.raises(WebSearchError) as exc_info:
        await _provider(mock_provider).search("q", limit=5)

    assert exc_info.value.code == "WEB_SEARCH_FORBIDDEN"
    assert "JSON" in exc_info.value.message


@pytest.mark.asyncio
async def test_search_server_error_is_retryable(mock_provider) -> None:
    """5xx помечается как временная ошибка."""
    _spec_json(mock_provider, {"error": "boom"}, status=503)

    with pytest.raises(WebSearchError) as exc_info:
        await _provider(mock_provider).search("q", limit=5)

    assert exc_info.value.code == "WEB_SEARCH_FAILED"
    assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_search_bad_json_raises_stable_code(mock_provider) -> None:
    """Не-JSON ответ даёт стабильный код, а не исключение парсера."""

    def handler(_method: str, _path: str, _body: bytes):
        return (200, "<html>not json</html>")

    mock_provider.spec["GET /search"] = handler

    with pytest.raises(WebSearchError) as exc_info:
        await _provider(mock_provider).search("q", limit=5)

    assert exc_info.value.code == "WEB_SEARCH_BAD_RESPONSE"


def test_build_citations_numbers_from_one() -> None:
    """Нумерация начинается с 1 и совпадает с порядком результатов."""
    from personal_hub.websearch.base import WebSearchResponse, WebSearchResult

    response = WebSearchResponse(
        query="q",
        results=[
            WebSearchResult(title="A", url="https://a", snippet="sa"),
            WebSearchResult(title="B", url="https://b", snippet="sb"),
        ],
    )

    citations = build_citations(response)

    assert [c.index for c in citations] == [1, 2]
    assert citations[1].title == "B"


def test_context_truncates_long_snippets() -> None:
    """Длинный сниппет обрезается: иначе вход запроса растёт бесконтрольно."""
    from personal_hub.websearch.base import WebCitation

    citations = [WebCitation(index=1, title="T", url="https://a", snippet="x" * 5000)]

    context = build_search_context(citations, max_chars=100)

    assert len(context) < 300
    assert context.endswith("…")
    assert "https://a" in context


def test_context_empty_without_citations() -> None:
    """Без источников контекст пуст, и поиск не влияет на промпт."""
    assert build_search_context([], max_chars=100) == ""


def test_system_prompt_marks_sources_as_data() -> None:
    """Инструкция защищает от prompt injection со страниц."""
    prompt = build_search_system_prompt("[1] T — https://a\nтекст")

    assert "ДАННЫЕ" in prompt
    assert "не выполняй" in prompt.lower() or "Никогда не" in prompt
    assert "недостаточно данных" in prompt
    assert "[1] T — https://a" in prompt


def test_format_warnings_returns_none_when_clean() -> None:
    """Без замечаний функция возвращает None, а не пустую строку."""
    from personal_hub.websearch.base import WebSearchResponse

    assert format_search_warnings(WebSearchResponse(query="q")) is None
    assert (
        format_search_warnings(WebSearchResponse(query="q", warnings=["a", "b"]))
        == "a b"
    )
