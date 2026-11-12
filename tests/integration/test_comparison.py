"""Интеграционные тесты сравнения моделей side-by-side."""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient


def _json_chat(store: list[dict]):
    """Обработчик /chat/completions: возвращает JSON-ответ и запоминает тело."""

    def handler(_method: str, _path: str, body: bytes):
        store.append(json.loads(body))
        payload = {
            "choices": [{"message": {"content": "Ответ модели"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return (200, json.dumps(payload), {"Content-Type": "application/json"})

    return handler


@pytest.mark.asyncio
async def test_compare_two_models(client: AsyncClient, mock_provider):
    """Оба вызова выполняются, ответы возвращаются в порядке запроса."""
    store: list[dict] = []
    mock_provider.spec["POST /chat/completions"] = _json_chat(store)

    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps(
            {"data": [{"id": "gpt-a", "name": "A"}, {"id": "gpt-b", "name": "B"}]}
        ),
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
    models = (await client.get("/api/v1/models", headers=headers)).json()
    assert len(models) == 2

    result = await client.post(
        "/api/v1/comparisons",
        json={
            "prompt": "Что лучше?",
            "model_profile_ids": [models[0]["id"], models[1]["id"]],
        },
        headers=headers,
    )

    assert result.status_code == 200
    assert len(result.json()["results"]) == 2
    assert all(item["content"] == "Ответ модели" for item in result.json()["results"])
    # Оба вызова реально ушли провайдеру.
    assert len(store) == 2
    assert {entry["model"] for entry in store} == {"gpt-a", "gpt-b"}


@pytest.mark.asyncio
async def test_compare_requires_two_models(client: AsyncClient):
    """Одна модель (или три) отклоняются валидацией."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    invalid = await client.post(
        "/api/v1/comparisons",
        json={"prompt": "Привет", "model_profile_ids": []},
        headers=headers,
    )
    assert invalid.status_code == 422
