"""Защищённые режимы: режим диалога, снимок защиты и vault (ADR-0007).

Добавляет контракты режимов и хранение карты псевдонимов:

- `conversations.protection_mode` и `protection_revision` — выбранный
  пользователем режим и ревизия контекста; commit подготовки с другой ревизией
  отклоняется до сетевого вызова;
- `messages.protection` — снимок защиты сообщения, включая sanitized-текст для
  следующего turn (приватный `content` повторно не отправляется);
- `protection_preparations` — подготовка запроса: digest, ревизия, статус;
- `protection_entities` — vault: псевдоним и зашифрованное мастер-ключом
  значение. Открытых ПДн в базе нет.

Миграция совместима со старыми диалогами: серверные значения по умолчанию
дают `cloud_controlled`, то есть текущее поведение.

Revision ID: 0008_protection_modes
Revises: 0007_job_cancel_requested
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0008_protection_modes"
down_revision = "0007_job_cancel_requested"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "protection_mode",
            sa.String(length=32),
            nullable=False,
            server_default="cloud_controlled",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "protection_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "messages",
        sa.Column(
            "protection",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "protection_preparations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("private_digest", sa.String(length=64), nullable=False),
        sa.Column("sanitized_digest", sa.String(length=64), nullable=False),
        sa.Column("sanitized_text", sa.Text(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_protection_preparations_user_id",
        "protection_preparations",
        ["user_id"],
    )
    op.create_index(
        "ix_protection_preparations_conversation_id",
        "protection_preparations",
        ["conversation_id"],
    )

    op.create_table(
        "protection_entities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preparation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("placeholder", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["preparation_id"], ["protection_preparations.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "preparation_id", "placeholder", name="uq_protection_entity_placeholder"
        ),
    )
    op.create_index(
        "ix_protection_entities_preparation_id",
        "protection_entities",
        ["preparation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_protection_entities_preparation_id", table_name="protection_entities"
    )
    op.drop_table("protection_entities")
    op.drop_index(
        "ix_protection_preparations_conversation_id",
        table_name="protection_preparations",
    )
    op.drop_index(
        "ix_protection_preparations_user_id", table_name="protection_preparations"
    )
    op.drop_table("protection_preparations")
    op.drop_column("messages", "protection")
    op.drop_column("conversations", "protection_revision")
    op.drop_column("conversations", "protection_mode")
