"""Async-движок и фабрика сессий SQLAlchemy 2.

Движок создаётся лениво из настроек и переиспользуется. Позволяет API
и worker подключаться к одной БД и выполнять миграции Alembic.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from personal_hub.config import get_settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Возвращает (и при необходимости создаёт) общий async-движок.

    Используется NullPool: worker запускает каждую задачу в отдельном
    event loop (asyncio.run), поэтому переиспользование asyncpg-соединений
    между loop приводит к «attached to a different loop». NullPool создаёт
    соединение на время сессии и закрывает его после, устраняя проблему.
    Для локального MVP накладные расходы пула незначительны.
    """
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url,
            poolclass=NullPool,
            echo=False,
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Возвращает фабрику async-сессий."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI-зависимость: предоставляет сессию на время запроса."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


async def ping_database() -> bool:
    """Проверяет доступность БД простым запросом (для /health/ready)."""
    try:
        factory = get_session_factory()
        async with factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
