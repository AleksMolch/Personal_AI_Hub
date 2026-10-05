"""Реестр адаптеров провайдеров.

Сопоставляет provider_type адаптеру. OpenRouter, RouterAI, Selectel,
универсальный OpenAI-compatible и опциональный LiteLLM Proxy используют
OpenAI-compatible адаптер; presets задают base URL по умолчанию. Добавление
video-адаптера на Этапе 2 не меняет существующие записи.
"""
from __future__ import annotations

from personal_hub.providers.openai_compatible import OpenAICompatibleAdapter

_openai_compatible = OpenAICompatibleAdapter()

# Все текущие провайдеры — OpenAI-compatible адаптер (чат + эмбеддинги).
# На Этап 2 реестр расширится async-generation адаптерами.
PROVIDER_ADAPTERS: dict[str, OpenAICompatibleAdapter] = {
    "openai_compatible": _openai_compatible,
    "openrouter": _openai_compatible,
    "routerai": _openai_compatible,
    "selectel": _openai_compatible,
    # ADR-0004: LiteLLM подключается как внешний OpenAI-совместимый proxy,
    # поэтому отдельный адаптер и библиотека litellm не нужны.
    "litellm_proxy": _openai_compatible,
}

# Типы, которые поддерживаются реестром.
SUPPORTED_PROVIDER_TYPES = frozenset(PROVIDER_ADAPTERS)


def get_adapter(provider_type: str) -> OpenAICompatibleAdapter:
    """Возвращает адаптер по типу провайдера.

    Бросает ValueError для неизвестного типа, чтобы API вернул стабильную
    ошибку VALIDATION_ERROR вместо AttributeError.
    """
    try:
        return PROVIDER_ADAPTERS[provider_type]
    except KeyError as exc:
        raise ValueError(f"неизвестный тип провайдера: {provider_type}") from exc
