"""Доменные ORM-модели: пользователь, провайдер, модель, диалог, сообщение,
цены, валютные курсы, бюджеты и записи расходов.

Провайдер хранит только зашифрованный ключ (encrypted_secret); открытый ключ
никогда не сохраняется и не возвращается API. Capabilities модели — данные,
а не условные ветки UI. Все денежные значения — Decimal/NUMERIC.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from personal_hub.db.base import Base, TimestampMixin, utcnow


class MessageStatus(StrEnum):
    """Жизненный цикл сообщения-генерации."""

    PENDING = "pending"
    STREAMING = "streaming"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class CostState(StrEnum):
    """Состояние расчёта стоимости записи расхода."""

    ESTIMATED = "estimated"
    ACTUAL = "actual"
    RECONCILED = "reconciled"
    UNKNOWN = "unknown"


class ReservationStatus(StrEnum):
    """Жизненный цикл резервирования стоимости."""

    ACTIVE = "active"
    SETTLED = "settled"
    CANCELLED = "cancelled"


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


class Conversation(Base, TimestampMixin):
    """Диалог пользователя с настройками по умолчанию."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(256), default="Новый диалог", nullable=False)
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    system_instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Message(Base, TimestampMixin):
    """Сообщение диалога. Сообщение-ассистент является генерацией.

    `parent_id` реализует ветвление (редактирование сообщения). `model_snapshot`
    фиксирует модель/провайдера на момент генерации.
    """

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # user/assistant/system
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=MessageStatus.COMPLETED.value, nullable=False
    )
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Снапшот модели/провайдера на момент генерации (для прозрачности истории).
    model_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


class PriceSnapshot(Base, TimestampMixin):
    """Версионированная цена модели (за 1M токенов).

    Обновление цены создаёт новую запись и не меняет исторические UsageRecord.
    """

    __tablename__ = "price_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    model_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    input_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    output_per_million: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cache_read_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    cache_write_per_million: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    # Источник цены: manual | api | url.
    source: Mapped[str] = mapped_column(String(16), default="manual", nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class FxRate(Base):
    """Валютный курс с источником и временем фиксации."""

    __tablename__ = "fx_rates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    from_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    to_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="manual", nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )


class Budget(Base):
    """Дневной и месячный hard limit пользователя (одна запись на пользователя)."""

    __tablename__ = "budgets"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    daily_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    monthly_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)


class UsageRecord(Base):
    """Запись расхода (токены и стоимость) по одной генерации."""

    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("provider_credentials.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("model_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    # Токены: input/output/cache_read/cache_write/reasoning.
    units_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    cost_amount: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    cost_state: Mapped[str] = mapped_column(
        String(16), default=CostState.ESTIMATED.value, nullable=False
    )
    price_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("price_snapshots.id", ondelete="SET NULL"), nullable=True
    )
    fx_rate_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("fx_rates.id", ondelete="SET NULL"), nullable=True
    )
    provider_request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False, index=True
    )


class CostReservation(Base):
    """Резервирование оценочной суммы до вызова провайдера."""

    __tablename__ = "cost_reservations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("messages.id", ondelete="SET NULL"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 10), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=ReservationStatus.ACTIVE.value, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, nullable=False
    )
