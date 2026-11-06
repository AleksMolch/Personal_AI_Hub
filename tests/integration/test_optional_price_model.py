"""Интеграционные тесты модели без цены (ADR-0007, срез 6).

Проверяют требование: модель без цены можно использовать, usage сохраняется,
стоимость остаётся unknown, а не превращается в ноль; предупреждение попадает
в снимок сообщения; бюджет не блокирует такой вызов.

SSE-чтение ограничено таймаутом: иначе сбой фоновой генерации превращался бы в
вечное зависание теста вместо понятной ошибки.
"""
from __future__ import annotations

import asyncio
import json

from httpx import AsyncClient

# Сколько ждём закрытия потока. Реальная генерация с mock-провайдером
# укладывается в секунды; таймаут нужен, чтобы сбой не вешал весь прогон.
_EVENTS_TIMEOUT = 20.0


def _sse_body(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks)


async def _setup(client: AsyncClient, mock_provider) -> tuple[dict, str, str]:
    """Готовит провайдера и модель БЕЗ цены; возвращает заголовки и id."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps({"data": [{"id": "free-model", "name": "Free"}]}),
    )
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
    conversation = await client.post(
        "/api/v1/conversations", json={"title": "Без цены"}, headers=headers
    )
    return headers, model_id, conversation.json()["id"]


async def _events(client: AsyncClient, generation_id: str, headers: dict) -> list[dict]:
    """Читает SSE-события генерации с жёстким таймаутом."""

    async def read() -> list[dict]:
        events: list[dict] = []
        async with client.stream(
            "GET", f"/api/v1/generations/{generation_id}/events", headers=headers
        ) as resp:
            assert resp.status_code == 200
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[len("data:") :].strip()))
        return events

    return await asyncio.wait_for(read(), timeout=_EVENTS_TIMEOUT)


async def test_model_without_price_is_usable_and_cost_unknown(
    client: AsyncClient, mock_provider
) -> None:
    """Без цены генерация работает, usage пишется с cost_state=unknown."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    mock_provider.spec["POST /chat/completions"] = (
        200,
        _sse_body(
            '{"choices":[{"delta":{"content":"Ответ"}}]}',
            '{"choices":[{"delta":{},"finish_reason":"stop"}],'
            '"usage":{"prompt_tokens":11,"completion_tokens":2}}',
            "[DONE]",
        ),
        {"Content-Type": "text/event-stream"},
    )

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Сколько стоит?", "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    events = await _events(client, resp.json()["generation_id"], headers)
    assert any(event["event"] == "generation.completed" for event in events)

    records = (await client.get("/api/v1/usage/records", headers=headers)).json()
    assert len(records) == 1
    record = records[0]
    assert record["cost_state"] == "unknown"
    # Неизвестная стоимость не должна выглядеть как ноль.
    assert record["cost_amount"] is None
    assert record["units_json"]["input_tokens"] == 11

    detail = await client.get(
        f"/api/v1/conversations/{conversation_id}", headers=headers
    )
    assistant = [m for m in detail.json()["messages"] if m["role"] == "assistant"][0]
    assert assistant["content"] == "Ответ"
    assert assistant["model_snapshot"]["pricing"]["known"] is False
    assert "неизвестна" in assistant["model_snapshot"]["pricing"]["warning"]


async def test_model_without_price_is_not_blocked_by_budget(
    client: AsyncClient, mock_provider
) -> None:
    """Нулевой бюджет не мешает вызову без цены: резервировать нечего."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    await client.put(
        "/api/v1/budgets",
        json={"daily_limit": "0.00", "monthly_limit": "0.00"},
        headers=headers,
    )
    mock_provider.spec["POST /chat/completions"] = (
        200,
        _sse_body('{"choices":[{"delta":{"content":"ok"}}]}', "[DONE]"),
        {"Content-Type": "text/event-stream"},
    )

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Привет", "model_profile_id": model_id},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    await _events(client, resp.json()["generation_id"], headers)
    records = (await client.get("/api/v1/usage/records", headers=headers)).json()
    # Провайдер не прислал usage: пишем локальную оценку токенов, но стоимость
    # всё равно unknown — вызов не должен исчезать из истории.
    assert len(records) == 1
    assert records[0]["cost_amount"] is None
    assert records[0]["units_json"]["input_tokens"] > 0
    assert records[0]["units_json"]["operation"] == "chat"
