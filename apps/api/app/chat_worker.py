"""Фоновая генерация чата (worker-задача внутри процесса API).

Запускается как asyncio-задача из POST /conversations/{id}/messages, стримит
ответ провайдера, публикует SSE-события и сохраняет сообщение в БД.
"""
from __future__ import annotations

import asyncio
import logging
import uuid

from personal_hub.db.engine import get_session_factory
from personal_hub.models import Message, MessageStatus
from personal_hub.providers.base import ChatProvider, ChatRequest, ProviderConnection
from personal_hub.providers.errors import ProviderError

from app.generation_manager import GenerationState, generation_manager

logger = logging.getLogger("api.chat")


async def run_generation(
    generation_id: uuid.UUID,
    connection: ProviderConnection,
    adapter: ChatProvider,
    request: ChatRequest,
) -> None:
    """Выполняет генерацию: стримит, публикует события и фиксирует результат.

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
