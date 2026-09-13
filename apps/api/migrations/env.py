"""Конфигурация Alembic для асинхронных миграций.

Читает URL БД из настроек приложения, использует общий metadata моделей.
URL не хранится в alembic.ini — он берётся из окружения, чтобы не дублировать
секреты подключения.
"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

import personal_hub.models  # noqa: F401  # регистрирует модели в metadata
from alembic import context
from personal_hub.config import get_settings
from personal_hub.db.base import Base
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """URL БД из настроек приложения."""
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Офлайн-режим: генерация SQL без подключения к БД."""
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    """Асинхронное подключение и выполнение миграций."""
    connectable = async_engine_from_config(
        {"sqlalchemy.url": _database_url()},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Онлайн-режим: применение миграций к живой БД."""
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
