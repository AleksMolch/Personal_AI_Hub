"""Диалоги: CRUD, отправка сообщения (создание генерации) и экспорт.

Отправка сообщения создаёт user-сообщение и assistant-сообщение (generation),
запускает фоновую генерацию и возвращает generation_id; поток событий
читается через GET /generations/{id}/events (SSE).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from personal_hub.db.engine import get_session
from personal_hub.models import (
    Conversation,
    Message,
    MessageStatus,
    ModelProfile,
    ProviderCredential,
    User,
)
from personal_hub.providers.base import ChatMessage, ChatRequest, ProviderConnection
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.chat_worker import run_generation
from app.deps import get_current_user
from app.schemas import (
    ConversationCreate,
    ConversationDetail,
    ConversationOut,
    ConversationUpdate,
    MessageCreate,
    MessageCreateResponse,
    MessageOut,
)

logger = logging.getLogger("api.conversations")

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])

# Сильные ссылки на фоновые генерации, чтобы asyncio не собирал задачи.
_background_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _get_owned_conversation(
    conversation_id, user: User, session: AsyncSession
) -> Conversation:
    result = await session.execute(
        select(Conversation).where(
            Conversation.id == conversation_id, Conversation.user_id == user.id
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Диалог не найден.")
    return conversation


async def _resolve_model(
    session: AsyncSession, user: User, model_profile_id: uuid.UUID | None
) -> tuple[ModelProfile, ProviderCredential]:
    """Возвращает модель и провайдера, проверяя принадлежность пользователю."""
    if model_profile_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Выберите модель.")
    result = await session.execute(
        select(ModelProfile)
        .join(ProviderCredential, ModelProfile.provider_id == ProviderCredential.id)
        .where(
            ModelProfile.id == model_profile_id,
            ProviderCredential.user_id == user.id,
            ModelProfile.enabled.is_(True),
            ProviderCredential.enabled.is_(True),
        )
    )
    model = result.scalar_one_or_none()
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Модель не найдена или отключена.")
    provider_result = await session.execute(
        select(ProviderCredential).where(ProviderCredential.id == model.provider_id)
    )
    provider = provider_result.scalar_one()
    return model, provider


def _connection_for(provider: ProviderCredential) -> ProviderConnection:
    return ProviderConnection(
        provider_type=provider.provider_type,
        base_url=provider.base_url,
        api_key=get_cipher().decrypt(provider.encrypted_secret),
    )


@router.get("", response_model=list[ConversationOut])
async def list_conversations(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    archived: bool = False,
) -> list[ConversationOut]:
    stmt = (
        select(Conversation)
        .where(Conversation.user_id == user.id, Conversation.archived == archived)
        .order_by(Conversation.updated_at.desc())
    )
    result = await session.execute(stmt)
    return [ConversationOut.model_validate(c) for c in result.scalars().all()]


@router.post("", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: ConversationCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationOut:
    conversation = Conversation(
        user_id=user.id,
        title=payload.title or "Новый диалог",
        model_profile_id=payload.model_profile_id,
        system_instruction=payload.system_instruction,
    )
    session.add(conversation)
    await session.commit()
    await session.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationDetail:
    conversation = await _get_owned_conversation(conversation_id, user, session)
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    )
    detail = ConversationDetail.model_validate(conversation)
    detail.messages = [MessageOut.model_validate(m) for m in result.scalars().all()]
    return detail


@router.patch("/{conversation_id}", response_model=ConversationOut)
async def update_conversation(
    conversation_id,
    payload: ConversationUpdate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ConversationOut:
    conversation = await _get_owned_conversation(conversation_id, user, session)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(conversation, field, value)
    await session.commit()
    await session.refresh(conversation)
    return ConversationOut.model_validate(conversation)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    conversation = await _get_owned_conversation(conversation_id, user, session)
    await session.delete(conversation)
    await session.commit()


@router.post("/{conversation_id}/messages", response_model=MessageCreateResponse)
async def create_message(
    conversation_id,
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MessageCreateResponse:
    """Создаёт сообщение и запускает генерацию (возвращает generation_id)."""
    conversation = await _get_owned_conversation(conversation_id, user, session)

    model_profile_id = payload.model_profile_id or conversation.model_profile_id
    model, provider = await _resolve_model(session, user, model_profile_id)

    # Сообщение пользователя.
    user_message = Message(
        conversation_id=conversation.id,
        role="user",
        content=payload.content,
        status=MessageStatus.COMPLETED.value,
        model_profile_id=model.id,
    )
    session.add(user_message)
    await session.flush()

    # Сообщение-генерация (ассистент).
    generation = Message(
        conversation_id=conversation.id,
        role="assistant",
        content="",
        parent_id=user_message.id,
        status=MessageStatus.STREAMING.value,
        model_profile_id=model.id,
        model_snapshot={
            "model": model.external_model_id,
            "provider_type": provider.provider_type,
            "display_name": model.display_name,
        },
    )
    session.add(generation)
    await session.commit()
    await session.refresh(generation)

    # История для провайдера: все завершённые user/assistant сообщения.
    history_result = await session.execute(
        select(Message)
        .where(
            Message.conversation_id == conversation.id,
            Message.role.in_(["user", "assistant"]),
            Message.status == MessageStatus.COMPLETED.value,
        )
        .order_by(Message.created_at, Message.id)
    )
    chat_messages = [
        ChatMessage(role=m.role, content=m.content) for m in history_result.scalars().all()
    ]
    if not chat_messages or chat_messages[-1].role != "user":
        # На случай рассинхронизации гарантируем, что последний — user.
        chat_messages.append(ChatMessage(role="user", content=payload.content))

    request = ChatRequest(
        model=model.external_model_id,
        messages=chat_messages,
        system=conversation.system_instruction,
    )

    _spawn(
        run_generation(
            generation.id,
            _connection_for(provider),
            get_adapter(provider.provider_type),
            request,
        )
    )

    return MessageCreateResponse(
        generation_id=generation.id,
        message=MessageOut.model_validate(generation),
    )


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id,
    fmt: str = "markdown",
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
):
    """Экспортирует диалог в Markdown или JSON."""
    from fastapi.responses import PlainTextResponse

    conversation = await _get_owned_conversation(conversation_id, user, session)
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at, Message.id)
    )
    messages = [MessageOut.model_validate(m) for m in result.scalars().all()]

    if fmt == "json":
        data = {
            "schema_version": 1,
            "title": conversation.title,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "status": m.status,
                    "model": m.model_snapshot.get("model"),
                }
                for m in messages
            ],
        }
        return PlainTextResponse(
            json.dumps(data, ensure_ascii=False, indent=2),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="conversation-{conversation.id}.json"'
            },
        )

    lines = [f"# {conversation.title}\n"]
    for m in messages:
        role = "Пользователь" if m.role == "user" else "Ассистент"
        lines.append(f"## {role}\n\n{m.content}\n")
    return PlainTextResponse(
        "\n".join(lines),
        media_type="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="conversation-{conversation.id}.md"'
        },
    )
