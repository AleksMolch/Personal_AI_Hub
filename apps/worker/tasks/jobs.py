"""Задача worker: выполнение Job с state machine и heartbeat.

Celery-задача запускает async-функцию execute_job, которая переводит задачу
queued/retryable -> running -> completed/failed. Обработчики регистрируются
по типу Job. Idempotency: повторный запуск завершённой задачи не выполняется.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from personal_hub.db.base import utcnow
from personal_hub.db.engine import get_session_factory
from personal_hub.jobs import JobStatus, JobType, assert_transition
from personal_hub.models import Asset, Job

from worker.celery_app import app

logger = logging.getLogger("worker.jobs")

# Реестр обработчиков по типу задачи.
_HANDLERS: dict[str, Callable[[uuid.UUID], Awaitable[dict]]] = {}


def register_handler(job_type: JobType):
    """Декоратор регистрации обработчика задачи."""

    def decorator(fn: Callable[[uuid.UUID], Awaitable[dict]]):
        _HANDLERS[job_type.value] = fn
        return fn

    return decorator


async def _handle_document_delete(job_id: uuid.UUID) -> dict:
    """Удаляет blob ассета и сам ассет (идемпотентно)."""
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {"deleted": False}
        asset_id = (job.input_json or {}).get("asset_id")
        deleted = False
        if asset_id:
            asset = await session.get(Asset, uuid.UUID(asset_id))
            if asset is not None:
                from personal_hub.blobstore import get_blob_store

                await get_blob_store().delete(asset.blob_key)
                await session.delete(asset)
                deleted = True
                await session.commit()
        return {"deleted_asset_id": asset_id, "deleted": deleted}


register_handler(JobType.DOCUMENT_DELETE)(_handle_document_delete)


async def _dispatch(job_id: uuid.UUID) -> dict:
    """Вызывает обработчик по типу задачи."""
    factory = get_session_factory()
    async with factory() as session:
        job = await session.get(Job, job_id)
        if job is None:
            return {}
        handler = _HANDLERS.get(job.type)
        if handler is None:
            raise RuntimeError(f"нет обработчика для типа задачи: {job.type}")
    return await handler(job_id)


async def execute_job(job_id: uuid.UUID) -> None:
    """Выполняет задачу с переходами state machine.

    Повторный запуск не-queued/retryable задачи пропускается (идемпотентность).
    """
    factory = get_session_factory()

    async with factory() as session:
        from sqlalchemy import select

        result = await session.execute(
            select(Job).where(Job.id == job_id).with_for_update()
        )
        job = result.scalar_one_or_none()
        if job is None:
            return
        current = JobStatus(job.status)
        if current not in (JobStatus.QUEUED, JobStatus.RETRYABLE):
            # Уже выполняется или завершена — не трогаем.
            return
        assert_transition(current, JobStatus.RUNNING)
        job.status = JobStatus.RUNNING.value
        job.started_at = utcnow()
        job.heartbeat_at = utcnow()
        job.attempts += 1
        await session.commit()

    try:
        output = await _dispatch(job_id)
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            assert_transition(JobStatus(job.status), JobStatus.COMPLETED)
            job.status = JobStatus.COMPLETED.value
            job.progress = 100
            job.finished_at = utcnow()
            job.heartbeat_at = utcnow()
            job.output_json = output or {}
            await session.commit()
    except Exception as exc:
        logger.exception("job_failed")
        async with factory() as session:
            job = await session.get(Job, job_id)
            if job is None:
                return
            assert_transition(JobStatus(job.status), JobStatus.FAILED)
            job.status = JobStatus.FAILED.value
            job.finished_at = utcnow()
            job.heartbeat_at = utcnow()
            job.error_code = "JOB_ERROR"
            job.error_detail_safe = str(exc)[:2000]
            await session.commit()


@app.task(name="worker.run_job", bind=True, max_retries=0)
def run_job(self, job_id: str) -> None:
    """Celery-обёртка: запускает async-выполнение в отдельном event loop."""
    asyncio.run(execute_job(uuid.UUID(job_id)))
