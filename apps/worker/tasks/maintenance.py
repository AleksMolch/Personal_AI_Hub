"""Периодические задачи обслуживания (reconciliation).

Освобождают просроченные резервирования и помечают «мёртвые» задачи.
Запускаются Celery beat; логика живёт в app.billing/app.job_service и
переиспользуется API.
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
