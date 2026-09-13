"""Pydantic-схемы API (v1): auth, providers, models.

Схемы отделяют транспортный слой от ORM-моделей и валидируют ввод.
Ключ провайдера принимается только на вход (create/update) и никогда
не возвращается; наружу отдаётся только маска.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_base_url(value: str) -> str:
    """Проверяет, что base_url имеет допустимую схему (SSRF-базовая защита)."""
    value = value.strip().rstrip("/")
    if not value.startswith(("https://", "http://")):
        raise ValueError("base_url должен начинаться с http:// или https://")
    return value


# ---- Auth -----------------------------------------------------------------


class BootstrapRequest(BaseModel):
    username: str = Field(min_length=3, max_length=128)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    is_admin: bool


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ---- Providers -------------------------------------------------------------


class ProviderCreate(BaseModel):
    provider_type: str
    display_name: str = Field(min_length=1, max_length=128)
    base_url: str
    api_key: str = Field(min_length=1, max_length=4096)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    priority: int = Field(default=100, ge=0)
    enabled: bool = True

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str) -> str:
        return _validate_base_url(value)


class ProviderUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    base_url: str | None = None
    api_key: str | None = Field(default=None, min_length=1, max_length=4096)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    priority: int | None = Field(default=None, ge=0)
    enabled: bool | None = None

    @field_validator("base_url")
    @classmethod
    def _check_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_base_url(value)


class ProviderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_type: str
    display_name: str
    base_url: str
    enabled: bool
    priority: int
    currency: str
    key_mask: str
    created_at: datetime
    updated_at: datetime


class ProviderTestResult(BaseModel):
    ok: bool
    message: str
    latency_ms: int = 0
    model_count: int = 0


class ProviderPresetOut(BaseModel):
    provider_type: str
    label: str
    base_url: str
    currency: str


# ---- Models ----------------------------------------------------------------


class ModelProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider_id: uuid.UUID
    external_model_id: str
    display_name: str
    capabilities: list[str]
    context_limit: int | None
    output_limit: int | None
    enabled: bool


# ---- Conversations ----------------------------------------------------------


class ConversationCreate(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    model_profile_id: uuid.UUID | None = None
    system_instruction: str | None = None


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=256)
    archived: bool | None = None
    model_profile_id: uuid.UUID | None = None
    system_instruction: str | None = None


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    parent_id: uuid.UUID | None
    status: str
    model_snapshot: dict
    error_code: str | None
    created_at: datetime


class ConversationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    model_profile_id: uuid.UUID | None
    system_instruction: str | None
    archived: bool
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut] = Field(default_factory=list)


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=200_000)
    model_profile_id: uuid.UUID | None = None


class MessageCreateResponse(BaseModel):
    generation_id: uuid.UUID
    message: MessageOut
