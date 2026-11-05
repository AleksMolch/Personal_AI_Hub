"""Эндпоинты защищённых режимов: подготовка и подтверждение (ADR-0007).

Назначение: показать пользователю, что именно уйдёт внешней модели, получить его
подтверждение и только затем разрешить отправку. Логика хранения и проверок
живёт в `personal_hub.protection.repository`; здесь — HTTP-контракт.

Место в архитектуре: API-слой. Наружу ничего не отправляет: prepare только
сохраняет подготовку, commit помечает её подтверждённой.

Инварианты (проверяются тестами):
1. Пока флаг `PROTECTION_MODES_ENABLED` выключен, эндпоинты отвечают понятным
   отказом: UI не может показать «работающую» защиту.
2. Prepare работает только в режиме `protected_hybrid`: в облачном режиме
   санитизация не нужна, в локальном — внешняя отправка запрещена.
3. Commit принимает только тот digest и ревизию, которые пользователь видел;
   устаревший или изменённый preview отклоняется до сетевого вызова.
4. Исходные значения не возвращаются API: preview содержит только псевдонимы.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from personal_hub.config import get_settings
from personal_hub.db.engine import get_session
from personal_hub.models import (
    Conversation,
    Message,
    MessageStatus,
    ModelProfile,
    ProtectionAuditLog,
    ProtectionEntity,
    ProviderCredential,
    User,
)
from personal_hub.protection.detector import detect
from personal_hub.protection.errors import ProtectionError
from personal_hub.protection.modes import ProtectionMode
from personal_hub.protection.repository import (
    commit_preparation,
    create_preparation,
    payload_digest,
    record_audit,
)
from personal_hub.protection.sanitizer import sanitize
from personal_hub.protection.vault import EntityVault
from personal_hub.security.crypto import get_cipher
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.schemas import (
    ProtectionAuditOut,
    ProtectionCommitOut,
    ProtectionCommitRequest,
    ProtectionEntityOut,
    ProtectionPrepareRequest,
    ProtectionPreviewOut,
)

router = APIRouter(prefix="/api/v1/protection", tags=["protection"])

_PREPARE_NOTE = (
    "Ничего не отправлено. Проверьте, что в sanitized-версии нет лишнего, и "
    "подтвердите — только после этого текст уйдёт внешней модели. Исходные "
    "значения останутся локально и будут восстановлены в ответе."
)


def _require_enabled() -> None:
    """Отказывает, пока защищённые режимы не включены на сервере."""
    if not get_settings().protection_modes_enabled:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Защищённые режимы выключены на сервере (PROTECTION_MODES_ENABLED=0).",
        )


async def _owned_conversation(
    session: AsyncSession, user: User, conversation_id: uuid.UUID
) -> Conversation:
    """Загружает диалог пользователя или отвечает 404.

    Чужой диалог неотличим от отсутствующего: иначе перебором можно узнать о
    существовании чужих conversation_id.
    """
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.user_id == user.id,
        )
    )
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диалог не найден.")
    return conversation


async def _history(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[Message]:
    """Возвращает историю в том же виде, в каком её увидит провайдер.

    Фильтры и порядок совпадают с отправкой сообщения: только завершённые
    сообщения user/assistant. Иначе digest подготовки не совпал бы с payload,
    который реально уходит модели.
    """
    result = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.role.in_(["user", "assistant"]),
            Message.status == MessageStatus.COMPLETED.value,
        )
        .order_by(Message.created_at, Message.id)
    )
    return list(result.scalars().all())


@router.get("/audit", response_model=list[ProtectionAuditOut])
async def list_audit(
    limit: int = 100,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ProtectionAuditOut]:
    """Возвращает журнал защищённых операций пользователя.

    Журнал содержит метаданные (действие, диалог, подготовка, ревизия) и не
    содержит текстов сообщений или исходных значений: он нужен для разбора
    инцидентов, а не как копия данных.

    Args:
        limit: Сколько последних событий вернуть (1..500).
        user: Текущий пользователь.
        session: Асинхронная сессия.

    Returns:
        События от новых к старым.
    """
    safe_limit = max(1, min(limit, 500))
    rows = (
        await session.execute(
            select(ProtectionAuditLog)
            .where(ProtectionAuditLog.user_id == user.id)
            .order_by(ProtectionAuditLog.created_at.desc())
            .limit(safe_limit)
        )
    ).scalars().all()
    return [ProtectionAuditOut.model_validate(row) for row in rows]


@router.get("/local-runtime", response_model=dict)
async def local_runtime_readiness(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Сообщает, готов ли локальный режим: есть ли помеченные локальные модели.

    Готовность не проверяет сеть и не угадывает локальность по адресу: она
    честно сообщает только то, что пользователь объявил сам. Реальный runtime
    (Ollama/LM Studio) должен быть запущен пользователем отдельно; если его
    нет, вызов провайдера завершится ошибкой соединения, а не тихой отправкой
    в облако.

    Args:
        user: Текущий пользователь.
        session: Асинхронная сессия.

    Returns:
        Флаг доступности локального режима и список локальных моделей.
    """
    rows = (
        await session.execute(
            select(ModelProfile, ProviderCredential)
            .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
            .where(
                ProviderCredential.user_id == user.id,
                ProviderCredential.enabled.is_(True),
                ProviderCredential.is_local.is_(True),
                ModelProfile.enabled.is_(True),
            )
        )
    ).all()
    return {
        "available": bool(rows),
        "models": [
            {
                "model_profile_id": str(model.id),
                "display_name": model.display_name or model.external_model_id,
                "provider": provider.display_name,
            }
            for model, provider in rows
        ],
        "note": (
            "Локальный провайдер объявлен пользователем; доступность самого "
            "runtime проверяется при вызове."
            if rows
            else "Нет моделей локального провайдера. Добавьте Ollama/LM Studio "
            "и отметьте провайдера как локальный."
        ),
    }


