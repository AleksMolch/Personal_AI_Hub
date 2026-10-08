"""Live-сертификация реального провайдера (крошечные платные запросы).

Проверяет: health и каталог моделей; непотоковый чат с фактическим usage;
streaming; эмбеддинги (если задана модель). Все платные вызовы проходят через
`LiveBudget` из conftest: бюджет проверяется до вызова и списывается после;
при отсутствии прайса резервируется консервативная оценка.

Запуск: `RUN_LIVE_TESTS=1 LIVE_TEST_BUDGET=0.05 make test-live`.
"""
from __future__ import annotations

import os

import pytest
from personal_hub.providers.base import ChatMessage, ChatRequest

# Лимит вывода настраивается: reasoning-моделям (например, DeepSeek Flash)
# нужно больше 8 токенов, иначе весь бюджет уходит на reasoning_tokens и
# видимого текста не остаётся.
MAX_TOKENS = int(os.getenv("LIVE_MAX_TOKENS", "256"))

# Один и тот же минимальный промпт: цена ответа ограничена max_tokens.
CHAT_PROMPT = "Ответь одним словом: ok"


def _chat_request(model: str) -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=[ChatMessage(role="user", content=CHAT_PROMPT)],
        max_tokens=MAX_TOKENS,
    )


async def test_live_health_and_models(live_provider) -> None:
    """Health и каталог моделей реального провайдера доступны (бесплатно)."""
    health = await live_provider.adapter.health(live_provider.connection)
    assert health.ok is True
    models = await live_provider.adapter.list_models(live_provider.connection)
    assert models
    assert any(model.external_id == live_provider.chat_model for model in models)


async def test_live_chat_completion_with_usage(live_provider, live_budget) -> None:
    """Непотоковый чат: текст непустой, usage распарсен, бюджет учтён."""
    live_budget.ensure_available()
    completion = await live_provider.adapter.chat_complete(
        live_provider.connection, _chat_request(live_provider.chat_model)
    )
    live_budget.charge(
        live_provider.cost(live_provider.chat_model, completion.usage)
    )
    assert completion.text.strip()
    if completion.usage is not None:
        # Если провайдер отдал usage, токены должны быть распарсены.
        assert completion.usage.get("prompt_tokens", 0) > 0


async def test_live_streaming_chat(live_provider, live_budget) -> None:
    """Streaming: дельты доезжают, usage (если отдан) учитывается бюджетом."""
    live_budget.ensure_available()
    chunks: list[str] = []
    usage: dict | None = None
    async for chunk in live_provider.adapter.stream_chat(
        live_provider.connection, _chat_request(live_provider.chat_model)
    ):
        if chunk.content_delta:
            chunks.append(chunk.content_delta)
        if chunk.usage:
            usage = chunk.usage
    live_budget.charge(live_provider.cost(live_provider.chat_model, usage))
    assert "".join(chunks).strip()


async def test_live_embeddings(live_provider, live_budget) -> None:
    """Эмбеддинги реального провайдера (если задана LIVE_EMBEDDING_MODEL)."""
    if live_provider.embedding_model is None:
        pytest.skip("LIVE_EMBEDDING_MODEL не задан — эмбеддинги не проверяются")
    live_budget.ensure_available()
    result = await live_provider.adapter.embed(
        live_provider.connection, ["personal ai hub"], live_provider.embedding_model
    )
    live_budget.charge(
        live_provider.cost(live_provider.embedding_model, result.usage)
    )
    assert result.vectors and len(result.vectors[0]) > 0
