"""Доменные ORM-модели: пользователь, провайдер, модель.

Провайдер хранит только зашифрованный ключ (encrypted_secret); открытый ключ
никогда не сохраняется и не возвращается API. Capabilities модели — данные,
а не условные ветки UI.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from personal_hub.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    """Локальный пользователь-владелец платформы."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    # Хранится только хэш пароля (argon2), никогда открытый пароль.
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class ProviderCredential(Base, TimestampMixin):
    """Учётные данные подключения к внешнему AI-провайдеру."""

    __tablename__ = "provider_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Тип адаптера: openrouter, routerai, selectel, openai_compatible.
    provider_type: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # Зашифрованный ключ (Fernet). Никогда не возвращается API.
    encrypted_secret: Mapped[str] = mapped_column(String(2048), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)


class ModelProfile(Base, TimestampMixin):
    """Профиль модели, привязанный к провайдеру.

    capabilities — JSON-список строк (chat, streaming, embeddings, vision, ...).
    Зарезервированы video_text/video_image/video_edit для Этапа 2.
    """

    __tablename__ = "model_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="CASCADE"),
        nullable=False,
    )
    external_model_id: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    context_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Дополнительные поля провайдера (цена, модальности и т.п.) — JSONB.
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
