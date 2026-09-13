"""Диагностические задачи worker (используются healthcheck и smoke).

На Этапе 1 сюда добавляются document_ingest/embedding/export; на Этапе 2 —
video-задачи. Все задачи придерживаются контрактов Job/Asset из архитектуры.
"""
from __future__ import annotations

import logging

from worker.celery_app import app

logger = logging.getLogger("worker")


@app.task(name="worker.ping", bind=True, max_retries=0)
def ping(self) -> str:
    """No-op задача для проверки целостности очереди."""
    logger.info("worker_ping", extra={"extra_fields": {"task": "ping"}})
    return "pong"
