"""Тесты конфигурации: валидация master key.

Проверяет, что placeholder секрета блокируется в production, а в development
допустим с явным знанием риска.
"""
from __future__ import annotations

import pytest

from personal_hub.config import Settings


def test_placeholder_master_key_blocked_in_production() -> None:
    settings = Settings(app_master_key="CHANGE_ME_WITH_32_BYTE_RANDOM_SECRET", app_env="production")
    with pytest.raises(RuntimeError):
        settings.validate_master_key()


def test_placeholder_master_key_allowed_in_development() -> None:
    settings = Settings(app_master_key="CHANGE_ME_WITH_32_BYTE_RANDOM_SECRET", app_env="development")
    settings.validate_master_key()  # не должен бросать исключение


def test_is_production_flag() -> None:
    assert Settings(app_master_key="x", app_env="production").is_production is True
    assert Settings(app_master_key="x", app_env="development").is_production is False
