"""Unit-тесты режимов обработки (ADR-0007/0008).

Проверяют, что «Прямой доступ» разрешает внешние вызовы, не требует подготовки
и не подменяет режим по умолчанию.
"""
from __future__ import annotations

from personal_hub.protection.modes import (
    DEFAULT_MODE,
    ProtectionMode,
    allows_external_calls,
    is_protected,
)


def test_direct_mode_allows_external_calls():
    """Прямой доступ — это облако без проверок, внешние вызовы разрешены."""
    assert allows_external_calls(ProtectionMode.DIRECT_CLOUD) is True


def test_direct_mode_does_not_require_preparation():
    """В прямом доступе prepare не нужен: текст уходит как есть."""
    assert is_protected(ProtectionMode.DIRECT_CLOUD) is False


def test_default_mode_is_cloud_controlled():
    """Владелец выбрал «облако с предупреждениями» режимом по умолчанию."""
    assert DEFAULT_MODE == ProtectionMode.CLOUD_CONTROLLED


def test_all_modes_are_exposed():
    """Список режимов содержит четыре значения, включая прямой доступ."""
    assert {mode.value for mode in ProtectionMode} == {
        "cloud_controlled",
        "direct_cloud",
        "protected_hybrid",
        "local_only",
    }
