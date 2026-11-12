"""Периодические задачи обслуживания: reconciliation и политика хранения.

Reconciliation освобождает просроченные резервирования и помечает «мёртвые»
задачи. Retention архивирует/удаляет старые диалоги и чистит артефакты защиты
(ADR-0008). Запускаются Celery beat; логика живёт в app.billing,
app.job_service и personal_hub.retention.
"""
from __future__ import annotations

import asyncio
import logging

from personal_hub.db.engine import get_session_factory

from worker.celery_app import app

logger = logging.getLogger("worker.maintenance")


async def _reconcile() -> None:
    from app.billing import reconcile_expired_reservations
    from app.job_service import reconcile_stale_jobs

    factory = get_session_factory()
    async with factory() as session:
        expired = await reconcile_expired_reservations(session)
        stale = await reconcile_stale_jobs(session)
        await session.commit()
    if expired or stale:
        logger.info(
            "reconciliation_done",
            extra={"extra_fields": {"expired_reservations": expired, "stale_jobs": stale}},
        )


@app.task(name="worker.reconcile")
def reconcile() -> None:
    """Celery-обёртка периодической reconciliation."""
    asyncio.run(_reconcile())


async def _retention() -> None:
    """Применяет политику хранения из настроек и логирует счётчики."""
    from personal_hub.config import get_settings
    from personal_hub.retention import (
        archive_idle_conversations,
        delete_archived_conversations,
        purge_audit_log,
        purge_protection_artifacts,
    )

    settings = get_settings()
    factory = get_session_factory()
    async with factory() as session:
        archived = await archive_idle_conversations(
            session, settings.conversation_archive_after_days
        )
        deleted = await delete_archived_conversations(
            session, settings.conversation_delete_after_days
        )
        artifacts = await purge_protection_artifacts(
            session, settings.protection_artifacts_retention_days
        )
        audit = await purge_audit_log(session, settings.audit_retention_days)
        await session.commit()
    logger.info(
        "retention_done",
        extra={
            "extra_fields": {
                "archived_conversations": archived,
                "deleted_conversations": deleted,
                "protection_artifacts": artifacts,
                "audit_records": audit,
            }
        },
    )


@app.task(name="worker.retention")
def retention() -> None:
    """Celery-обёртка политики хранения (ADR-0008)."""
    asyncio.run(_retention())
