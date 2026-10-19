"""Интеграционные тесты каталога моделей: ручное объявление возможностей.

Регрессия на практическую проблему: DeepSeek принимает `reasoning_effort`, но
не перечисляет поддерживаемые параметры в `/models`, поэтому capability
`reasoning` не появлялась и селектор глубины в чате был скрыт. Пользователь
должен иметь возможность объявить возможность сам, а backend — отправлять
параметр только после такого объявления.
"""
from __future__ import annotations

import json

from httpx import AsyncClient


async def _setup(client: AsyncClient, mock_provider) -> tuple[dict, str]:
    """Готовит администратора, провайдера и модель; возвращает (headers, model_id)."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    host, port = mock_provider.server_address
    # Провайдер НЕ рекламирует reasoning — как реальный DeepSeek.
    mock_provider.spec["GET /models"] = (
        200,
        json.dumps({"data": [{"id": "deepseek-flash", "name": "DeepSeek Flash"}]}),
    )
    provider = await client.post(
        "/api/v1/providers",
        json={
            "provider_type": "openai_compatible",
            "display_name": "DeepSeek",
            "base_url": f"http://{host}:{port}",
            "api_key": "sk-test",
        },
        headers=headers,
    )
    await client.post(
        f"/api/v1/providers/{provider.json()['id']}/sync-models", headers=headers
    )
    model_id = (await client.get("/api/v1/models", headers=headers)).json()[0]["id"]
    return headers, model_id


async def test_model_capabilities_can_be_declared_manually(
    client: AsyncClient, mock_provider
) -> None:
    """Capability reasoning добавляется вручную и сохраняется в каталоге."""
    headers, model_id = await _setup(client, mock_provider)

    catalog = (await client.get("/api/v1/models", headers=headers)).json()
    assert "reasoning" not in catalog[0]["capabilities"]

    resp = await client.patch(
        f"/api/v1/models/{model_id}",
        json={"capabilities": ["reasoning"]},
        headers=headers,
    )

    assert resp.status_code == 200
    capabilities = resp.json()["capabilities"]
    assert "reasoning" in capabilities
    # Базовые возможности синхронизации не потерялись.
    assert "chat" in capabilities
    assert "streaming" in capabilities


async def test_reasoning_effort_is_sent_after_manual_declaration(
    client: AsyncClient, mock_provider
) -> None:
    """После объявления capability параметр реально уходит провайдеру.

    Это ключевая проверка сквозного сценария: пользователь включил опцию в UI,
    и следующее сообщение несёт `reasoning_effort` в теле запроса.
    """
    headers, model_id = await _setup(client, mock_provider)
    await client.patch(
        f"/api/v1/models/{model_id}",
        json={"capabilities": ["reasoning"]},
        headers=headers,
    )
    await client.post(
        "/api/v1/prices",
        json={
            "model_profile_id": model_id,
            "input_per_million": "0.3",
            "output_per_million": "1.2",
            "currency": "USD",
        },
        headers=headers,
    )

    captured: dict = {}

    def chat_handler(_method: str, _path: str, body: bytes):
        captured.update(json.loads(body))
        return (
            200,
            'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n',
            {"Content-Type": "text/event-stream"},
        )

    mock_provider.spec["POST /chat/completions"] = chat_handler

    conversation = await client.post(
        "/api/v1/conversations", json={"title": "T"}, headers=headers
    )
    resp = await client.post(
        f"/api/v1/conversations/{conversation.json()['id']}/messages",
        json={
            "content": "привет",
            "model_profile_id": model_id,
            "reasoning_depth": "high",
        },
        headers=headers,
    )
    assert resp.status_code == 200

    # Дожидаемся завершения генерации, затем проверяем тело запроса.
    async with client.stream(
        "GET",
        f"/api/v1/generations/{resp.json()['generation_id']}/events",
        headers=headers,
    ) as stream:
        async for _ in stream.aiter_lines():
            pass

    assert captured["reasoning_effort"] == "high"


async def test_unknown_capability_is_rejected(
    client: AsyncClient, mock_provider
) -> None:
    """Неизвестные capabilities не попадают в JSONB."""
    headers, model_id = await _setup(client, mock_provider)

    resp = await client.patch(
        f"/api/v1/models/{model_id}",
        json={"capabilities": ["teleportation"]},
        headers=headers,
    )

    assert resp.status_code == 422
    assert "teleportation" in resp.json()["error"]["message"]


async def test_foreign_model_is_not_editable(
    client: AsyncClient, mock_provider
) -> None:
    """Чужая модель недоступна: 404, а не 403 с раскрытием существования."""
    headers, _ = await _setup(client, mock_provider)

    resp = await client.patch(
        "/api/v1/models/00000000-0000-0000-0000-000000000000",
        json={"capabilities": ["reasoning"]},
        headers=headers,
    )

    assert resp.status_code == 404
