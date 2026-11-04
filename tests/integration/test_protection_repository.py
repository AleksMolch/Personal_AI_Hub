"""Интеграционные тесты репозитория защищённых подготовок (ADR-0007, срез 2).

Проверяют главное для денег и приватности: подготовка сохраняется с
шифротекстом, commit проверяет digest/revision, повторный commit идемпотентен,
чужая подготовка не видна, истёкшая — отклоняется.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from personal_hub.db.engine import get_session_factory
from personal_hub.models import Message, ProtectionEntity, User
from personal_hub.protection.detector import detect
from personal_hub.protection.errors import ProtectionError
from personal_hub.protection.repository import (
    commit_preparation,
    create_preparation,
    get_preparation,
    load_vault,
    payload_digest,
)
from personal_hub.protection.sanitizer import restore, sanitize
from personal_hub.protection.vault import EntityVault
from personal_hub.security.crypto import get_cipher

_TEXT = (
    "Договор с ООО «Ромашка» подписан. "
    "Почта: ivan.petrov@example.com, телефон +7 999 123-45-67."
)


async def _setup(client: AsyncClient) -> tuple[dict[str, str], uuid.UUID, uuid.UUID]:
    """Создаёт админа и диалог, возвращает (заголовки, user_id, conversation_id)."""
    resp = await client.post(
        "/api/v1/auth/bootstrap",
        json={"username": "admin", "password": "supersecret"},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    user_id = uuid.UUID(me.json()["id"])
    conversation = await client.post(
        "/api/v1/conversations", json={"title": "Тест"}, headers=headers
    )
    return headers, user_id, uuid.UUID(conversation.json()["id"])


def _prepared(private_text: str) -> tuple[str, EntityVault, str]:
    """Санитизирует текст и возвращает (sanitized, vault, digest).

    Организации детектор знает только из словаря пользователя — в тесте
    передаём его явно, иначе «Ромашка» осталась бы в тексте.
    """
    cipher = get_cipher()
    vault = EntityVault(encrypt=cipher.encrypt, decrypt=cipher.decrypt)
    spans = detect(private_text, dictionary={"org": ["ООО «Ромашка»"]})
    sanitized = sanitize(private_text, spans, vault, "scope")
    digest = payload_digest({"text": private_text})
    return sanitized.text, vault, digest


@pytest.mark.asyncio
async def test_preparation_persists_ciphertext_and_restores(client: AsyncClient) -> None:
    """Vault сохраняется в БД в шифрованном виде и восстанавливает текст."""
    _, user_id, conversation_id = await _setup(client)
    sanitized, vault, digest = _prepared(_TEXT)

    factory = get_session_factory()
    async with factory() as session:
        preparation = await create_preparation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            mode="protected_hybrid",
            revision=0,
            private_digest=digest,
            sanitized_text=sanitized,
            vault=vault,
        )
        rows = (
            await session.execute(
                select(ProtectionEntity).where(
                    ProtectionEntity.preparation_id == preparation.id
                )
            )
        ).scalars().all()
    async with factory() as session:
        restored = await load_vault(session, preparation_id=preparation.id)

    assert preparation.status == "pending"
    assert rows, "vault должен сохранить хотя бы одну сущность"
    # В базе нет открытых значений.
    assert all("Ромашка" not in row.ciphertext for row in rows)
    assert all("ivan.petrov" not in row.ciphertext for row in rows)
    assert "Ромашка" not in sanitized
    assert restore(sanitized, restored).text == _TEXT


@pytest.mark.asyncio
async def test_commit_is_idempotent(client: AsyncClient) -> None:
    """Повторный commit не создаёт вторую подготовку и не меняет статус."""
    _, user_id, conversation_id = await _setup(client)
    sanitized, vault, digest = _prepared(_TEXT)
    factory = get_session_factory()

    async with factory() as session:
        preparation = await create_preparation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            mode="protected_hybrid",
            revision=0,
            private_digest=digest,
            sanitized_text=sanitized,
            vault=vault,
        )
    async with factory() as session:
        first = await commit_preparation(
            session,
            user_id=user_id,
            preparation_id=preparation.id,
            digest=digest,
            revision=0,
        )
    async with factory() as session:
        second = await commit_preparation(
            session,
            user_id=user_id,
            preparation_id=preparation.id,
            digest=digest,
            revision=0,
        )

    assert first.id == second.id
    assert second.status == "committed"
    assert second.committed_at is not None


@pytest.mark.asyncio
async def test_commit_rejects_wrong_digest(client: AsyncClient) -> None:
    """Изменённое содержимое отклоняется до отправки."""
    _, user_id, conversation_id = await _setup(client)
    sanitized, vault, digest = _prepared(_TEXT)
    factory = get_session_factory()

    async with factory() as session:
        preparation = await create_preparation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            mode="protected_hybrid",
            revision=0,
            private_digest=digest,
            sanitized_text=sanitized,
            vault=vault,
        )
    async with factory() as session:
        with pytest.raises(ProtectionError) as exc_info:
            await commit_preparation(
                session,
                user_id=user_id,
                preparation_id=preparation.id,
                digest=payload_digest({"text": "другой текст"}),
                revision=0,
            )

    assert exc_info.value.code == "PROTECTION_DIGEST_MISMATCH"


@pytest.mark.asyncio
async def test_commit_rejects_stale_revision(client: AsyncClient) -> None:
    """Reвизия диалога важнее: устаревший preview не отправляется."""
    _, user_id, conversation_id = await _setup(client)
    sanitized, vault, digest = _prepared(_TEXT)
    factory = get_session_factory()

    async with factory() as session:
        preparation = await create_preparation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            mode="protected_hybrid",
            revision=0,
            private_digest=digest,
            sanitized_text=sanitized,
            vault=vault,
        )
    async with factory() as session:
        with pytest.raises(ProtectionError) as exc_info:
            await commit_preparation(
                session,
                user_id=user_id,
                preparation_id=preparation.id,
                digest=digest,
                revision=1,
            )

    assert exc_info.value.code == "PROTECTION_PREVIEW_STALE"


@pytest.mark.asyncio
async def test_expired_preparation_is_rejected(client: AsyncClient) -> None:
    """Истёкшая подготовка не может быть подтверждена."""
    _, user_id, conversation_id = await _setup(client)
    sanitized, vault, digest = _prepared(_TEXT)
    factory = get_session_factory()

    async with factory() as session:
        preparation = await create_preparation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            mode="protected_hybrid",
            revision=0,
            private_digest=digest,
            sanitized_text=sanitized,
            vault=vault,
            ttl=timedelta(seconds=-1),
        )
    async with factory() as session:
        with pytest.raises(ProtectionError) as exc_info:
            await commit_preparation(
                session,
                user_id=user_id,
                preparation_id=preparation.id,
                digest=digest,
                revision=0,
            )

    assert exc_info.value.code == "PROTECTION_PREPARATION_EXPIRED"


@pytest.mark.asyncio
async def test_foreign_user_cannot_read_preparation(client: AsyncClient) -> None:
    """Чужая подготовка неотличима от отсутствующей."""
    _, user_id, conversation_id = await _setup(client)
    sanitized, vault, digest = _prepared(_TEXT)
    factory = get_session_factory()

    async with factory() as session:
        preparation = await create_preparation(
            session,
            user_id=user_id,
            conversation_id=conversation_id,
            mode="protected_hybrid",
            revision=0,
            private_digest=digest,
            sanitized_text=sanitized,
            vault=vault,
        )
        # Второй пользователь создаётся напрямую: bootstrap допускает только
        # первого администратора.
        other = User(
            username="other",
            password_hash="x",
            is_admin=False,
        )
        session.add(other)
        await session.commit()
        other_id = other.id

    async with factory() as session:
        with pytest.raises(ProtectionError) as exc_info:
            await get_preparation(
                session, user_id=other_id, preparation_id=preparation.id
            )

    assert exc_info.value.code == "PROTECTION_NOT_FOUND"


@pytest.mark.asyncio
async def test_message_protection_snapshot_roundtrip(client: AsyncClient) -> None:
    """Снимок защиты сообщения хранит sanitized-текст для следующего turn."""
    _, _, conversation_id = await _setup(client)
    sanitized, _, _ = _prepared(_TEXT)
    factory = get_session_factory()

    async with factory() as session:
        message = Message(
            conversation_id=conversation_id,
            role="user",
            content=_TEXT,
            protection={
                "mode": "protected_hybrid",
                "sanitized": sanitized,
                "status": "restored",
            },
        )
        session.add(message)
        await session.commit()
        message_id = message.id
    async with factory() as session:
        stored = await session.get(Message, message_id)

    assert stored is not None
    assert stored.protection["sanitized"] == sanitized
    assert "Ромашка" not in stored.protection["sanitized"]
    assert stored.content == _TEXT


@pytest.mark.asyncio
async def test_capabilities_reports_protection_flag(
    client: AsyncClient, monkeypatch
) -> None:
    """UI узнаёт, включена ли защита, и не показывает нерабочий переключатель."""
    from personal_hub.config import get_settings

    monkeypatch.setenv("PROTECTION_MODES_ENABLED", "0")
    get_settings.cache_clear()
    disabled = (await client.get("/api/v1/capabilities")).json()
    assert disabled["protection"]["enabled"] is False
    assert set(disabled["protection"]["modes"]) == {
        "cloud_controlled",
        "protected_hybrid",
        "local_only",
    }

    monkeypatch.setenv("PROTECTION_MODES_ENABLED", "1")
    get_settings.cache_clear()
    enabled = (await client.get("/api/v1/capabilities")).json()
    assert enabled["protection"]["enabled"] is True
    get_settings.cache_clear()
