"""Health- и version-endpoints.

Отделяет liveness (процесс жив) от readiness (зависимости доступны).
UI и оркестратор используют их для проверки готовности стека.
"""
from __future__ import annotations

import httpx
import redis.asyncio as redis
from fastapi import APIRouter, Response, status
from personal_hub.config import get_settings
from personal_hub.db.engine import ping_database
from personal_hub.version import APP_VERSION

router = APIRouter(prefix="/api/v1", tags=["system"])


@router.get("/health/live", summary="Liveness: процесс отвечает")
async def health_live() -> dict[str, str]:
    """Возвращает 200, если процесс работает. Не проверяет зависимости."""
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness: зависимости доступны")
async def health_ready(response: Response) -> dict[str, object]:
    """Проверяет PostgreSQL, Valkey и Qdrant. Возвращает 503 при сбое любой."""
    settings = get_settings()
    checks: dict[str, str] = {}

    checks["postgres"] = "ok" if await ping_database() else "unavailable"

    checks["valkey"] = await _ping_valkey(settings.valkey_url)
    checks["qdrant"] = await _ping_qdrant(settings.qdrant_url)

    all_ok = all(value == "ok" for value in checks.values())
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ready" if all_ok else "not_ready", "checks": checks}


@router.get("/version", summary="Версия приложения")
async def version() -> dict[str, str]:
    """Возвращает версию API и режим окружения."""
    settings = get_settings()
    return {"version": APP_VERSION, "env": settings.app_env}


async def _ping_valkey(url: str) -> str:
    """Проверяет Valkey командой PING."""
    try:
        client = redis.from_url(url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        return "ok"
    except Exception:
        return "unavailable"


async def _ping_qdrant(url: str) -> str:
    """Проверяет Qdrant endpoint /readyz."""
    try:
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{url.rstrip('/')}/readyz")
            return "ok" if resp.status_code == 200 else "unavailable"
    except Exception:
        return "unavailable"
