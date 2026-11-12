"""Политика хранения данных (ADR-0008).

Назначение: не держать вечно то, что нужно лишь для работы. Архив убирает
диалог из обычного списка, не удаляя его; удаление выключено по умолчанию.
Артефакты защиты (подготовки и сущности) и журнал аудита чистятся по срокам.

Место в архитектуре: доменный модуль; вызывается фоновой задачей воркера и
тестами. Решения о данных не принимает: только применяет настройки.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from personal_hub.models import (
    Conversation,
    ProtectionAuditLog,
    ProtectionPreparation,
)


async def archive_idle_conversations(session: AsyncSession, days: int) -> int:
    """Архивирует диалоги, к которым не возвращались дольше срока.

    Args:
        session: Асинхронная сессия.
        days: Срок простоя в днях; 0 или меньше — действие выключено.

    Returns:
        Сколько диалогов архивировано.
    """
    if days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await session.execute(
        update(Conversation)
        .where(Conversation.archived.is_(False), Conversation.updated_at < cutoff)
        .values(archived=True)
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def delete_archived_conversations(session: AsyncSession, days: int) -> int:
    """Удаляет архивные диалоги, к которым не возвращались дольше срока.

    Удаление необратимо: сообщения уходят каскадом, записи расходов остаются с
    `message_id=NULL`. Поэтому по умолчанию срок равен нулю (выключено).

    Args:
        session: Асинхронная сессия.
        days: Срок простоя архивного диалога; 0 или меньше — выключено.

    Returns:
        Сколько диалогов удалено.
    """
    if days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await session.execute(
        delete(Conversation).where(
            Conversation.archived.is_(True),
            Conversation.updated_at < cutoff,
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_protection_artifacts(session: AsyncSession, days: int) -> int:
    """Удаляет просроченные подготовки и старые артефакты защиты.

    Сущности (псевдонимы) удаляются каскадом вместе с подготовкой. Сами
    сообщения не трогаем: восстановленный текст уже сохранён в них.

    Args:
        session: Асинхронная сессия.
        days: Срок хранения артефактов; 0 или меньше — выключено.

    Returns:
        Сколько подготовок удалено.
    """
    if days <= 0:
        return 0
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=days)
    result = await session.execute(
        delete(ProtectionPreparation).where(
            (ProtectionPreparation.expires_at < now)
            | (ProtectionPreparation.created_at < cutoff)
        )
    )
    return int(getattr(result, "rowcount", 0) or 0)


async def purge_audit_log(session: AsyncSession, days: int) -> int:
    """Удаляет старые записи журнала защищённых операций.

    Args:
        session: Асинхронная сессия.
        days: Срок хранения записей; 0 или меньше — выключено.

    Returns:
        Сколько записей удалено.
    """
    if days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=days)
    result = await session.execute(
        delete(ProtectionAuditLog).where(ProtectionAuditLog.created_at < cutoff)
    )
    return int(getattr(result, "rowcount", 0) or 0)



