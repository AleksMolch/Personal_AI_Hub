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


def test_litellm_not_in_project_requirements() -> None:
    """LiteLLM не ставится в backend: только внешний proxy (ADR-0004).

    Проверяем сам факт отсутствия зависимости в requirements, а не состояние
    текущего Python-окружения (иначе тест ложно падал бы у разработчика,
    который поставил litellm локально для экспериментов).
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    for name in ("apps/api/requirements.txt", "apps/api/requirements-dev.txt"):
        contents = (root / name).read_text(encoding="utf-8").lower()
        assert "litellm" not in contents


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


def test_provider_connection_repr_hides_api_key() -> None:
    """repr соединения не раскрывает ключ (иначе он утекает в логи/вывод тестов)."""
    from personal_hub.providers.base import ProviderConnection

    connection = ProviderConnection(
        provider_type="openai_compatible",
        base_url="http://example.invalid",
        api_key="sk-super-secret-key",
    )
    assert "sk-super-secret-key" not in repr(connection)
    assert connection.api_key == "sk-super-secret-key"
