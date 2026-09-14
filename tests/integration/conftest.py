"""Фикстуры интеграционных тестов (реальный Postgres).

Миграции применяются в команде запуска (`alembic upgrade head` перед pytest).
Перед каждым тестом таблицы очищаются для изоляции.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from personal_hub.db.engine import get_engine

from app.main import app


@pytest.fixture
async def client() -> AsyncClient:
    """ASGI-клиент к приложению без запуска реального HTTP-сервера."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture(autouse=True)
async def clean_db() -> None:
    """Очищает доменные таблицы перед каждым тестом и освобождает пул.

    dispose() закрывает asyncpg-соединения на текущем event loop, чтобы
    следующий тест (новый loop) не наткнулся на «мёртвые» соединения.
    """
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "TRUNCATE users, provider_credentials, model_profiles, "
                "conversations, messages, price_snapshots, fx_rates, budgets, "
                "usage_records, cost_reservations, assets, jobs "
                "RESTART IDENTITY CASCADE"
            )
        )
    yield
    await engine.dispose()