@router.post(
    "/conversations/{conversation_id}/prepare",
    response_model=ProtectionPreviewOut,
)
async def prepare_protection(
    conversation_id: uuid.UUID,
    payload: ProtectionPrepareRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProtectionPreviewOut:
    """Готовит sanitized-контекст и показывает его до отправки.

    Args:
        conversation_id: Диалог пользователя.
        payload: Новое сообщение и словарь организаций.
        user: Текущий пользователь.
        session: Асинхронная сессия.

    Returns:
        Preview: приватные и sanitized-сообщения, digest, ревизия, сущности.

    Raises:
        HTTPException: 400 при выключенной защите или неподходящем режиме,
            404 для чужого диалога.
    """
    _require_enabled()
    conversation = await _owned_conversation(session, user, conversation_id)
    if conversation.protection_mode != ProtectionMode.PROTECTED_HYBRID.value:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Подготовка доступна только в режиме «Защищённый гибрид». "
            "Переключите режим диалога.",
        )

    history = await _history(session, conversation_id)
    messages: list[dict[str, str]] = [
        {"role": message.role, "content": message.content} for message in history
    ]
    messages.append({"role": "user", "content": payload.text})

    cipher = get_cipher()
    vault = EntityVault(encrypt=cipher.encrypt, decrypt=cipher.decrypt)
    # Область стабильности привязана к ревизии: в пределах одного preview
    # одинаковые значения получают один псевдоним.
    scope = f"{conversation_id}:{conversation.protection_revision}"

    private_messages: list[str] = []
    sanitized_messages: list[str] = []
    for message in messages:
        spans = detect(message["content"], dictionary=payload.dictionary)
        sanitized = sanitize(message["content"], spans, vault, scope)
        private_messages.append(message["content"])
        sanitized_messages.append(sanitized.text)

    sanitized_text = "\n\n".join(
        f"{message['role']}: {text}"
        for message, text in zip(messages, sanitized_messages, strict=True)
    )
    digest = payload_digest({"messages": messages})

    try:
        preparation = await create_preparation(
            session,
            user_id=user.id,
            conversation_id=conversation_id,
            mode=conversation.protection_mode,
            revision=conversation.protection_revision,
            private_digest=digest,
            sanitized_text=sanitized_text,
            sanitized_messages=sanitized_messages,
            vault=vault,
        )
    except ProtectionError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.message) from exc

    entities = [
        ProtectionEntityOut(
            placeholder=placeholder,
            category=entry.category,
            occurrences=sanitized_text.count(placeholder),
        )
        for placeholder, entry in vault.entries.items()
    ]

    # Журнал: кто и когда готовил запрос. Тексты сюда не попадают.
    await record_audit(
        session,
        user_id=user.id,
        conversation_id=conversation_id,
        action="prepare",
        details={
            "preparation_id": str(preparation.id),
            "revision": preparation.revision,
            "entities": len(entities),
            "messages": len(sanitized_messages),
        },
    )
    await session.commit()

    return ProtectionPreviewOut(
        preparation_id=preparation.id,
        mode=preparation.mode,
        revision=preparation.revision,
        digest=digest,
        private_messages=private_messages,
        sanitized_messages=sanitized_messages,
        sanitized_text=sanitized_text,
        entities=entities,
        expires_at=preparation.expires_at,
        note=_PREPARE_NOTE,
    )


