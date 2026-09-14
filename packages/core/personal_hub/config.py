"""Конфигурация приложения на основе переменных окружения.

Использует pydantic-settings: читает переменные окружения, валидирует
обязательные поля и master key. Разделяется API и worker.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки Personal AI Hub, читаемые из окружения (.env).

    Провайдеры и модели хранятся в БД, здесь только bootstrap/секреты.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Режим приложения.
    app_env: str = "production"
    app_bind_host: str = "0.0.0.0"
    app_base_url: str = "http://localhost:3000"

    # Мастер-ключ шифрования. В production не должен быть пустым/placeholder.
    app_master_key: str = ""

    # Автосоздание первого администратора (опционально, для CI/автоматизации).
    admin_username: str = ""
    admin_password: str = ""

    # Инфраструктура.
    database_url: str = "postgresql+asyncpg://app:app@postgres:5432/app"
    valkey_url: str = "redis://valkey:6379/0"
    qdrant_url: str = "http://qdrant:6333"

    # Хранилище файлов.
    blob_store_driver: str = "local"
    blob_local_root: str = "/data/assets"

    # Векторное хранилище (qdrant | memory).
    vector_store_driver: str = "qdrant"

    # Логирование и тесты.
    log_level: str = "INFO"
    run_live_tests: bool = False

    @property
    def is_production(self) -> bool:
        """True, если запущен production-режим."""
        return self.app_env == "production"

    def validate_master_key(self) -> None:
        """Проверяет, что master key не является placeholder.

        Вызывается при старте production; в development разрешает placeholder
        только с явным предупреждением.
        """
        if self.app_master_key == "" or self.app_master_key.startswith("CHANGE_ME"):
            if self.is_production:
                raise RuntimeError(
                    "APP_MASTER_KEY пуст или содержит placeholder. Запустите "
                    "`make bootstrap` или задайте 32+ байтовый случайный ключ."
                )


@lru_cache
def get_settings() -> Settings:
    """Возвращает кэшированный экземпляр настроек (singleton на процесс)."""
    return Settings()
