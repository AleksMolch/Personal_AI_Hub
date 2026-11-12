"""Конфигурация приложения на основе переменных окружения.

Использует pydantic-settings: читает переменные окружения, валидирует
обязательные поля и master key. Разделяется API и worker.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
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

    # OCR сканов: backend (tesseract|rapidocr|auto), языки, лимиты ресурсов.
    # В режиме auto предпочтителен RapidOCR c fallback на Tesseract.
    ocr_backend: str = "tesseract"
    ocr_languages: str = "rus,eng"
    # Максимум страниц PDF, распознаваемых за одну задачу индексации.
    # 0 — OCR полностью отключён (сканы и изображения не распознаются).
    ocr_max_pages: int = Field(default=40, ge=0)
    # Максимальная сторона изображения до OCR (предварительное уменьшение).
    ocr_max_image_side: int = Field(default=3500, gt=0)
    # Максимум пикселей изображения; проверяется до декодирования (bomb-guard).
    ocr_max_image_pixels: int = Field(default=50_000_000, gt=0)
    # Таймаут распознавания одной страницы, секунд; 0 недопустим.
    ocr_page_timeout_seconds: float = Field(default=30.0, gt=0)

    # Веб-поиск для обоснования ответов модели (опционально).
    # По умолчанию выключен: требует отдельного сервиса SearXNG (профиль
    # `search` в compose.yaml). Пока выключен, переключатель веб-доступа в UI
    # не показывается — неработающих элементов интерфейса быть не должно.
    web_search_enabled: bool = False
    web_search_provider: str = "searxng"
    searxng_url: str = "http://searxng:8080"
    searxng_timeout_seconds: float = Field(default=10.0, gt=0)
    # Сколько результатов поиска попадает в контекст модели.
    web_search_max_results: int = Field(default=5, ge=1, le=20)
    # Ограничение длины сниппета одного источника: поисковики отдают целые
    # страницы, и без лимита вход запроса становится непредсказуемым по цене.
    web_search_max_context_chars: int = Field(default=2000, ge=200, le=20000)
    # Список движков SearXNG через запятую; пусто — выбор самого SearXNG.
    web_search_engines: str = ""

    # Headless-рендер страниц для импорта цен (ADR-0006).
    # Нужен там, где таблица тарифов дорисовывается JavaScript: обычный
    # HTTP-запрос видит только пустую оболочку. По умолчанию выключен, потому
    # что требует отдельного контейнера с Chromium (профиль `pricebot`).
    pricebot_enabled: bool = False
    pricebot_url: str = "http://pricebot:8100"
    pricebot_timeout_seconds: float = Field(default=30.0, gt=0)

    # Защищённые режимы (ADR-0007). Флаг включает гибрид, локальный режим и
    # селектор в UI. Облачный режим с предупреждениями доступен всегда: это
    # режим по умолчанию, и скрывать его предупреждения было бы нечестно.
    protection_modes_enabled: bool = False
    # Режим обработки для новых диалогов. Владелец выбрал «облако с
    # предупреждениями» по умолчанию (ADR-0008), а не гибрид.
    default_protection_mode: Literal[
        "cloud_controlled", "direct_cloud", "protected_hybrid", "local_only"
    ] = "cloud_controlled"
    # Локальное сканирование текста перед отправкой в облачном режиме.
    # Отключается, если пользователь сознательно не хочет предупреждений;
    # режим «Прямой доступ» не сканирует всегда.
    cloud_scan_enabled: bool = True

    # Окно контекста: сколько истории уходит провайдеру. Без ограничения
    # длинный диалог растёт в цене и может превысить лимит модели.
    chat_history_max_messages: int = Field(default=80, ge=2, le=500)
    chat_history_max_tokens: int = Field(default=24000, ge=1000, le=200000)
    # Резерв под системную инструкцию и ответ модели при расчёте по context_limit.
    chat_context_reserve_tokens: int = Field(default=1024, ge=0, le=32000)

    # Политика хранения (ADR-0008). Нули выключают соответствующее действие.
    # По умолчанию удаление диалогов выключено: архив не разрушает данные.
    conversation_archive_after_days: int = Field(default=90, ge=0)
    conversation_delete_after_days: int = Field(default=0, ge=0)
    protection_artifacts_retention_days: int = Field(default=30, ge=0)
    audit_retention_days: int = Field(default=90, ge=0)

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
