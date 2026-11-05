"""Признак локального провайдера для режима local_only (ADR-0007, срез 6b).

Локальным считается провайдер, которого пользователь явно так пометил
(Ollama, LM Studio или собственный inference на этом хосте). Автоматически
определять локальность по base_url нельзя: за `127.0.0.1` может стоять
туннель в облако, и тогда «локальный» режим отправил бы данные наружу.

Revision ID: 0011_local_providers
Revises: 0010_usage_cost_nullable
Create Date: 2026-10-19

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_local_providers"
down_revision = "0010_usage_cost_nullable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "provider_credentials",
        sa.Column(
            "is_local",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_credentials", "is_local")
