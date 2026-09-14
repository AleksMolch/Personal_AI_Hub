"""Лёгкий producer задач для Celery (без побочной настройки логов).

API использует этот producer для постановки задач в очередь; worker имеет
собственный Celery-app с конфигурацией логирования. Разделение исключает
перезапись лог-конфигурации API при импорте worker.
"""
from __future__ import annotations

from celery import Celery

from personal_hub.config import get_settings

_producer: Celery | None = None


def get_producer() -> Celery:
    """Возвращает (и кэширует) Celery-producer для постановки задач."""
    global _producer
    if _producer is None:
        _producer = Celery("personal_hub_producer", broker=get_settings().valkey_url)
    return _producer


def enqueue_task(name: str, args: list) -> None:
    """Ставит задачу в очередь по имени."""
    get_producer().send_task(name, args=args)
