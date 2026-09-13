"""Тесты пресетов провайдеров и реестра.

Проверяют наличие обязательных пресетов и маршрутизацию адаптеров.
"""
from __future__ import annotations

import pytest

from personal_hub.providers.presets import PRESETS, get_preset
from personal_hub.providers.registry import SUPPORTED_PROVIDER_TYPES, get_adapter


def test_required_presets_present() -> None:
    assert set(PRESETS) >= {"openrouter", "routerai", "selectel", "openai_compatible"}


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
