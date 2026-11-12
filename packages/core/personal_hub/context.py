"""Окно контекста диалога: обрезка истории перед отправкой (ADR-0008).

Назначение: не отправлять провайдеру всю историю бесконечно. Длинный диалог
растёт в цене и может превысить лимит модели, поэтому окно ограничивается
числом сообщений и токенов.

Место в архитектуре: доменный помощник; используется и при подготовке
(`prepare`), и при отправке сообщения (`create_message`), чтобы digest
подготовки совпадал с фактическим payload.

Инварианты:
1. Оставляем самые свежие сообщения: старые обычно менее важны для ответа.
2. Последнее сообщение не отбрасывается никогда — иначе модель ответит без
   вопроса.
3. Порядок оставшихся сообщений сохраняется.
4. Если лимит модели известен, он важнее настройки: превышать контекст нельзя.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from personal_hub.costs import estimate_tokens


@dataclass(frozen=True)
class TrimmedHistory:
    """Результат обрезки истории.

    Attributes:
        messages: Оставленные сообщения в исходном порядке.
        dropped: Сколько сообщений отброшено.
        estimated_tokens: Оценка токенов оставленных сообщений.
    """

    messages: list[dict]
    dropped: int
    estimated_tokens: int


def trim_history(
    messages: Sequence[dict],
    *,
    max_messages: int,
    max_tokens: int,
) -> TrimmedHistory:
    """Обрезает историю до окна по числу сообщений и токенов.

    Args:
        messages: Сообщения в хронологическом порядке (dict с `role` и
            `content`).
        max_messages: Максимум сообщений в окне (>= 1).
        max_tokens: Максимум токенов в окне (>= 1).

    Returns:
        Оставленные сообщения, число отброшенных и оценка токенов.
    """
    if not messages:
        return TrimmedHistory(messages=[], dropped=0, estimated_tokens=0)

    kept: list[dict] = []
    used_tokens = 0
    for message in reversed(messages):
        content = str(message.get("content", ""))
        tokens = estimate_tokens(content)
        is_last = not kept
        # Последнее сообщение оставляем даже при превышении лимита: без него
        # запрос теряет смысл. Для остальных соблюдаем оба ограничения.
        if not is_last and (len(kept) >= max_messages or used_tokens + tokens > max_tokens):
            break
        kept.append(message)
        used_tokens += tokens

    kept.reverse()
    return TrimmedHistory(
        messages=kept,
        dropped=len(messages) - len(kept),
        estimated_tokens=used_tokens,
    )


def effective_max_tokens(
    *,
    configured: int,
    context_limit: int | None,
    output_limit: int | None,
    reserve: int,
) -> int:
    """Считает лимит входных токенов с учётом контекста модели.

    Args:
        configured: Настройка `chat_history_max_tokens`.
        context_limit: Лимит контекста модели (может быть неизвестен).
        output_limit: Лимит ответа модели (может быть неизвестен).
        reserve: Резерв под системную инструкцию и ответ.

    Returns:
        Лимит входа: минимум из настройки и доступного места у модели, но не
        меньше 2000 токенов, иначе окно стало бы бесполезным.
    """
    if not context_limit:
        return configured
    available = context_limit - (output_limit or 0) - reserve
    return max(2000, min(configured, available))
