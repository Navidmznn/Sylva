"""auth: magic tokens, sessions, scope syllabi to users

Revision ID: 0002_auth
Revises: 0001_initial
Create Date: 2026-04-26

Migration order matters: we add the new column nullable, backfill, then
tighten. Same pattern for `syllabi.user_id` — orphan rows from the pre-auth
era are deleted (they were unreachable anyway, since /results is gone in
the new app), then the column is set NOT NULL.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002_auth"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── users.email_normalized ────────────────────────────────────────────
    # 1. add nullable, 2. backfill, 3. enforce NOT NULL + unique index.
    op.add_column(
        "users",
        sa.Column("email_normalized", sa.String(length=320), nullable=True),
    )
    op.execute(
        "UPDATE users SET email_normalized = LOWER(TRIM(email)) "
        "WHERE email IS NOT NULL"
    )
    # Drop any duplicate emails that differed only in case before tightening.
    # In practice the pre-auth era had no users at all, but be defensive.
    op.execute("""
        DELETE FROM users a USING users b
        WHERE a.id < b.id
          AND a.email_normalized = b.email_normalized
          AND a.email_normalized IS NOT NULL
    """)
    # Rows with NULL email_normalized are non-recoverable (no email).
    op.execute("DELETE FROM users WHERE email_normalized IS NULL")
    op.alter_column("users", "email_normalized", nullable=False)
    op.create_index(
        "ix_users_email_normalized", "users", ["email_normalized"], unique=True
    )

    # ── magic_tokens ──────────────────────────────────────────────────────
    op.create_table(
        "magic_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at",    sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_magic_tokens_user_id",    "magic_tokens", ["user_id"])
    op.create_index("ix_magic_tokens_token_hash", "magic_tokens", ["token_hash"], unique=True)

    # ── sessions ──────────────────────────────────────────────────────────
    op.create_table(
        "sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("session_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at",   sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_sessions_user_id",      "sessions", ["user_id"])
    op.create_index("ix_sessions_session_hash", "sessions", ["session_hash"], unique=True)

    # ── tighten syllabi.user_id ───────────────────────────────────────────
    # Pre-auth syllabi have user_id IS NULL and are unreachable now that
    # /results is gone. Delete them, then enforce NOT NULL.
    op.execute("DELETE FROM syllabi WHERE user_id IS NULL")
    op.alter_column("syllabi", "user_id", nullable=False)


def downgrade() -> None:
    # Loosen syllabi.user_id again.
    op.alter_column("syllabi", "user_id", nullable=True)

    op.drop_index("ix_sessions_session_hash", table_name="sessions")
    op.drop_index("ix_sessions_user_id",      table_name="sessions")
    op.drop_table("sessions")

    op.drop_index("ix_magic_tokens_token_hash", table_name="magic_tokens")
    op.drop_index("ix_magic_tokens_user_id",    table_name="magic_tokens")
    op.drop_table("magic_tokens")

    op.drop_index("ix_users_email_normalized", table_name="users")
    op.drop_column("users", "email_normalized")
