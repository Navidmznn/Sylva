"""initial schema — users and syllabi

Revision ID: 0001_initial
Revises:
Create Date: 2026-04-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=True, unique=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "syllabi",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("filename", sa.String(length=512), nullable=False),
        sa.Column("data", postgresql.JSONB, nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_syllabi_job_id",     "syllabi", ["job_id"])
    op.create_index("ix_syllabi_created_at", "syllabi", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_syllabi_created_at", table_name="syllabi")
    op.drop_index("ix_syllabi_job_id",     table_name="syllabi")
    op.drop_table("syllabi")
    op.drop_table("users")
