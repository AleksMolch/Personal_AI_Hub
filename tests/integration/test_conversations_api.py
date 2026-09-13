"""Интеграционные тесты диалогов и потоковой генерации.

Проверяют: создание диалога, отправку сообщения, SSE-поток, сохранение,
экспорт и обработку ошибки провайдера (mock HTTP-сервер).
"""
from __future__ import annotations

import json

from httpx import AsyncClient


async def _setup(client: AsyncClient, mock_provider, models_body: str) -> tuple[dict, str]:
    """Создаёт администратора, провайдера и модель; возвращает (headers, model_id)."""
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
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
    provider_id = provider.json()["id"]
    await client.post(f"/api/v1/providers/{provider_id}/sync-models", headers=headers)

    catalog = await client.get("/api/v1/models", headers=headers)
    model_id = catalog.json()[0]["id"]
    return headers, model_id


def _sse_body(*chunks: str) -> str:
    return "".join(f"data: {c}\n\n" for c in chunks)


async def _collect_events(
    client: AsyncClient, generation_id: str, headers: dict
) -> list[dict]:
    events: list[dict] = []
    async with client.stream(
        "GET", f"/api/v1/generations/{generation_id}/events", headers=headers
    ) as resp:
        assert resp.status_code == 200
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


async def test_streaming_chat_end_to_end(client: AsyncClient, mock_provider) -> None:
    headers, model_id = await _setup(
        client, mock_provider, '{"data": [{"id": "gpt-x", "name": "GPT X"}]}'
    )
    mock_provider.spec["POST /chat/completions"] = (
        200,
        _sse_body(
            '{"choices":[{"delta":{"content":"При"}}]}',
            '{"choices":[{"delta":{"content":"вет"}}]}',
            '{"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"total_tokens":5}}',
            "[DONE]",
        ),
        {"Content-Type": "text/event-stream"},
    )

    conv = await client.post(
        "/api/v1/conversations", json={"title": "Тест"}, headers=headers
    )
    conversation_id = conv.json()["id"]

    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "Привет", "model_profile_id": model_id},
        headers=headers,
    )
    assert resp.status_code == 200
    generation_id = resp.json()["generation_id"]

    events = await _collect_events(client, generation_id, headers)
    event_names = [e["event"] for e in events]
    assert "generation.started" in event_names
    assert "content.delta" in event_names
    assert "generation.completed" in event_names

    # Полный текст собран из дельт.
    full = "".join(e["delta"] for e in events if e["event"] == "content.delta")
    assert full == "Привет"

    # Сообщение сохранено в БД.
    detail = await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
    messages = detail.json()["messages"]
    assistant = [m for m in messages if m["role"] == "assistant"][0]
    assert assistant["status"] == "completed"
    assert assistant["content"] == "Привет"
    assert assistant["model_snapshot"]["usage"]["total_tokens"] == 5


async def test_streaming_provider_error(client: AsyncClient, mock_provider) -> None:
    headers, model_id = await _setup(
        client, mock_provider, '{"data": [{"id": "gpt-x", "name": "GPT X"}]}'
    )
    mock_provider.spec["POST /chat/completions"] = (401, '{"error": "bad key"}')

    conv = await client.post(
        "/api/v1/conversations", json={}, headers=headers
    )
    conversation_id = conv.json()["id"]
    resp = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "hi", "model_profile_id": model_id},
        headers=headers,
    )
    generation_id = resp.json()["generation_id"]

    events = await _collect_events(client, generation_id, headers)
    failed = [e for e in events if e["event"] == "generation.failed"]
    assert failed
    assert failed[0]["code"] == "PROVIDER_UNAUTHORIZED"

    detail = await client.get(f"/api/v1/conversations/{conversation_id}", headers=headers)
    assistant = [m for m in detail.json()["messages"] if m["role"] == "assistant"][0]
    assert assistant["status"] == "failed"
    assert assistant["error_code"] == "PROVIDER_UNAUTHORIZED"


async def test_conversation_crud_and_export(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    conv = await client.post("/api/v1/conversations", json={"title": "Диалог"}, headers=headers)
    conversation_id = conv.json()["id"]

    # Переименование.
    patched = await client.patch(
        f"/api/v1/conversations/{conversation_id}", json={"title": "Новое имя"}, headers=headers
    )
    assert patched.json()["title"] == "Новое имя"

    # Экспорт Markdown (пустой диалог).
    md = await client.get(
        f"/api/v1/conversations/{conversation_id}/export?fmt=markdown", headers=headers
    )
    assert md.status_code == 200
    assert "# Новое имя" in md.text

    # Экспорт JSON.
    js = await client.get(
        f"/api/v1/conversations/{conversation_id}/export?fmt=json", headers=headers
    )
    assert js.status_code == 200
    assert json.loads(js.text)["schema_version"] == 1

    # Удаление.
    deleted = await client.delete(f"/api/v1/conversations/{conversation_id}", headers=headers)
    assert deleted.status_code == 204
    assert (await client.get("/api/v1/conversations", headers=headers)).json() == []
