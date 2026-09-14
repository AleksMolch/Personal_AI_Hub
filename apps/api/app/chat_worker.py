"""Фоновая генерация чата (worker-задача внутри процесса API).

Запускается как asyncio-задача из POST /conversations/{id}/messages, стримит
ответ провайдера, публикует SSE-события, сохраняет сообщение и фиксирует
расход (UsageRecord) с закрытием резервирования.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from personal_hub.db.engine import get_session_factory
from personal_hub.models import Message, MessageStatus
from personal_hub.providers.base import ChatProvider, ChatRequest, ProviderConnection
from personal_hub.providers.errors import ProviderError

from app.billing import BillingContext, finalize_generation, release_reservation
from app.generation_manager import GenerationState, generation_manager

logger = logging.getLogger("api.chat")


async def run_generation(
    generation_id: uuid.UUID,
    connection: ProviderConnection,
    adapter: ChatProvider,
    request: ChatRequest,
    *,
    user_id: uuid.UUID,
    provider_id: uuid.UUID,
    model_profile_id: uuid.UUID,
    billing: BillingContext | None,
) -> None:
    """Выполняет генерацию: стримит, публикует события, фиксирует расход.

    Результат пишется в message с id = generation_id. Ошибки провайдера
    нормализуются в stable code и публикуются как generation.failed.
    """
    state: GenerationState = generation_manager.create(generation_id)
    await generation_manager.publish(
        state, {"event": "generation.started", "generation_id": str(generation_id)}
    )

    parts: list[str] = []
    usage: dict | None = None
    status = MessageStatus.COMPLETED.value
    error_code: str | None = None
    completed = False

    try:
        async for chunk in adapter.stream_chat(connection, request):
            if state.cancel_event.is_set():
                raise asyncio.CancelledError()
            if chunk.content_delta:
                parts.append(chunk.content_delta)
                await generation_manager.publish(
                    state, {"event": "content.delta", "delta": chunk.content_delta}
                )
            if chunk.usage:
                usage = chunk.usage
        completed = True
        await generation_manager.publish(
            state, {"event": "generation.completed", "usage": usage}
        )
    except asyncio.CancelledError:
        status = MessageStatus.CANCELLED.value
        await generation_manager.publish(state, {"event": "generation.cancelled"})
    except ProviderError as exc:
        status = MessageStatus.FAILED.value
        error_code = exc.code
        await generation_manager.publish(
            state,
            {
                "event": "generation.failed",
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
            },
        )
    except Exception:
        logger.exception("generation_unexpected_error")
        status = MessageStatus.FAILED.value
        error_code = "INTERNAL_ERROR"
        await generation_manager.publish(
            state,
            {
                "event": "generation.failed",
                "code": "INTERNAL_ERROR",
                "message": "Внутренняя ошибка.",
            },
        )
    finally:
        content = "".join(parts)
        await _persist_result(generation_id, content, status, error_code, usage)
        if billing is not None:
            await _finalize_billing(
                user_id=user_id,
                provider_id=provider_id,
                model_profile_id=model_profile_id,
                message_id=generation_id,
                usage=usage,
                billing=billing,
                completed=completed,
            )
        await generation_manager.finish(state)


async def _persist_result(
    generation_id: uuid.UUID,
    content: str,
    status: str,
    error_code: str | None,
    usage: dict | None,
) -> None:
    """Сохраняет итоговый контент и статус сообщения-генерации."""
    factory = get_session_factory()
    async with factory() as session:
        message = await session.get(Message, generation_id)
        if message is None:
            return
        message.content = content
        message.status = status
        message.error_code = error_code
        if usage:
            snapshot = dict(message.model_snapshot or {})
            snapshot["usage"] = usage
            message.model_snapshot = snapshot
        await session.commit()


async def _finalize_billing(
    *,
    user_id: uuid.UUID,
    provider_id: uuid.UUID,
    model_profile_id: uuid.UUID,
    message_id: uuid.UUID,
    usage: dict | None,
    billing: BillingContext,
    completed: bool,
) -> None:
    """Фиксирует расход или освобождает резервирование."""
    factory = get_session_factory()
    async with factory() as session:
        if completed:
            await finalize_generation(
                session,
                user_id=user_id,
                provider_id=provider_id,
                model_profile_id=model_profile_id,
                message_id=message_id,
                usage=usage,
                billing=billing,
                provider_request_id=None,
            )
        else:
            await release_reservation(session, billing.reservation_id)
        await session.commit()


async def mark_interrupted_generations() -> None:
    """При старте помечает зависшие streaming-генерации как interrupted.

    Выполняется на startup: после рестарта процесса незавершённые генерации
    не должны оставаться вечно в статусе streaming.
    """
    factory = get_session_factory()
    async with factory() as session:
        from sqlalchemy import update

        await session.execute(
            update(Message)
            .where(Message.status == MessageStatus.STREAMING.value)
            .values(status=MessageStatus.INTERRUPTED.value, error_code="RESTARTED")
        )
        await session.commit()
