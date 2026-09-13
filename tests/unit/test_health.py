"""Тесты health/version endpoints.

Проверяют liveness и version без доступа к внешней инфраструктуре.
Readiness покрывается integration-тестами с реальной БД.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.mark.asyncio
async def test_health_live() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "alive"}


@pytest.mark.asyncio
async def test_version() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/version")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"]
    assert data["env"] in {"production", "development"}


@pytest.mark.asyncio
async def test_ready_reports_dependencies() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/health/ready")
    # Без инфраструктуры статус 503 с перечислением проверок.
    assert resp.status_code in {200, 503}
    assert "checks" in resp.json()