@router.post(
    "/conversations/{conversation_id}/commit",
    response_model=ProtectionCommitOut,
)
async def commit_protection(
    conversation_id: uuid.UUID,
    payload: ProtectionCommitRequest,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ProtectionCommitOut:
    """Подтверждает подготовку: после этого текст можно отправлять модели.

    Args:
        conversation_id: Диалог пользователя.
        payload: Идентификатор подготовки, digest и ревизия из preview.
        user: Текущий пользователь.
        session: Асинхронная сессия.

    Returns:
        Подтверждённая подготовка с sanitized-текстом и числом сущностей.

    Raises:
        HTTPException: 400 при выключенной защите, 404/409/410 по кодам
            репозитория (нет подготовки, устарела, изменилась, истекла).
    """
    _require_enabled()
    # Проверяем владение диалогом: commit не должен работать для чужого id.
    await _owned_conversation(session, user, conversation_id)

    try:
        preparation = await commit_preparation(
            session,
            user_id=user.id,
            preparation_id=payload.preparation_id,
            digest=payload.digest,
            revision=payload.revision,
        )
    except ProtectionError as exc:
        raise _http_error(exc) from exc

    entities_count = int(
        await session.scalar(
            select(func.count(ProtectionEntity.id)).where(
                ProtectionEntity.preparation_id == preparation.id
            )
        )
        or 0
    )
    await record_audit(
        session,
        user_id=user.id,
        conversation_id=conversation_id,
        action="commit",
        details={
            "preparation_id": str(preparation.id),
            "revision": preparation.revision,
            "status": preparation.status,
            "entities": entities_count,
        },
    )
    await session.commit()
    return ProtectionCommitOut(
        preparation_id=preparation.id,
        status=preparation.status,
        revision=preparation.revision,
        sanitized_text=preparation.sanitized_text,
        entities_count=entities_count,
        note=(
            "Запрос подтверждён. Внешней модели уйдёт только sanitized-текст, "
            "исходные значения останутся локально. Повторное подтверждение "
            "не создаёт второй запрос."
        ),
    )


def _http_error(exc: ProtectionError) -> HTTPException:
    """Переводит стабильный код ошибки в HTTP-статус."""
    status_code = {
        "PROTECTION_NOT_FOUND": status.HTTP_404_NOT_FOUND,
        "PROTECTION_DIGEST_MISMATCH": status.HTTP_409_CONFLICT,
        "PROTECTION_PREVIEW_STALE": status.HTTP_409_CONFLICT,
        "PROTECTION_PREPARATION_EXPIRED": status.HTTP_410_GONE,
        "PROTECTION_EMPTY_PREPARATION": status.HTTP_400_BAD_REQUEST,
    }.get(exc.code, status.HTTP_400_BAD_REQUEST)
    return HTTPException(status_code, f"{exc.message} ({exc.code})")
