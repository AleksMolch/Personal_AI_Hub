"""Эндпоинты задач: список, просмотр, retry и cancel.

При чтении выполняется ленивая reconciliation зависших задач (worker lost).
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from personal_hub.db.engine import get_session
from personal_hub.models import Job, User
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user
from app.job_service import cancel_job, reconcile_stale_jobs, retry_job
from app.schemas import JobOut

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


async def _owned_job(
    session: AsyncSession, job_id: uuid.UUID, user: User
) -> Job:
    result = await session.execute(
        select(Job).where(Job.id == job_id, Job.user_id == user.id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Задача не найдена.")
    return job


@router.get("", response_model=list[JobOut])
async def list_jobs(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[JobOut]:
    await reconcile_stale_jobs(session)
    result = await session.execute(
        select(Job)
        .where(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [JobOut.model_validate(j) for j in result.scalars().all()]


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    await reconcile_stale_jobs(session)
    return JobOut.model_validate(await _owned_job(session, job_id, user))


@router.post("/{job_id}/retry", response_model=JobOut)
async def retry(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    try:
        job = await retry_job(session, job_id, user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return JobOut.model_validate(job)


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel(
    job_id: uuid.UUID,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> JobOut:
    try:
        job = await cancel_job(session, job_id, user.id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    return JobOut.model_validate(job)
