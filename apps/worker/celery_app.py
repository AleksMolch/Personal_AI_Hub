"""Создание Celery-приложения.

Broker и backend — Valkey. Сериализация JSON (без pickle). Время UTC.
Задачи объявлены с timeout и retry через общие политики задач.
"""
from __future__ import annotations

from celery import Celery
from personal_hub.config import get_settings
from personal_hub.logging_setup import configure_logging

settings = get_settings()
configure_logging(settings.log_level, service="worker")

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
