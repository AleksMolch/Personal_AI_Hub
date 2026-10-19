"""Интеграционные тесты веб-поиска в чате (ADR-0005).

Проверяют сквозной путь: флаг `web_search` в запросе сообщения → поиск через
mock SearXNG → источники в системной инструкции → сохранение цитат в снимке
сообщения, а также отказ с понятной ошибкой, когда возможность выключена.

Платные вызовы не выполняются: LLM и поисковик подменены локальным mock
HTTP-сервером.
"""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from personal_hub.config import get_settings

SEARCH_BODY = {
    "results": [
        {
            "title": "Что такое RAG",
            "url": "https://example.org/rag",
            "content": "RAG объединяет поиск и генерацию текста.",
            "engine": "duckduckgo",
        },
        {
            "title": "Второй источник",
            "url": "https://example.org/second",
            "content": "Дополнительное описание.",
            "engine": "google",
        },
    ]
}


@pytest.fixture
def enable_web_search(monkeypatch):
    """Включает веб-поиск и направляет его на mock-сервер.

    Настройки кэшированы (`lru_cache`), поэтому кэш сбрасывается: иначе
    приложение продолжит видеть значения, прочитанные при импорте.

    Returns:
        Функцию, принимающую адрес mock-сервера и включающую поиск.
    """

    def _enable(base_url: str) -> None:
        monkeypatch.setenv("WEB_SEARCH_ENABLED", "1")
        monkeypatch.setenv("SEARXNG_URL", base_url)
        get_settings.cache_clear()

    yield _enable
    get_settings.cache_clear()


