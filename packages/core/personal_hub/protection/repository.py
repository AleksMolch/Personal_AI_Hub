"""Репозиторий защищённых подготовок и vault в PostgreSQL (ADR-0007).

Назначение: сохранять prepared-запросы и карту псевдонимов, проверять
целостность перед отправкой (digest + revision), обеспечивать идемпотентность
повторного commit и загрузку vault для локального восстановления.

Место в архитектуре: доменный слой между API и моделями. Работает только с
локальной базой; наружу ничего не отправляет.

Инварианты:
1. Псевдонимы и зашифрованные значения принадлежат конкретной подготовке и
   пользователю; чужая подготовка неотличима от отсутствующей.
2. Commit принимает только digest и ревизию, которые пользователь видел на
   preview. Иначе запрос отклоняется ДО сетевого вызова.
3. Повторный commit не создаёт второй подготовки и не приводит к повторной
   оплате: он идемпотентен по `preparation_id`.
4. Секреты в vault не попадают: они удаляются на этапе санитизации.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from personal_hub.models import (
    Conversation,
    PreparationStatus,
    ProtectionEntity,
    ProtectionPreparation,
)
from personal_hub.protection.errors import ProtectionError
from personal_hub.protection.vault import EntityVault, VaultEntry
from personal_hub.security.crypto import get_cipher

# Сколько подготовка живёт до истечения. Preview показывается пользователю, и
# он может отвлечься; сутки — компромисс между удобством и тем, что в базе не
# копится бесконечно много расшифровываемых карт.
DEFAULT_TTL = timedelta(days=1)


def payload_digest(payload: Mapping[str, Any]) -> str:
    """Считает стабильный digest payload.

    Канонический JSON (сортировка ключей, без пробелов) нужен, чтобы один и тот
    же смысл давал один и тот же digest независимо от порядка ключей в словаре.

    Args:
        payload: Данные запроса (модель, сообщения, параметры).

    Returns:
        SHA-256 в hex.
    """
    canonical = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def create_preparation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    conversation_id: uuid.UUID,
    mode: str,
    revision: int,
    private_digest: str,
    sanitized_text: str,
    vault: EntityVault,
    ttl: timedelta = DEFAULT_TTL,
) -> ProtectionPreparation:
    """Сохраняет подготовку и её vault.

    Args:
        session: Асинхронная сессия.
        user_id: Владелец.
        conversation_id: Диалог, к которому относится подготовка.
        mode: Режим защиты на момент подготовки.
        revision: Ревизия диалога на момент подготовки.
        private_digest: Digest приватного payload (что видел пользователь).
        sanitized_text: Текст, который уйдёт провайдеру.
        vault: Vault с псевдонимами и шифротекстом.
        ttl: Срок жизни подготовки.

    Returns:
        Созданная подготовка (без коммита).

    Raises:
        ProtectionError: Если у vault нет записей (нечего отправлять) или
            подготовка не сохраняется.
    """
    if not vault.entries:
        raise ProtectionError(
            "PROTECTION_EMPTY_PREPARATION",
            "Подготовка не содержит защищённых сущностей: отправлять нечего.",
        )

    now = datetime.now(UTC)
    preparation = ProtectionPreparation(
        user_id=user_id,
        conversation_id=conversation_id,
        mode=mode,
        status=PreparationStatus.PENDING.value,
        revision=revision,
        private_digest=private_digest,
        sanitized_digest=payload_digest({"text": sanitized_text}),
        sanitized_text=sanitized_text,
        expires_at=now + ttl,
    )
    session.add(preparation)
    await session.flush()

    for placeholder, entry in vault.entries.items():
        session.add(
            ProtectionEntity(
                preparation_id=preparation.id,
                placeholder=placeholder,
                category=entry.category,
                ciphertext=entry.ciphertext,
            )
        )
    await session.commit()
    await session.refresh(preparation)
    return preparation


async def get_preparation(
    session: AsyncSession, *, user_id: uuid.UUID, preparation_id: uuid.UUID
) -> ProtectionPreparation:
    """Загружает подготовку пользователя или сообщает, что её нет.

    Чужая подготовка возвращает тот же код, что и отсутствующая: иначе можно
    перебором узнать о существовании чужих диалогов.

    Args:
        session: Асинхронная сессия.
        user_id: Владелец.
        preparation_id: Идентификатор подготовки.

    Returns:
        Подготовка.

    Raises:
        ProtectionError: `PROTECTION_NOT_FOUND`, если подготовки нет.
    """
    result = await session.execute(
        select(ProtectionPreparation).where(
            ProtectionPreparation.id == preparation_id,
            ProtectionPreparation.user_id == user_id,
        )
    )
    preparation = result.scalar_one_or_none()
    if preparation is None:
        raise ProtectionError(
            "PROTECTION_NOT_FOUND", "Подготовка не найдена."
        )
    return preparation


async def commit_preparation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    preparation_id: uuid.UUID,
    digest: str,
    revision: int,
) -> ProtectionPreparation:
    """Подтверждает подготовку к отправке.

    Идемпотентность: повторный commit уже подтверждённой подготовки с тем же
    digest возвращает её без изменений, поэтому повторный клик не создаёт второй
    платный запрос. Несовпадение digest или ревизии, истечение срока — отказ.

    Args:
        session: Асинхронная сессия.
        user_id: Владелец.
        preparation_id: Подготовка.
        digest: Digest, который пользователь видел на preview.
        revision: Текущая ревизия диалога.

    Returns:
        Подтверждённая подготовка.

    Raises:
        ProtectionError: При истечении, несовпадении digest, устаревшей ревизии
            или неверном статусе.
    """
    # Блокировка строки: два одновременных commit не должны создать два вызова.
    result = await session.execute(
        select(ProtectionPreparation)
        .where(
            ProtectionPreparation.id == preparation_id,
            ProtectionPreparation.user_id == user_id,
        )
        .with_for_update()
    )
    preparation = result.scalar_one_or_none()
    if preparation is None:
        raise ProtectionError("PROTECTION_NOT_FOUND", "Подготовка не найдена.")

    if preparation.status == PreparationStatus.COMMITTED.value:
        if preparation.private_digest != digest:
            raise ProtectionError(
                "PROTECTION_DIGEST_MISMATCH",
                "Подготовка уже подтверждена с другим содержимым.",
            )
        return preparation

    if preparation.status != PreparationStatus.PENDING.value:
        raise ProtectionError(
            "PROTECTION_PREPARATION_EXPIRED",
            "Подготовка истекла. Подготовьте запрос заново.",
        )

    now = datetime.now(UTC)
    if preparation.expires_at is not None and preparation.expires_at < now:
        preparation.status = PreparationStatus.EXPIRED.value
        await session.commit()
        raise ProtectionError(
            "PROTECTION_PREPARATION_EXPIRED",
            "Подготовка истекла. Подготовьте запрос заново.",
        )

    if digest != preparation.private_digest:
        raise ProtectionError(
            "PROTECTION_DIGEST_MISMATCH",
            "Содержимое запроса изменилось после подготовки. Покажите preview заново.",
        )

    if revision != preparation.revision:
        raise ProtectionError(
            "PROTECTION_PREVIEW_STALE",
            "Контекст диалога изменился после подготовки. Покажите preview заново.",
        )

    # Дополнительно сверяем актуальную ревизию диалога: пользователь мог
    # изменить режим или контекст в другой вкладке.
    current_revision = await session.scalar(
        select(Conversation.protection_revision).where(
            Conversation.id == preparation.conversation_id,
            Conversation.user_id == user_id,
        )
    )
    if current_revision is not None and current_revision != revision:
        raise ProtectionError(
            "PROTECTION_PREVIEW_STALE",
            "Контекст диалога изменился после подготовки. Покажите preview заново.",
        )

    preparation.status = PreparationStatus.COMMITTED.value
    preparation.committed_at = now
    await session.commit()
    await session.refresh(preparation)
    return preparation


async def load_vault(
    session: AsyncSession, *, preparation_id: uuid.UUID
) -> EntityVault:
    """Собирает vault подготовки для локального восстановления.

    Args:
        session: Асинхронная сессия.
        preparation_id: Подготовка.

    Returns:
        Vault с записями из базы; значения расшифровываются мастер-ключом.
    """
    cipher = get_cipher()
    vault = EntityVault(encrypt=cipher.encrypt, decrypt=cipher.decrypt)
    result = await session.execute(
        select(ProtectionEntity).where(
            ProtectionEntity.preparation_id == preparation_id
        )
    )
    for entity in result.scalars().all():
        vault.entries[entity.placeholder] = VaultEntry(
            placeholder=entity.placeholder,
            category=entity.category,
            ciphertext=entity.ciphertext,
            scope=str(preparation_id),
        )
    return vault


async def count_preparations(session: AsyncSession, *, user_id: uuid.UUID) -> int:
    """Число подготовок пользователя (для диагностики и тестов)."""
    return int(
        await session.scalar(
            select(func.count(ProtectionPreparation.id)).where(
                ProtectionPreparation.user_id == user_id
            )
        )
        or 0
    )
