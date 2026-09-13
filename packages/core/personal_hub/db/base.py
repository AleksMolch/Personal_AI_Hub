"""Базовый класс ORM-моделей и общие колонки.

Все модели наследуют `Base`, чтобы Alembic видел единый metadata.
Время хранится в UTC (aware datetime).
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """Текущее время в UTC (aware)."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Корневой класс всех ORM-моделей."""


class TimestampMixin:
    """Миксин с created_at/updated_at в UTC."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
