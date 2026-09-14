"""Базовые типы провайдеров: Capability, протокол адаптера, DTO.

Capabilities — данные (enum), по которым UI строит интерфейс, а не условные
ветки по названию модели. Видео-capabilities зарезервированы для Этапа 2.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol


class Capability(StrEnum):
    """Возможности модели, хранимые как данные."""

    CHAT = "chat"
    STREAMING = "streaming"
    TOOLS = "tools"
    VISION = "vision"
    EMBEDDINGS = "embeddings"
    STRUCTURED_OUTPUT = "structured_output"
    # Зарезервированы для Этапа 2.
    VIDEO_TEXT = "video_text"
    VIDEO_IMAGE = "video_image"
    VIDEO_EDIT = "video_edit"


@dataclass(frozen=True)
class ProviderConnection:
    """Соединение к провайдеру: base URL и расшифрованный ключ."""

    provider_type: str
    base_url: str
    api_key: str


@dataclass
class HealthResult:
    """Результат проверки соединения."""

    ok: bool
    message: str = ""
    latency_ms: int = 0
    model_count: int = 0


@dataclass
class RemoteModel:
    """Модель, полученная от провайдера (для синхронизации каталога)."""

    external_id: str
    display_name: str = ""
    capabilities: list[str] = field(default_factory=list)
    context_limit: int | None = None
    output_limit: int | None = None


@dataclass
class ChatMessage:
    """Сообщение для отправки провайдеру."""

    role: str
    content: str


@dataclass
class ChatRequest:
    """Запрос на генерацию чата."""

    model: str
    messages: list[ChatMessage]
    system: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass
class ChatChunk:
    """Часть потокового ответа провайдера."""

    content_delta: str = ""
    usage: dict | None = None
    finish_reason: str | None = None


@dataclass
class EmbeddingResult:
    """Результат эмбеддинга батча текстов."""

    vectors: list[list[float]]
    model: str = ""


class ProviderAdapter(Protocol):
    """Контракт адаптера провайдера.

    На Этапе 1 реализуются health/list_models; chat/embeddings — следующий
    срез. AsyncGenerationProvider добавляется на Этапе 2 без изменения реестра.
    """

    async def health(self, connection: ProviderConnection) -> HealthResult: ...
    async def list_models(self, connection: ProviderConnection) -> list[RemoteModel]: ...


class ChatProvider(ProviderAdapter, Protocol):
    """Адаптер с поддержкой потокового чата.

    `stream_chat` описан как обычный `def` с возвратом `AsyncIterator`,
    поскольку реализация — async-генератор (вызов возвращает итератор,
    а не корутину).
    """

    def stream_chat(
        self, connection: ProviderConnection, request: ChatRequest
    ) -> AsyncIterator[ChatChunk]: ...


class EmbeddingProvider(ProviderAdapter, Protocol):
    """Адаптер с поддержкой эмбеддингов."""

    async def embed(
        self, connection: ProviderConnection, texts: list[str], model: str
    ) -> EmbeddingResult: ...
