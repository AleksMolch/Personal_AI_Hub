"""Хранение построчных sanitized-сообщений в подготовке (ADR-0007, срез 4).

Подготовка уже хранит общий sanitized-текст, но для истории чата нужны версии
каждого сообщения отдельно: при отправке провайдеру они подставляются
построчно, а не склеенным текстом. Кроме того, commit должен подтверждать
именно тот вариант, который пользователь видел в preview, поэтому повторная
санитизация при отправке недопустима — она могла бы дать другой результат при
изменённом словаре.

Revision ID: 0009_protection_sanitized
Revises: 0008_protection_modes
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0009_protection_sanitized"
down_revision = "0008_protection_modes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "protection_preparations",
        sa.Column(
            "sanitized_messages",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("protection_preparations", "sanitized_messages")
