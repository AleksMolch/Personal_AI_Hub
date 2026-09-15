"""Добавление флага cooperative cancel в jobs.

Revision ID: 0007_job_cancel_requested
Revises: 0006_knowledge_and_chunks
Create Date: 2026-09-15

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_job_cancel_requested"
down_revision = "0006_knowledge_and_chunks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "jobs",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("jobs", "cancel_requested")
