"""Предустановки провайдеров.

Задают base URL и валюту по умолчанию для быстрого подключения. Ключ
пользователь вводит сам; пресеты не содержат секретов и не гарантируют
работоспособность без ключа.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    """Описание предустановки провайдера."""

    provider_type: str
    label: str
    base_url: str
    currency: str = "USD"


PRESETS: dict[str, ProviderPreset] = {
    "openrouter": ProviderPreset(
        provider_type="openrouter",
        label="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        currency="USD",
    ),
    "routerai": ProviderPreset(
        provider_type="routerai",
        label="RouterAI",
        base_url="https://api.routerai.io/v1",
        currency="USD",
    ),
    "selectel": ProviderPreset(
        provider_type="selectel",
        label="Selectel",
        base_url="https://api.selectel.ru/v1",
        currency="RUB",
    ),
    "openai_compatible": ProviderPreset(
        provider_type="openai_compatible",
        label="OpenAI-совместимый API",
        base_url="",
        currency="USD",
    ),
    # Optional: локальный LiteLLM proxy из compose-профиля `litellm`
    # (ADR-0004). Тот же OpenAI-совместимый адаптер и тот же billing —
    # отдельная библиотека в backend не ставится.
    "litellm_proxy": ProviderPreset(
        provider_type="litellm_proxy",
        label="LiteLLM Proxy (опционально)",
        base_url="http://litellm:4000/v1",
        currency="USD",
    ),
}


def get_preset(provider_type: str) -> ProviderPreset | None:
    """Возвращает пресет по типу; None для неизвестного."""
    return PRESETS.get(provider_type)
