"""Теги диалогов для фильтрации в сайдбаре (ADR-0008).

Теги хранятся списком строк на диалоге: их немного, и отдельная таблица дала бы
лишние соединения без выигрыша. Индекс GIN не добавляем, пока фильтрация
клиентская; при переходе на серверную фильтрацию его можно добавить отдельной
миграцией.

Revision ID: 0013_conversation_tags
Revises: 0012_protection_audit
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0013_conversation_tags"
down_revision = "0012_protection_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "tags")
