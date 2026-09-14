"""Добавление цен, курсов, бюджетов и расходов.

Revision ID: 0004_usage_and_billing
Revises: 0003_conversations_and_messages
Create Date: 2026-09-13

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_usage_and_billing"
down_revision = "0003_conversations_and_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "price_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("input_per_million", sa.Numeric(20, 8), nullable=False),
        sa.Column("output_per_million", sa.Numeric(20, 8), nullable=False),
        sa.Column("cache_read_per_million", sa.Numeric(20, 8), nullable=True),
        sa.Column("cache_write_per_million", sa.Numeric(20, 8), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("source_url", sa.String(length=512), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["model_profile_id"], ["model_profiles.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_price_snapshots_model_profile_id", "price_snapshots", ["model_profile_id"]
    )

    op.create_table(
        "fx_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_currency", sa.String(length=3), nullable=False),
        sa.Column("to_currency", sa.String(length=3), nullable=False),
        sa.Column("rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "budgets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("daily_limit", sa.Numeric(20, 8), nullable=True),
        sa.Column("monthly_limit", sa.Numeric(20, 8), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id"),
    )

    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("model_profile_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("units_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cost_amount", sa.Numeric(20, 10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("cost_state", sa.String(length=16), nullable=False),
        sa.Column("price_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fx_rate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider_request_id", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["provider_id"], ["provider_credentials.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["model_profile_id"], ["model_profiles.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["price_snapshot_id"], ["price_snapshots.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["fx_rate_id"], ["fx_rates.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_usage_records_user_id", "usage_records", ["user_id"])
    op.create_index("ix_usage_records_occurred_at", "usage_records", ["occurred_at"])

    op.create_table(
        "cost_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(20, 10), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_cost_reservations_user_id", "cost_reservations", ["user_id"])


def downgrade() -> None:
    op.drop_table("cost_reservations")
    op.drop_table("usage_records")
    op.drop_table("budgets")
    op.drop_table("fx_rates")
    op.drop_table("price_snapshots")
