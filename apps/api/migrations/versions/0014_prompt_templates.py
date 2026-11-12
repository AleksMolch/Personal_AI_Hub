"""Библиотека промптов: персональные шаблоны пользователя (ADR-0009).

Шаблон — текст, вставляемый в поле ввода чата. Таблица персональная: у каждого
пользователя свои шаблоны.

Revision ID: 0014_prompt_templates
Revises: 0013_conversation_tags
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_prompt_templates"
down_revision = "0013_conversation_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_prompt_templates_user_id", "prompt_templates", ["user_id"]
    )


def downgrade() -> None:
    op.drop_table("prompt_templates")
