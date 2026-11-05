"""Стоимость расхода может быть неизвестной (ADR-0007, срез 6).

Модель без цены разрешено использовать, но неизвестную стоимость нельзя
выдавать за ноль: `usage_records.cost_amount` становится nullable, а состояние
остаётся `unknown`. Ноль означал бы «бесплатно» и исказил бы отчёты.

Revision ID: 0010_usage_cost_nullable
Revises: 0009_protection_sanitized
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_usage_cost_nullable"
down_revision = "0009_protection_sanitized"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "usage_records",
        "cost_amount",
        existing_type=sa.Numeric(20, 10),
        nullable=True,
    )


def downgrade() -> None:
    # Перед возвратом NOT NULL неизвестные стоимости заменяются нулём: иначе
    # миграция упадёт на существующих записях. Это потеря информации, но
    # downgrade и так возвращает прежнюю модель учёта.
    op.execute("UPDATE usage_records SET cost_amount = 0 WHERE cost_amount IS NULL")
    op.alter_column(
        "usage_records",
        "cost_amount",
        existing_type=sa.Numeric(20, 10),
        nullable=False,
    )
