"""Изображения в сообщениях (мультимодальный ввод, ADR-0009 срез 5).

Храним data-URL изображений inline в messages.images (JSONB). Ограничения по
числу и размеру проверяются валидатором MessageCreate.images.

Revision ID: 0015_message_images
Revises: 0014_prompt_templates
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0015_message_images"
down_revision = "0014_prompt_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "images",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "images")
