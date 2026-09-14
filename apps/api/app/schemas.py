"""Pydantic-схемы API (v1): auth, providers, models.

Схемы отделяют транспортный слой от ORM-моделей и валидируют ввод.
Ключ провайдера принимается только на вход (create/update) и никогда
не возвращается; наружу отдаётся только маска.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

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


# ---- Budgets / Usage / Prices ----------------------------------------------
# Decimal сериализуется в JSON-строку (без потери точности).


class BudgetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    currency: str
    daily_limit: Decimal | None
    monthly_limit: Decimal | None


class BudgetUpdate(BaseModel):
    daily_limit: Decimal | None = Field(default=None, ge=0)
    monthly_limit: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)


class PriceCreate(BaseModel):
    model_profile_id: uuid.UUID
    currency: str = Field(default="USD", min_length=3, max_length=3)
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    cache_read_per_million: Decimal | None = Field(default=None, ge=0)
    cache_write_per_million: Decimal | None = Field(default=None, ge=0)
    source: str = Field(default="manual", max_length=16)
    source_url: str | None = Field(default=None, max_length=512)


class PriceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    model_profile_id: uuid.UUID
    currency: str
    input_per_million: Decimal
    output_per_million: Decimal
    cache_read_per_million: Decimal | None
    cache_write_per_million: Decimal | None
    source: str
    source_url: str | None
    effective_at: datetime


class UsageRecordOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    units_json: dict
    cost_amount: Decimal
    currency: str
    cost_state: str
    model_profile_id: uuid.UUID | None
    message_id: uuid.UUID | None
    provider_request_id: str | None
    occurred_at: datetime


class UsageSummary(BaseModel):
    currency: str
    today_cost: Decimal
    month_cost: Decimal
    today_input_tokens: int
    today_output_tokens: int
    month_input_tokens: int
    month_output_tokens: int
    daily_limit: Decimal | None
    monthly_limit: Decimal | None
    daily_remaining: Decimal | None
    monthly_remaining: Decimal | None


# ---- Assets / Jobs ----------------------------------------------------------


class AssetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    status: str
    original_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    metadata_json: dict
    created_at: datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    status: str
    progress: int
    input_json: dict
    output_json: dict
    error_code: str | None
    error_detail_safe: str | None
    attempts: int
    submitted_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None


class DeleteAssetResponse(BaseModel):
    job_id: uuid.UUID


# ---- Knowledge / RAG --------------------------------------------------------


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    embedding_model_profile_id: uuid.UUID


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    embedding_model_profile_id: uuid.UUID | None = None


class KnowledgeBaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    embedding_model_profile_id: uuid.UUID | None
    embedding_version: str
    created_at: datetime
    updated_at: datetime


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    status: str
    error_code: str | None
    asset_id: uuid.UUID
    created_at: datetime


class KnowledgeBaseDetail(KnowledgeBaseOut):
    documents: list[DocumentOut] = Field(default_factory=list)


class DocumentCreateResponse(BaseModel):
    document_id: uuid.UUID
    job_id: uuid.UUID


class QueryRequest(BaseModel):
    text: str = Field(min_length=1, max_length=10_000)
    top_k: int = Field(default=5, ge=1, le=20)
    chat_model_profile_id: uuid.UUID | None = None


class Citation(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    text: str
    page: int | None
    score: float


class QueryResult(BaseModel):
    sufficient: bool
    answer: str | None = None
    citations: list[Citation]


# ---- Tables -----------------------------------------------------------------


class TableColumn(BaseModel):
    name: str
    type: str


class TablePreview(BaseModel):
    format: str
    sheets: list[str] = []
    columns: list[TableColumn] = []
    sample_rows: list = []
    row_count: int = 0


class TableQueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)
    sheet: str | None = None


class TableQueryResult(BaseModel):
    columns: list[str]
    rows: list


class TableExportRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=10_000)
    sheet: str | None = None
    format: str = Field(default="csv", pattern="^(csv|xlsx)$")
