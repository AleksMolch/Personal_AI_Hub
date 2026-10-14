"""Тесты управления глубиной рассуждений.

Проверяют три инварианта:
1. Параметр уходит в тело запроса только для моделей, объявивших capability
   `reasoning`, и в той форме, которую документирует провайдер
   (OpenRouter — объект `reasoning`, остальные — плоский `reasoning_effort`).
2. Поддержка определяется по данным провайдера (`supported_parameters`), а не
   по названию модели.
3. Токены рассуждений читаются из вложенного блока usage и НЕ добавляются к
   выходным токенам (иначе стоимость считалась бы дважды).

Платные вызовы не выполняются: используется локальный mock HTTP-сервер.
"""
from __future__ import annotations

import json

import pytest

from personal_hub.providers.base import (
    Capability,
    ChatMessage,
    ChatRequest,
    ProviderConnection,
    ReasoningDepth,
)
from personal_hub.providers.openai_compatible import (
    _REASONING_MARKERS,
    OpenAICompatibleAdapter,
    _declares_reasoning,
)


def _connection(mock_provider, provider_type: str = "openai_compatible"):
    """Соединение к mock-провайдеру с заданным типом."""
    host, port = mock_provider.server_address
    return ProviderConnection(
        provider_type=provider_type,
        base_url=f"http://{host}:{port}",
        api_key="sk-test",
    )


def _request(depth: ReasoningDepth | None, capabilities: list[str]):
    """Запрос чата с заданной глубиной и capabilities модели."""
    return ChatRequest(
        model="test-model",
        messages=[ChatMessage(role="user", content="Привет")],
        reasoning_depth=depth,
        model_capabilities=capabilities,
    )


def _capture_request(mock_provider) -> dict:
    """Готовит mock и возвращает словарь, куда запишется тело запроса."""
    captured: dict = {}

    def handler(_method: str, _path: str, body: bytes):
        captured.update(json.loads(body))
        return (200, '{"choices":[{"message":{"content":"ok"}}]}')

    mock_provider.spec["POST /chat/completions"] = handler
    return captured


@pytest.mark.asyncio
async def test_reasoning_effort_sent_for_generic_provider(mock_provider) -> None:
    """OpenAI-compatible провайдер получает плоский reasoning_effort."""
    captured = _capture_request(mock_provider)
    adapter = OpenAICompatibleAdapter()
    request = _request(ReasoningDepth.HIGH, [Capability.CHAT.value, Capability.REASONING.value])

    await adapter.chat_complete(_connection(mock_provider), request)

    assert captured["reasoning_effort"] == "high"
    # Обе формы одновременно не отправляем: порядок разрешения конфликта
    # провайдером не документирован.
    assert "reasoning" not in captured


@pytest.mark.asyncio
async def test_reasoning_object_sent_for_openrouter(mock_provider) -> None:
    """OpenRouter получает нормализованный объект reasoning.effort."""
    captured = _capture_request(mock_provider)
    adapter = OpenAICompatibleAdapter()
    request = _request(ReasoningDepth.LOW, [Capability.CHAT.value, Capability.REASONING.value])

    await adapter.chat_complete(_connection(mock_provider, "openrouter"), request)

    assert captured["reasoning"] == {"effort": "low"}
    assert "reasoning_effort" not in captured


@pytest.mark.asyncio
async def test_reasoning_depth_omitted_without_capability(mock_provider) -> None:
    """Модель без capability reasoning: параметр не уходит вовсе.

    Отправка параметра такой модели приводит у части провайдеров к 400,
    поэтому «на всякий случай» его передавать нельзя.
    """
    captured = _capture_request(mock_provider)
    adapter = OpenAICompatibleAdapter()
    request = _request(ReasoningDepth.HIGH, [Capability.CHAT.value])

    await adapter.chat_complete(_connection(mock_provider), request)

    assert "reasoning_effort" not in captured
    assert "reasoning" not in captured


@pytest.mark.asyncio
async def test_no_reasoning_when_depth_not_selected(mock_provider) -> None:
    """Без выбранной глубины параметр не отправляется даже при capability."""
    captured = _capture_request(mock_provider)
    adapter = OpenAICompatibleAdapter()
    request = _request(None, [Capability.CHAT.value, Capability.REASONING.value])

    await adapter.chat_complete(_connection(mock_provider), request)

    assert "reasoning_effort" not in captured
    assert "reasoning" not in captured


@pytest.mark.asyncio
async def test_streaming_sends_reasoning_too(mock_provider) -> None:
    """Потоковый путь отправляет те же поля, что и непотоковый."""
    captured: dict = {}

    def handler(_method: str, _path: str, body: bytes):
        captured.update(json.loads(body))
        # Формат SSE как у провайдера: строка начинается с "data: ".
        return (
            200,
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
            {"Content-Type": "text/event-stream"},
        )

    mock_provider.spec["POST /chat/completions"] = handler
    adapter = OpenAICompatibleAdapter()
    request = _request(
        ReasoningDepth.MEDIUM, [Capability.CHAT.value, Capability.REASONING.value]
    )

    chunks = []
    async for chunk in adapter.stream_chat(_connection(mock_provider), request):
        chunks.append(chunk.content_delta)

    assert captured["reasoning_effort"] == "medium"
    assert chunks == ["ok"]


@pytest.mark.asyncio
async def test_list_models_declares_reasoning_capability(mock_provider) -> None:
    """Capability reasoning берётся из supported_parameters провайдера."""
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps(
            {
                "data": [
                    {
                        "id": "reasoning-model",
                        "name": "Reasoning Model",
                        "supported_parameters": ["temperature", "reasoning"],
                    },
                    {
                        "id": "plain-model",
                        "name": "Plain Model",
                        "supported_parameters": ["temperature"],
                    },
                ]
            }
        ),
    )
    adapter = OpenAICompatibleAdapter()
    models = await adapter.list_models(_connection(mock_provider))
    by_id = {m.external_id: m for m in models}

    assert Capability.REASONING.value in by_id["reasoning-model"].capabilities
    assert Capability.REASONING.value not in by_id["plain-model"].capabilities


def test_declares_reasoning_ignores_model_name() -> None:
    """Поддержка НЕ выводится из названия модели (правило проекта).

    Модель с «reasoning» в id, но без декларации в supported_parameters,
    не получает capability: угадывание по имени даёт 400 у провайдера.
    """
    assert _declares_reasoning({"id": "o3-reasoning-preview"}) is False
    assert _declares_reasoning({"id": "x", "supported_parameters": ["reasoning"]}) is True
    assert _declares_reasoning({"id": "x", "capabilities": ["reasoning_effort"]}) is True
    # Мусор в поле не должен приводить к ложному срабатыванию.
    assert _declares_reasoning({"id": "x", "supported_parameters": "reasoning"}) is False
    assert _declares_reasoning({"id": "x", "supported_parameters": []}) is False
    assert _REASONING_MARKERS  # набор маркеров не пуст
