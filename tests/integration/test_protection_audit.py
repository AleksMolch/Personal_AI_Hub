"""Интеграционные тесты журнала защищённых операций (ADR-0007, срез 7).

Проверяют: prepare/commit/отправка пишут метаданные, журнал не содержит
исходных значений и текстов, чужие события не видны.
"""
from __future__ import annotations

import json
import uuid

import pytest
from httpx import AsyncClient
from personal_hub.config import get_settings
from personal_hub.db.engine import get_session_factory
from personal_hub.models import ProtectionAuditLog, User

_TEXT = "Договор с ООО «Ромашка». Почта: ivan.petrov@example.com"


@pytest.fixture
def protection_enabled(monkeypatch):
    """Включает защищённые режимы: иначе эндпоинты честно отказывают."""
    monkeypatch.setenv("PROTECTION_MODES_ENABLED", "1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _setup(client: AsyncClient, mock_provider) -> tuple[dict, str, str]:
    """Готовит админа, провайдера, модель с ценой и гибридный диалог."""
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
    conversation = await client.post(
        "/api/v1/conversations", json={"title": "Аудит"}, headers=headers
    )
    conversation_id = conversation.json()["id"]
    await client.patch(
        f"/api/v1/conversations/{conversation_id}",
        json={"protection_mode": "protected_hybrid"},
        headers=headers,
    )
    return headers, model_id, conversation_id


async def test_audit_records_operations_without_content(
    client: AsyncClient, mock_provider, protection_enabled
) -> None:
    """prepare, commit и отправка попадают в журнал без текстов и значений."""
    headers, model_id, conversation_id = await _setup(client, mock_provider)
    mock_provider.spec["POST /chat/completions"] = (
        200,
        "".join(
            f"data: {chunk}\n\n"
            for chunk in (
                '{"choices":[{"delta":{"content":"ok"}}]}',
                '{"choices":[{"delta":{},"finish_reason":"stop"}]}',
                "[DONE]",
            )
        ),
        {"Content-Type": "text/event-stream"},
    )
    preview = (
        await client.post(
            f"/api/v1/protection/conversations/{conversation_id}/prepare",
            json={"text": _TEXT, "dictionary": {"org": ["ООО «Ромашка»"]}},
            headers=headers,
        )
    ).json()
    await client.post(
        f"/api/v1/protection/conversations/{conversation_id}/commit",
        json={
            "preparation_id": preview["preparation_id"],
            "digest": preview["digest"],
            "revision": preview["revision"],
        },
        headers=headers,
    )
    send = await client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={
            "content": _TEXT,
            "model_profile_id": model_id,
            "preparation_id": preview["preparation_id"],
        },
        headers=headers,
    )
    assert send.status_code == 200, send.text

    audit = (await client.get("/api/v1/protection/audit", headers=headers)).json()
    actions = [event["action"] for event in audit]
    assert "prepare" in actions
    assert "commit" in actions
    assert "message_sent" in actions

    # Ни текста, ни почты, ни названия организации в журнале нет.
    payload = json.dumps(audit, ensure_ascii=False)
    assert "ivan.petrov@example.com" not in payload
    assert "Ромашка" not in payload
    assert "Договор" not in payload


async def test_audit_is_user_scoped(
    client: AsyncClient, mock_provider, protection_enabled
) -> None:
    """Чужие события в журнал пользователя не попадают."""
    headers, _, _ = await _setup(client, mock_provider)
    factory = get_session_factory()
    async with factory() as session:
        other = User(username="other-audit", password_hash="x", is_admin=False)
        session.add(other)
        await session.flush()
        session.add(
            ProtectionAuditLog(
                user_id=other.id,
                conversation_id=None,
                action="prepare",
                details={"note": "чужое событие"},
            )
        )
        await session.commit()

    audit = (await client.get("/api/v1/protection/audit", headers=headers)).json()

    assert audit == []
