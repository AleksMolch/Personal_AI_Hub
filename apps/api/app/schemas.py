"""Pydantic-схемы API (v1): auth, providers, models.

Схемы отделяют транспортный слой от ORM-моделей и валидируют ввод.
Ключ провайдера принимается только на вход (create/update) и никогда
не возвращается; наружу отдаётся только маска.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _validate_base_url(value: str) -> str:
    """Проверяет, что base_url имеет допустимую схему (SSRF-базовая защита)."""
    value = value.strip().rstrip("/")
    if not value.startswith(("https://", "http://")):
        raise ValueError("base_url должен начинаться с http:// или https://")
    return value


def _normalize_decimal_input(value: object) -> object:
    """Приводит десятичное значение из формы к формату JSON (точка).

    Русскоязычный пользователь естественно вводит цену как `0,022` — с запятой
    в качестве десятичного разделителя. `Decimal` и JSON ожидают точку, поэтому
    без нормализации запрос отклонялся с 422 и невнятным сообщением (реальный
    дефект, найденный при работе с интерфейсом).

    Нормализация выполняется ДО валидации и только для строк: числа из JSON уже
    корректны. Пробелы (включая неразрывные, которые используют как разделители
    тысяч) удаляются, чтобы «1 234,5» тоже принималось.

    Args:
        value: Исходное значение поля из запроса.

    Returns:
        Строка с точкой вместо запятой либо исходное значение без изменений.
    """
    if not isinstance(value, str):
        return value
    cleaned = value.strip().replace("\u00a0", "").replace(" ", "")
    return cleaned.replace(",", ".") if "," in cleaned else cleaned


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
    # Задана ли для модели хотя бы одна цена (PriceSnapshot). Без цены платный
    # вызов не выполняется, поэтому UI обязан предупредить пользователя заранее.
    has_price: bool = False


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
    # Глубина рассуждений. Допустимые значения — нормализованный минимум,
    # переносимый между OpenAI-совместимыми провайдерами (openai_compatible →
    # reasoning_effort, openrouter → reasoning.effort). Значение принимается
    # только для моделей с capability `reasoning`; иначе запрос отклоняется,
    # чтобы селектор в UI не мог оказаться декоративным.
    reasoning_depth: Literal["low", "medium", "high"] | None = None
    # Обосновать ответ результатами веб-поиска. Доступно только если на сервере
    # включён `WEB_SEARCH_ENABLED`; иначе запрос отклоняется с понятной ошибкой.
    web_search: bool = False


class WebCitationOut(BaseModel):
    """Источник под ответом модели: та же нумерация, что в маркерах `[n]`."""

    index: int
    title: str
    url: str
    snippet: str


class SystemCapabilities(BaseModel):
    """Возможности сервера, влияющие на состав элементов интерфейса.

    Отдаётся отдельным эндпоинтом, чтобы UI не показывал неработающие
    переключатели: если веб-поиск выключен на сервере, элемент не рендерится.
    """

    web_search: bool


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

    @field_validator("daily_limit", "monthly_limit", mode="before")
    @classmethod
    def _normalize_limits(cls, value: object) -> object:
        """Принимает лимит с запятой или точкой: `0,5` и `0.5` равнозначны."""
        return _normalize_decimal_input(value)


class PriceCreate(BaseModel):
    model_profile_id: uuid.UUID
    currency: str = Field(default="USD", min_length=3, max_length=3)
    input_per_million: Decimal = Field(ge=0)
    output_per_million: Decimal = Field(ge=0)
    cache_read_per_million: Decimal | None = Field(default=None, ge=0)
    cache_write_per_million: Decimal | None = Field(default=None, ge=0)
    source: str = Field(default="manual", max_length=16)
    source_url: str | None = Field(default=None, max_length=512)

    @field_validator(
        "input_per_million",
        "output_per_million",
        "cache_read_per_million",
        "cache_write_per_million",
        mode="before",
    )
    @classmethod
    def _normalize_prices(cls, value: object) -> object:
        """Принимает цену с запятой: `0,022` из формы равно `0.022`."""
        return _normalize_decimal_input(value)


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
    cancel_requested: bool
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
    # Причина, по которой синтез не выполнялся (price_missing и т.п.),
    # чтобы UI мог объяснить пустой answer.
    answer_skipped_reason: str | None = None
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


# ---- Fx rates ---------------------------------------------------------------


class FxRateCreate(BaseModel):
    from_currency: str = Field(min_length=3, max_length=3)
    to_currency: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    source: str = Field(default="manual", max_length=64)

    @field_validator("rate", mode="before")
    @classmethod
    def _normalize_rate(cls, value: object) -> object:
        """Принимает курс с запятой: `0,011` из формы равно `0.011`."""
        return _normalize_decimal_input(value)


class FxRateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_currency: str
    to_currency: str
    rate: Decimal
    source: str
    fetched_at: datetime
