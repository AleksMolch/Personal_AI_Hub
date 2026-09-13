"""Модель пользователя — корень модели данных.

MVP рассчитан на одного владельца, но `user_id` присутствует с первого дня,
чтобы multi-user можно было добавить миграциями без переделки ядра.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from personal_hub.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Локальный пользователь-владелец платформы."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Хранится только хэш пароля (argon2/bcrypt), никогда открытый пароль.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
