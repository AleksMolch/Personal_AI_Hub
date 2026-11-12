"""Интеграционные тесты политики хранения (ADR-0008).

Проверяют, что архив не удаляет данные, удаление по умолчанию выключено, а
просроченные артефакты защиты и старый аудит чистятся.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from personal_hub.db.engine import get_session_factory
from personal_hub.models import (
    Conversation,
    ProtectionAuditLog,
    ProtectionPreparation,
)
from personal_hub.retention import (
    archive_idle_conversations,
    delete_archived_conversations,
    purge_audit_log,
    purge_protection_artifacts,
)

_OLD = datetime.now(UTC) - timedelta(days=120)


@pytest.mark.asyncio
async def test_retention_archives_and_purges_without_deleting_by_default(
    client: AsyncClient,
):
    """Старый диалог архивируется, удаление выключено, артефакты чистятся."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = me.json()["id"]

    factory = get_session_factory()
    async with factory() as session:
        conversation = Conversation(user_id=user_id, title="Старый диалог")
        conversation.updated_at = _OLD
        session.add(conversation)
        await session.flush()

        session.add(
            ProtectionAuditLog(
                user_id=user_id,
                conversation_id=conversation.id,
                action="message_sent",
                details={"mode": "cloud_controlled"},
                created_at=_OLD,
            )
        )
        session.add(
            ProtectionPreparation(
                user_id=user_id,
                conversation_id=conversation.id,
                mode="protected_hybrid",
                status="pending",
                revision=0,
                private_digest="digest",
                sanitized_digest="sanitized-digest",
                sanitized_text="sanitized",
                sanitized_messages=["sanitized"],
                expires_at=_OLD,
            )
        )
        await session.commit()

    async with factory() as session:
        archived = await archive_idle_conversations(session, 90)
        # Удаление по умолчанию выключено (0 дней).
        deleted = await delete_archived_conversations(session, 0)
        audit = await purge_audit_log(session, 90)
        artifacts = await purge_protection_artifacts(session, 30)
        await session.commit()

    assert archived == 1
    assert deleted == 0
    assert audit == 1
    assert artifacts == 1

    async with factory() as session:
        stored = await session.get(Conversation, conversation.id)
        # Архив не разрушает данные: диалог на месте и помечен архивным.
        assert stored is not None
        assert stored.archived is True
        # Повторный запуск идемпотентен.
        assert await archive_idle_conversations(session, 90) == 0
