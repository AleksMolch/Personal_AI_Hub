"""Загрузка истории диалога с окном контекста (ADR-0008).

Назначение: дать `prepare` и отправке сообщения один и тот же набор истории.
Если окно считалось бы по-разному, digest подготовки не совпал бы с payload, и
гибрид отклонял бы собственный preview.

Место в архитектуре: вспомогательный модуль API. Обращается к БД, но решений о
режимах не принимает.
"""
from __future__ import annotations

import uuid

from personal_hub.config import Settings
from personal_hub.context import TrimmedHistory, effective_max_tokens, trim_history
from personal_hub.models import Message, MessageStatus, ModelProfile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def load_history(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[Message]:
    """Возвращает завершённые сообщения диалога в хронологическом порядке.

    Фильтры совпадают с отправкой: только `user`/`assistant` и `completed`.
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


def build_window(
    history: list[Message],
    *,
    model: ModelProfile | None,
    settings: Settings,
) -> TrimmedHistory:
    """Строит окно контекста с учётом настроек и лимита модели.

    Args:
        history: Сообщения в хронологическом порядке.
        model: Модель, которой уйдёт запрос (может быть неизвестна в prepare).
        settings: Настройки приложения.

    Returns:
        Обрезанная история в виде словарей `role`/`content`.
    """
    messages = [
        {"role": message.role, "content": message.content} for message in history
    ]
    max_tokens = effective_max_tokens(
        configured=settings.chat_history_max_tokens,
        context_limit=model.context_limit if model else None,
        output_limit=model.output_limit if model else None,
        reserve=settings.chat_context_reserve_tokens,
    )
    return trim_history(
        messages,
        max_messages=settings.chat_history_max_messages,
        max_tokens=max_tokens,
    )
