"""Сервис задач: создание, постановка в очередь, retry/cancel, reconciliation.

Idempotency key защищает от дубликатов. Признак «мёртвого» worker —
просроченный heartbeat; reconcile переводит такие задачи в retryable/failed.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from personal_hub.db.base import utcnow
from personal_hub.jobs import JobStatus, assert_transition
from personal_hub.models import Job
from personal_hub.queue import enqueue_task
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("api.jobs")

HEARTBEAT_TTL_SECONDS = 300  # 5 минут
MAX_ATTEMPTS = 3

RUN_JOB_TASK = "worker.run_job"


async def create_job(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    job_type: str,
    input_json: dict | None = None,
    idempotency_key: str | None = None,
    provider_id: uuid.UUID | None = None,
    model_profile_id: uuid.UUID | None = None,
) -> Job:
    """Создаёт задачу (идемпотентно) и ставит её в очередь.

    При повторном вызове с тем же idempotency_key возвращает существующую
    задачу, не создавая дубликат.
    """
    if idempotency_key:
        result = await session.execute(
            select(Job).where(
                Job.user_id == user_id, Job.idempotency_key == idempotency_key
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

    job = Job(
        user_id=user_id,
        type=job_type,
        status=JobStatus.QUEUED.value,
        idempotency_key=idempotency_key,
        input_json=input_json or {},
        provider_id=provider_id,
        model_profile_id=model_profile_id,
        submitted_at=utcnow(),
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)

    try:
        enqueue_task(RUN_JOB_TASK, [str(job.id)])
    except Exception:
        logger.exception("job_enqueue_failed")
        job.status = JobStatus.FAILED.value
        job.error_code = "ENQUEUE_FAILED"
        job.finished_at = utcnow()
        await session.commit()
    return job


async def retry_job(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
    """Повторно ставит задачу в очередь (failed/retryable -> queued)."""
    job = await _owned_job(session, job_id, user_id)
    current = JobStatus(job.status)
    if current not in (JobStatus.FAILED, JobStatus.RETRYABLE):
        raise ValueError(f"задача в статусе {current.value} не может быть повторена")
    assert_transition(current, JobStatus.QUEUED)
    job.status = JobStatus.QUEUED.value
    job.error_code = None
    job.error_detail_safe = None
    await session.commit()
    enqueue_task(RUN_JOB_TASK, [str(job.id)])
    return job


async def cancel_job(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
    """Отменяет задачу, находящуюся в очереди (queued -> cancelled)."""
    job = await _owned_job(session, job_id, user_id)
    current = JobStatus(job.status)
    if current != JobStatus.QUEUED:
        raise ValueError(f"задача в статусе {current.value} не может быть отменена")
    assert_transition(current, JobStatus.CANCELLED)
    job.status = JobStatus.CANCELLED.value
    job.finished_at = utcnow()
    await session.commit()
    return job


async def reconcile_stale_jobs(session: AsyncSession) -> int:
    """Помечает зависшие running-задачи (просроченный heartbeat).

    attempts < MAX_ATTEMPTS -> retryable (ждёт ручного retry), иначе failed.
    Возвращает число обработанных задач.
    """
    stale_before = datetime.now(UTC) - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
    result = await session.execute(
        select(Job)
        .where(
            Job.status == JobStatus.RUNNING.value,
            Job.heartbeat_at < stale_before,
        )
        .with_for_update()
    )
    jobs = result.scalars().all()
    for job in jobs:
        if job.attempts < MAX_ATTEMPTS:
            job.status = JobStatus.RETRYABLE.value
            job.error_code = "WORKER_LOST"
            job.error_detail_safe = "Исполнитель потерян; задачу можно повторить."
        else:
            job.status = JobStatus.FAILED.value
            job.error_code = "WORKER_LOST"
            job.error_detail_safe = "Исполнитель потерян; лимит попыток исчерпан."
            job.finished_at = utcnow()
    await session.commit()
    return len(jobs)


async def _owned_job(session: AsyncSession, job_id: uuid.UUID, user_id: uuid.UUID) -> Job:
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise ValueError("задача не найдена")
    return job
