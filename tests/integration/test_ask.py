"""Интеграционные тесты сквозного сценария «таблицы + документы» (ask)."""
from __future__ import annotations

import json

import pytest
from httpx import AsyncClient

_CSV = "name,amount\nA,1\nB,2\nC,3\n"


def _sql_or_answer(store: list[dict]):
    """Обработчик чата: на SQL-запрос возвращает SELECT, иначе — ответ."""

    def handler(_method: str, _path: str, body: bytes):
        store.append(json.loads(body))
        messages = store[-1].get("messages") or []
        is_sql = any(
            m.get("role") == "system" and "SQL" in (m.get("content") or "")
            for m in messages
        )
        content = "SELECT * FROM data LIMIT 3" if is_sql else "В таблице три строки."
        payload = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }
        return (200, json.dumps(payload), {"Content-Type": "application/json"})

    return handler


@pytest.mark.asyncio
async def test_ask_table_only(client: AsyncClient, mock_provider):
    """Вопрос по таблице генерирует SQL, выполняет его и синтезирует ответ."""
    store: list[dict] = []
    mock_provider.spec["POST /chat/completions"] = _sql_or_answer(store)

    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    host, port = mock_provider.server_address
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps({"data": [{"id": "gpt-x", "name": "GPT X"}]}),
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

    uploaded = await client.post(
        "/api/v1/assets/uploads",
        files={"file": ("data.csv", _CSV.encode(), "text/csv")},
        data={"kind": "table"},
        headers=headers,
    )
    asset_id = uploaded.json()["id"]

    result = await client.post(
        "/api/v1/ask",
        json={
            "question": "Сколько строк в таблице?",
            "table_asset_id": asset_id,
            "chat_model_profile_id": model_id,
        },
        headers=headers,
    )

    assert result.status_code == 200
    body = result.json()
    assert body["answer"] == "В таблице три строки."
    assert body["table"]["columns"] == ["name", "amount"]
    assert len(body["table"]["rows"]) == 3
    assert "SELECT" in body["table"]["sql"]
    # Два платных вызова: генерация SQL и синтез.
    assert len(store) == 2
