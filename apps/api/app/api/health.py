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
from personal_hub.protection.modes import ProtectionMode
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


@router.get("/capabilities", summary="Возможности сервера для UI")
async def capabilities() -> dict[str, object]:
    """Сообщает, какие опциональные возможности включены на сервере.

    Нужен интерфейсу, чтобы не показывать неработающие элементы: например,
    переключатель веб-доступа рендерится только при `web_search=true`, а
    переключатель режима защиты — только когда защита включена флагом
    `PROTECTION_MODES_ENABLED` (ADR-0007).
    """
    settings = get_settings()
    return {
        "web_search": settings.web_search_enabled,
        "protection": {
            "enabled": settings.protection_modes_enabled,
            # Список режимов отдаём и при выключенном флаге: он статичен и
            # нужен тестам/клиентам, но UI показывает переключатель только при
            # enabled=true.
            "modes": [mode.value for mode in ProtectionMode],
            # Режим для новых диалогов (ADR-0008): UI берёт его как начальное
            # значение селектора, а сервер применяет при создании диалога.
            "default_mode": settings.default_protection_mode,
            # Предупреждения облака: клиент спрашивает, показывать ли их.
            "cloud_scan": settings.cloud_scan_enabled,
        },
    }


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
