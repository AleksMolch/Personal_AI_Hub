"""Unit-тесты окна контекста (ADR-0008).

Проверяют инварианты обрезки: оставляем свежие сообщения, никогда не теряем
последнее, сохраняем порядок и уважаем лимит модели.
"""
from __future__ import annotations

from personal_hub.context import TrimmedHistory, effective_max_tokens, trim_history


def _message(role: str, content: str) -> dict:
    """Короткий конструктор сообщения для тестов."""
    return {"role": role, "content": content}


def test_empty_history_returns_empty():
    """Пустая история не падает и не считает токены."""
    result = trim_history([], max_messages=10, max_tokens=1000)

    assert result == TrimmedHistory(messages=[], dropped=0, estimated_tokens=0)


def test_keeps_only_recent_messages_by_count():
    """При лимите сообщений остаются самые свежие, порядок сохраняется."""
    history = [_message("user", f"вопрос {i}") for i in range(10)]

    result = trim_history(history, max_messages=3, max_tokens=100_000)

    assert [m["content"] for m in result.messages] == [
        "вопрос 7",
        "вопрос 8",
        "вопрос 9",
    ]
    assert result.dropped == 7


def test_keeps_recent_messages_by_tokens():
    """При лимите токенов старые сообщения отбрасываются первыми."""
    history = [_message("user", "a" * 400) for _ in range(5)]

    result = trim_history(history, max_messages=10, max_tokens=250)

    # 400 символов ≈ 100 токенов, поэтому в 250 токенов влезает два сообщения.
    assert len(result.messages) == 2
    assert result.dropped == 3
    assert result.estimated_tokens <= 250


def test_last_message_is_never_dropped():
    """Даже если последнее сообщение больше лимита, оно остаётся."""
    history = [
        _message("user", "короткое"),
        _message("user", "x" * 5000),
    ]

    result = trim_history(history, max_messages=10, max_tokens=10)

    assert result.messages == [history[-1]]
    assert result.dropped == 1


def test_effective_max_tokens_limits_by_model_context():
    """Лимит модели меньше настройки — окно сужается."""
    limit = effective_max_tokens(
        configured=24000,
        context_limit=8000,
        output_limit=2000,
        reserve=1000,
    )

    assert limit == 5000


def test_effective_max_tokens_without_model_uses_configured():
    """Без известного контекста модели остаётся настройка."""
    limit = effective_max_tokens(
        configured=24000,
        context_limit=None,
        output_limit=None,
        reserve=1000,
    )

    assert limit == 24000


def test_effective_max_tokens_never_below_minimum():
    """Слишком маленький контекст модели не делает окно бесполезным."""
    limit = effective_max_tokens(
        configured=24000,
        context_limit=1500,
        output_limit=500,
        reserve=1000,
    )

    assert limit == 2000
