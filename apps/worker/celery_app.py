"""Создание Celery-приложения.

Broker и backend — Valkey. Сериализация JSON (без pickle). Время UTC.
Задачи объявлены с timeout и retry через общие политики задач.
"""
from __future__ import annotations

import sys

from celery import Celery, signals
from personal_hub.config import get_settings
from personal_hub.logging_setup import apply_json_handler, configure_logging

settings = get_settings()
# worker и beat используют один celery_app.py, но команда отличается («worker»/«beat»).
_service = "beat" if "beat" in sys.argv else "worker"
configure_logging(settings.log_level, service=_service)

app = Celery(
    "personal_hub",
    broker=settings.valkey_url,
    backend=settings.valkey_url,
    include=[
        "worker.tasks.system",
        "worker.tasks.jobs",
        "worker.tasks.ingest",
        "worker.tasks.maintenance",
    ],
)


@signals.after_setup_logger.connect
def _json_celery_logger(logger, **kwargs) -> None:
    """Переводит логгер `celery` на JSON-формат."""
    apply_json_handler(logger)


@signals.after_setup_task_logger.connect
def _json_task_logger(logger, **kwargs) -> None:
    """Переводит task-логгер на JSON-формат."""
    apply_json_handler(logger)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "reconcile-every-minute": {
            "task": "worker.reconcile",
            "schedule": 60.0,
        },
    },
)
