"""Тесты пресетов провайдеров и реестра.

Проверяют наличие обязательных пресетов и маршрутизацию адаптеров.
"""
from __future__ import annotations

import pytest

from personal_hub.providers.presets import PRESETS, get_preset
from personal_hub.providers.registry import SUPPORTED_PROVIDER_TYPES, get_adapter


def test_required_presets_present() -> None:
    assert set(PRESETS) >= {"openrouter", "routerai", "selectel", "openai_compatible"}


def test_litellm_proxy_preset_is_optional_openai_compatible() -> None:
    """Пресет LiteLLM (ADR-0004) — тот же адаптер, только локальный proxy."""
    preset = get_preset("litellm_proxy")
    assert preset is not None
    assert preset.base_url == "http://litellm:4000/v1"
    assert preset.provider_type == "litellm_proxy"
    assert get_adapter("litellm_proxy") is get_adapter("openai_compatible")


def test_litellm_is_not_part_of_default_extras() -> None:
    """Никаких тяжёлых зависимостей: LiteLLM не должен быть в core-пакете."""
    import importlib.util

    # Библиотека litellm в backend не ставится (только внешний proxy-сервис).
    assert importlib.util.find_spec("litellm") is None


def test_presets_have_no_secrets() -> None:
    for preset in PRESETS.values():
        assert "key" not in vars(preset)
        assert "secret" not in vars(preset)


def test_get_preset_unknown_returns_none() -> None:
    assert get_preset("unknown") is None


def test_adapter_resolves_for_supported_types() -> None:
    for provider_type in SUPPORTED_PROVIDER_TYPES:
        assert get_adapter(provider_type) is not None


def test_adapter_unknown_type_raises() -> None:
    with pytest.raises(ValueError):
        get_adapter("not_a_real_type")
