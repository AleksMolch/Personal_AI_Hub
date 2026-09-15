"""Структурированное логирование в формате JSON.

Каждая запись содержит обязательные поля: timestamp (UTC), level, service,
version, request_id, job_id (при наличии) и исключает секреты.
Использует contextvar для прокидывания request_id через async-контекст.
"""
from __future__ import annotations

import contextvars
import json
import logging
import sys
from datetime import UTC, datetime

from personal_hub.version import APP_VERSION

SERVICE_NAME = "api"

# Контекстные переменные для корреляционных идентификаторов.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)
job_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("job_id", default=None)

# Поля, которые гарантированно исключаются из логов (секреты и приватные данные).
_REDACT_KEYS = {"authorization", "api_key", "apikey", "secret", "token", "password", "master_key"}


def _redact(obj: object) -> object:
    """Рекурсивно удаляет секретные ключи из произвольной структуры."""
    if isinstance(obj, dict):
        return {
            k: ("[REDACTED]" if k.lower() in _REDACT_KEYS else _redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_redact(v) for v in obj]
    return obj


class JsonFormatter(logging.Formatter):
    """Форматирует запись лога как одну строку JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": SERVICE_NAME,
            "version": APP_VERSION,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        job_id = job_id_var.get()
        if job_id:
            payload["job_id"] = job_id
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if extra:
            payload["extra"] = _redact(extra)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO", service: str = "api") -> None:
    """Инициализирует корневой логгер с JSON-выводом в stdout."""
    global SERVICE_NAME
    SERVICE_NAME = service

    root = logging.getLogger()
    root.setLevel(level.upper())
    # Удаляем ранее добавленные обработчики для идемпотентности.
    for handler in root.handlers[:]:
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # Приводим шумные сторонние логгеры к разумному уровню.
    logging.getLogger("uvicorn.access").setLevel("WARNING")
    logging.getLogger("httpx").setLevel("WARNING")


def apply_json_handler(logger: logging.Logger) -> None:
    """Заменяет обработчики логгера на JSON-форматтер (для Celery-логгеров).

    Устанавливает propagate=False, чтобы избежать дублирования через root.
    """
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.propagate = False
