"""Интеграционные тесты жизненного цикла Job.

Проверяют: выполнение задачи (document_delete), reconciliation «мёртвых»
задач, retry и cancel.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import text

from personal_hub.db.engine import get_session_factory
from personal_hub.jobs import JobStatus
from personal_hub.models import Job

from app.job_service import reconcile_stale_jobs
from worker.tasks.jobs import execute_job


async def _bootstrap(client: AsyncClient) -> tuple[dict, str]:
    resp = await client.post(
        "/api/v1/auth/bootstrap", json={"username": "admin", "password": "supersecret"}
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    me = await client.get("/api/v1/auth/me", headers=headers)
    return headers, me.json()["id"]


async def _upload(client: AsyncClient, headers: dict) -> str:
    resp = await client.post(
        "/api/v1/assets/uploads",
        headers=headers,
        files={"file": ("doc.txt", b"data", "text/plain")},
    )
    return resp.json()["id"]


async def test_delete_job_executes(client: AsyncClient) -> None:
    headers, _ = await _bootstrap(client)
    asset_id = await _upload(client, headers)
    delete = await client.delete(f"/api/v1/assets/{asset_id}", headers=headers)
    job_id = delete.json()["job_id"]

    # Выполняем задачу напрямую (в интеграционном тесте нет отдельного worker).
    await execute_job(uuid.UUID(job_id))

    get_asset = await client.get(f"/api/v1/assets/{asset_id}", headers=headers)
    assert get_asset.status_code == 404

    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
    assert job["status"] == "completed"
    assert job["output_json"]["deleted"] is True
    assert job["attempts"] == 1


async def test_execute_job_idempotent(client: AsyncClient) -> None:
    headers, _ = await _bootstrap(client)
    asset_id = await _upload(client, headers)
    delete = await client.delete(f"/api/v1/assets/{asset_id}", headers=headers)
    job_id = delete.json()["job_id"]

    await execute_job(uuid.UUID(job_id))
    # Повторный запуск завершённой задачи ничего не делает.
    await execute_job(uuid.UUID(job_id))

    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
    assert job["status"] == "completed"
    assert job["attempts"] == 1


async def test_reconcile_stale_jobs(client: AsyncClient) -> None:
    headers, user_id = await _bootstrap(client)

    factory = get_session_factory()
    async with factory() as session:
        job = Job(
            user_id=uuid.UUID(user_id),
            type="document_delete",
            status=JobStatus.RUNNING.value,
            heartbeat_at=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    # GET /jobs выполняет ленивую reconciliation.
    jobs = (await client.get("/api/v1/jobs", headers=headers)).json()
    stale = next(j for j in jobs if j["id"] == str(job_id))
    assert stale["status"] == "retryable"
    assert stale["error_code"] == "WORKER_LOST"


async def test_retry_and_cancel(client: AsyncClient) -> None:
    headers, user_id = await _bootstrap(client)

    factory = get_session_factory()
    async with factory() as session:
        job = Job(
            user_id=uuid.UUID(user_id),
            type="document_delete",
            status=JobStatus.FAILED.value,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    # retry failed -> queued
    retried = await client.post(f"/api/v1/jobs/{job_id}/retry", headers=headers)
    assert retried.status_code == 200
    assert retried.json()["status"] == "queued"

    # cancel queued -> cancelled
    cancelled = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


async def test_cancel_running_sets_flag(client: AsyncClient) -> None:
    headers, user_id = await _bootstrap(client)

    factory = get_session_factory()
    async with factory() as session:
        job = Job(
            user_id=uuid.UUID(user_id),
            type="document_ingest",
            status=JobStatus.RUNNING.value,
            heartbeat_at=datetime.now(timezone.utc),
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    # cooperative cancel: статус остаётся running, флаг выставляется.
    resp = await client.post(f"/api/v1/jobs/{job_id}/cancel", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "running"
    assert body["cancel_requested"] is True


def test_engine_usable_across_event_loops() -> None:
    """Регрессия: движок не должен переиспользовать соединения между event loop.

    Worker запускает каждую Celery-задачу через asyncio.run (новый loop на
    задачу). Пул asyncpg, переиспользуя соединение между loop, падал с
    «attached to a different loop». NullPool устраняет переиспользование.
    """
    factory = get_session_factory()

    async def _touch() -> None:
        async with factory() as session:
            await session.execute(text("SELECT 1"))

    # Два последовательных asyncio.run(), как это делает worker-обёртка run_job.
    asyncio.run(_touch())
    asyncio.run(_touch())


async def test_execute_cancelled_queued_job(client: AsyncClient) -> None:
    headers, user_id = await _bootstrap(client)

    factory = get_session_factory()
    async with factory() as session:
        job = Job(
            user_id=uuid.UUID(user_id),
            type="document_delete",
            status=JobStatus.QUEUED.value,
            cancel_requested=True,
        )
        session.add(job)
        await session.commit()
        job_id = job.id

    await execute_job(job_id)

    job = (await client.get(f"/api/v1/jobs/{job_id}", headers=headers)).json()
    assert job["status"] == "cancelled"
