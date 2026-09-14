"""Интеграционные тесты биллинга: цены, бюджеты, запись расхода.

Проверяют: запись UsageRecord из SSE-usage (actual), блокировку бюджета до
отправки провайдеру (402 BUDGET_EXCEEDED) и summary.
"""
from __future__ import annotations

import json
from decimal import Decimal

from httpx import AsyncClient


async def _bootstrap(client: AsyncClient) -> dict:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _model(client: AsyncClient, headers: dict, mock_provider) -> str:
    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (200, '{"data": [{"id": "gpt-x", "name": "GPT X"}]}')
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
    catalog = await client.get("/api/v1/models", headers=headers)
    return catalog.json()[0]["id"]


async def _send_and_wait(client: AsyncClient, headers: dict, conversation_id: str, model_id: str):
    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Привет", "model_profile_id": model_id},
        headers=headers,
    )
    if resp.status_code != 200:
        return resp
    generation_id = resp.json()["generation_id"]
    events: list[dict] = []
    async with client.stream(
        "GET", f"/api/v1/generations/{generation_id}/events", headers=headers
    ) as stream:
        async for line in stream.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


async def test_usage_recorded_from_stream(client: AsyncClient, mock_provider) -> None:
    headers = await _bootstrap(client)
    model_id = await _model(client, headers, mock_provider)

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
    await client.put(
        "/api/v1/budgets",
        json={"daily_limit": "10.00", "monthly_limit": "100.00", "currency": "USD"},
        headers=headers,
    )

    mock_provider.spec["POST /chat/completions"] = (
        200,
        "data: {\"choices\":[{\"delta\":{\"content\":\"Привет\"}}]}\n\n"
        + "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}],"
        + "\"usage\":{\"prompt_tokens\":1000,\"completion_tokens\":500}}\n\n"
        + "data: [DONE]\n\n",
        {"Content-Type": "text/event-stream"},
    )

    conv = await client.post("/api/v1/conversations", json={}, headers=headers)
    events = await _send_and_wait(client, headers, conv.json()["id"], model_id)
    assert any(e["event"] == "generation.completed" for e in events)

    # Расход записан как actual: 1000*1/1M + 500*2/1M = 0.002.
    records = (await client.get("/api/v1/usage/records", headers=headers)).json()
    assert len(records) == 1
    assert records[0]["cost_state"] == "actual"
    assert Decimal(records[0]["cost_amount"]) == Decimal("0.002")

    summary = (await client.get("/api/v1/usage/summary", headers=headers)).json()
    assert Decimal(summary["today_cost"]) == Decimal("0.002")
    assert summary["today_input_tokens"] == 1000
    assert summary["today_output_tokens"] == 500


async def test_budget_blocks_before_provider(client: AsyncClient, mock_provider) -> None:
    headers = await _bootstrap(client)
    model_id = await _model(client, headers, mock_provider)

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
    # Очень маленький лимит: запрос должен быть заблокирован ДО отправки.
    await client.put(
        "/api/v1/budgets",
        json={"daily_limit": "0.00000001", "monthly_limit": "0.00000001", "currency": "USD"},
        headers=headers,
    )

    mock_provider.spec["POST /chat/completions"] = (
        200,
        "data: [DONE]\n\n",
        {"Content-Type": "text/event-stream"},
    )

    conv = await client.post("/api/v1/conversations", json={}, headers=headers)
    resp = await client.post(
        f"/api/v1/conversations/{conv.json()['id']}/messages",
        json={"content": "Привет", "model_profile_id": model_id},
        headers=headers,
    )
    assert resp.status_code == 402
    body = resp.json()
    assert body["error"]["code"] == "BUDGET_EXCEEDED"

    # Никакого расхода не записано, провайдер не вызывался.
    records = (await client.get("/api/v1/usage/records", headers=headers)).json()
    assert records == []


async def test_message_requires_price(client: AsyncClient, mock_provider) -> None:
    headers = await _bootstrap(client)
    model_id = await _model(client, headers, mock_provider)

    conv = await client.post("/api/v1/conversations", json={}, headers=headers)
    resp = await client.post(
        f"/api/v1/conversations/{conv.json()['id']}/messages",
        json={"content": "Привет", "model_profile_id": model_id},
        headers=headers,
    )
    assert resp.status_code == 400