async def _setup(client: AsyncClient, mock_provider, models_body: str) -> tuple[dict, str]:
    """Создаёт администратора, провайдера, модель и цену."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (200, models_body)

    provider = await client.post(
        "/api/v1/providers",
        json={
            "provider_type": "openai_compatible",
            "display_name": "Test",
            "base_url": f"http://{host}:{port}",
            "api_key": "sk-test",
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/providers/{provider.json()['id']}/sync-models", headers=headers
    )
    model_id = (await client.get("/api/v1/models", headers=headers)).json()[0]["id"]
    await client.post(
        "/api/v1/prices",
        json={
            "model_profile_id": model_id,
            "input_per_million": "1.00",
            "output_per_million": "2.00",
            "currency": "USD",
        },
        headers=headers,
    )
    return headers, model_id


def _sse(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks)


async def _drain_events(client: AsyncClient, generation_id: str, headers: dict) -> None:
    """Вычитывает SSE-поток до конца, чтобы генерация завершилась."""
    async with client.stream(
        "GET", f"/api/v1/generations/{generation_id}/events", headers=headers
    ) as resp:
        async for _ in resp.aiter_lines():
            pass


@pytest.mark.asyncio
async def test_capabilities_reports_web_search_state(client: AsyncClient) -> None:
    """Эндпоинт возможностей сообщает состояние веб-поиска для UI."""
    resp = await client.get("/api/v1/capabilities")

    assert resp.status_code == 200
    assert "web_search" in resp.json()


@pytest.mark.asyncio
async def test_web_search_disabled_returns_clear_error(
    client: AsyncClient, mock_provider, monkeypatch
) -> None:
    """Флаг web_search при выключенной возможности даёт понятную ошибку.

    Молча игнорировать флаг нельзя: пользователь считал бы, что ответ
    обоснован источниками. Настройки кэшированы, поэтому состояние задаётся
    явно: иначе тест зависел бы от `.env` на машине разработчика (и падал,
    если там включён веб-поиск).
    """
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "0")
    get_settings.cache_clear()
    try:
        models = json.dumps({"data": [{"id": "m1", "name": "Model 1"}]})
        headers, model_id = await _setup(client, mock_provider, models)
        conversation = await client.post(
            "/api/v1/conversations", json={"title": "T"}, headers=headers
        )
        conversation_id = conversation.json()["id"]

        resp = await client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={
                "content": "вопрос",
                "model_profile_id": model_id,
                "web_search": True,
            },
            headers=headers,
        )

        assert resp.status_code == 400
        assert "WEB_SEARCH_ENABLED" in resp.json()["error"]["message"]
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_web_search_sources_saved_and_injected(
    client: AsyncClient, mock_provider, enable_web_search
) -> None:
    """Сквозной путь: поиск → контекст в промпте → источники в снимке."""
    models = json.dumps({"data": [{"id": "m1", "name": "Model 1"}]})
    headers, model_id = await _setup(client, mock_provider, models)

    host, port = mock_provider.server_address
    enable_web_search(f"http://{host}:{port}")

    # Mock SearXNG: точный ключ не подходит, путь содержит query string,
    # поэтому регистрируем обработчик без параметров (см. tests/conftest.py).
    mock_provider.spec["GET /search"] = (200, json.dumps(SEARCH_BODY))

    # Запоминаем системную инструкцию, которую получил провайдер LLM.
    captured: dict = {}

    def chat_handler(_method: str, _path: str, body: bytes) -> tuple:
        captured.update(json.loads(body))
        return (
            200,
            _sse(
                '{"choices":[{"delta":{"content":"Ответ по источникам [1]"}}]}',
                '{"choices":[{"delta":{}}],"usage":'
                '{"prompt_tokens":10,"completion_tokens":5}}',
                "[DONE]",
            ),
            {"Content-Type": "text/event-stream"},
        )

    mock_provider.spec["POST /chat/completions"] = chat_handler

    conversation = await client.post(
        "/api/v1/conversations", json={"title": "Поиск"}, headers=headers
    )
    conversation_id = conversation.json()["id"]

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "content": "что такое RAG",
            "model_profile_id": model_id,
            "web_search": True,
        },
        headers=headers,
    )
    assert resp.status_code == 200
    generation_id = resp.json()["generation_id"]
    await _drain_events(client, generation_id, headers)

    # 1. Системная инструкция содержит источники с адресами и правилом
    #    цитирования, а также защиту от команд со страниц.
    system = captured["messages"][0]["content"]
    assert captured["messages"][0]["role"] == "system"
    assert "https://example.org/rag" in system
    assert "https://example.org/second" in system
    assert "[1]" in system
    assert "не выдумывай" in system.lower()

    # 2. Источники сохранены в снимке сообщения: они переживут перезагрузку.
    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    messages = detail.json()["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"][-1]
    search = assistant["model_snapshot"]["web_search"]
    assert search["used"] is True
    assert [c["index"] for c in search["citations"]] == [1, 2]
    assert search["citations"][0]["url"] == "https://example.org/rag"
    assert search["citations"][0]["title"] == "Что такое RAG"


@pytest.mark.asyncio
async def test_web_search_failure_blocks_before_llm_call(
    client: AsyncClient, mock_provider, enable_web_search
) -> None:
    """Сбой поиска возвращает 502 и НЕ вызывает платного провайдера.

    Это ключевой инвариант расходов: неудачный поиск не должен приводить к
    оплаченной генерации.
    """
    models = json.dumps({"data": [{"id": "m1", "name": "Model 1"}]})
    headers, model_id = await _setup(client, mock_provider, models)

    host, port = mock_provider.server_address
    enable_web_search(f"http://{host}:{port}")

    # 403 — формат json не включён в settings.yml SearXNG.
    mock_provider.spec["GET /search"] = (403, json.dumps({"error": "forbidden"}))
    called: list[str] = []

    def chat_handler(_method: str, _path: str, _body: bytes) -> tuple:
        called.append("chat")
        return (200, _sse("[DONE]"))

    mock_provider.spec["POST /chat/completions"] = chat_handler

    conversation = await client.post(
        "/api/v1/conversations", json={"title": "Сбой"}, headers=headers
    )
    conversation_id = conversation.json()["id"]

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "content": "вопрос",
            "model_profile_id": model_id,
            "web_search": True,
        },
        headers=headers,
    )

    assert resp.status_code == 502
    assert "WEB_SEARCH_FORBIDDEN" in resp.json()["error"]["message"]
    assert called == [], "провайдер не должен вызываться при сбое поиска"
