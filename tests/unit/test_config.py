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


def test_ocr_timeout_must_be_positive() -> None:
    """Нулевой таймаут OCR — конфигурационная ошибка, а не мгновенная отмена."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Settings(app_master_key="x", ocr_page_timeout_seconds=0)


def test_ocr_max_pages_allows_zero_to_disable() -> None:
    """OCR_MAX_PAGES=0 допустим и означает «OCR отключён»."""
    settings = Settings(app_master_key="x", ocr_max_pages=0)
    assert settings.ocr_max_pages == 0
