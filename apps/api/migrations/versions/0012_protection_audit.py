"""Журнал защищённых операций (ADR-0007, срез 7).

Хранит метаданные prepare/commit/отправки, чтобы можно было разобрать инцидент:
кто, когда и в каком диалоге готовил запрос. Содержимое сообщений и значения
vault в журнал не попадают.

Revision ID: 0012_protection_audit
Revises: 0011_local_providers
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0012_protection_audit"
down_revision = "0011_local_providers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "protection_audit_log",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=48), nullable=False),
        sa.Column(
            "details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
    )
    op.create_index(
        "ix_protection_audit_log_user_id", "protection_audit_log", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(
        "ix_protection_audit_log_user_id", table_name="protection_audit_log"
    )
    op.drop_table("protection_audit_log")
