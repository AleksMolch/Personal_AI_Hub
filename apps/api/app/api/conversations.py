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
from personal_hub.config import get_settings
from personal_hub.db.engine import get_session
from personal_hub.models import (
    Conversation,
    Message,
    MessageStatus,
    ModelProfile,
    ProviderCredential,
    User,
)
from personal_hub.providers.base import (
    Capability,
    ChatMessage,
    ChatRequest,
    ProviderConnection,
    ReasoningDepth,
)
from personal_hub.providers.registry import get_adapter
from personal_hub.security.crypto import get_cipher
from personal_hub.websearch.base import WebCitation, WebSearchError
from personal_hub.websearch.service import (
    build_citations,
    build_search_context,
    build_search_system_prompt,
    format_search_warnings,
    get_web_search_provider,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import check_and_reserve, estimate_units, get_latest_price
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

    # Глубину рассуждений принимаем только для моделей, которые её объявили.
    # Иначе вернули бы 400 от провайдера или молча проигнорировали параметр —
    # и то, и другое хуже явной ошибки: пользователь думал бы, что управляет
    # поведением модели.
    reasoning_depth: ReasoningDepth | None = None
    if payload.reasoning_depth is not None:
        if Capability.REASONING.value not in (model.capabilities or []):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Выбранная модель не поддерживает управление глубиной "
                "рассуждений.",
            )
        reasoning_depth = ReasoningDepth(payload.reasoning_depth)

    # Цена обязательна: неизвестная цена блокирует запрос (strict mode).
    price = await get_latest_price(session, model.id)
    if price is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Цена модели не задана. Задайте цену на странице «Модели».",
        )

    # История для провайдера: завершённые сообщения + новое сообщение пользователя.
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
    chat_messages.append(ChatMessage(role="user", content=payload.content))

    # Веб-поиск выполняется ДО обращения к LLM и только один раз на запрос:
    # автоматические «уточняющие» поиски модели недопустимы, так как
    # неуправляемо увеличивают расходы и задержку.
    settings = get_settings()
    web_citations: list[WebCitation] = []
    search_context = ""
    search_warning: str | None = None
    if payload.web_search:
        provider_search = get_web_search_provider(settings)
        if provider_search is None:
            # Возможность выключена на сервере: сообщаем явно, а не молча
            # игнорируем флаг — иначе пользователь считал бы, что поиск был.
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Веб-поиск выключен на сервере (WEB_SEARCH_ENABLED=0).",
            )
        try:
            response = await provider_search.search(
                payload.content, limit=settings.web_search_max_results
            )
        except WebSearchError as exc:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                f"{exc.message} ({exc.code})",
            ) from exc
        web_citations = build_citations(response)
        search_context = build_search_context(
            web_citations, max_chars=settings.web_search_max_context_chars
        )
        search_warning = format_search_warnings(response)

    # Системная инструкция: при веб-поиске она дополняется контекстом и
    # правилами цитирования. Основная инструкция диалога сохраняется.
    system_prompt = conversation.system_instruction
    if search_context:
        search_prompt = build_search_system_prompt(search_context)
        system_prompt = (
            f"{system_prompt}\n\n{search_prompt}" if system_prompt else search_prompt
        )

    # Оценка стоимости и резервирование ДО отправки провайдеру.
    history_text = "\n".join(
        (conversation.system_instruction or "") + m.content for m in chat_messages
    )
    estimated_units = estimate_units(
        history_text, model.output_limit, reasoning_depth
    )

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
    # reasoning_depth и источники веб-поиска сохраняются в снимке: история
    # должна объяснять, с какой глубиной и по каким источникам получен ответ,
    # иначе позднее нельзя обосновать ни его содержание, ни стоимость.
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
            "reasoning_depth": reasoning_depth.value if reasoning_depth else None,
            "web_search": {
                "used": bool(search_context),
                "warning": search_warning,
                "citations": [
                    {
                        "index": c.index,
                        "title": c.title,
                        "url": c.url,
                        "snippet": c.snippet,
                    }
                    for c in web_citations
                ],
            },
        },
    )
    session.add(generation)
    await session.flush()

    # Резервирование (может поднять BudgetExceededError → 402, всё откатывается).
    billing = await check_and_reserve(
        session,
        user.id,
        price=price,
        estimated_units=estimated_units,
        message_id=generation.id,
    )
    await session.commit()
    await session.refresh(generation)

    request = ChatRequest(
        model=model.external_model_id,
        messages=chat_messages,
        system=system_prompt,
        reasoning_depth=reasoning_depth,
        model_capabilities=list(model.capabilities or []),
    )

    _spawn(
        run_generation(
            generation.id,
            _connection_for(provider),
            get_adapter(provider.provider_type),
            request,
            user_id=user.id,
            provider_id=provider.id,
            model_profile_id=model.id,
            billing=billing,
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
