"""
db_models.py — SQLAlchemy ORM models.

Tables
──────
* users        — one per email. Created lazily on first /auth/login.
* magic_tokens — single-use sign-in tokens; only the hash is stored.
* sessions     — server-side session rows; only the hash is stored.
* syllabi      — one per parsed upload, FK to users (NOT NULL after 0002).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # `email` is the user-visible form. `email_normalized` is the lookup key
    # (stripped + lowercased) — split into two columns so we can show users
    # the casing they typed while still deduping on case-insensitive equality.
    email:            Mapped[str] = mapped_column(String(320), nullable=False)
    email_normalized: Mapped[str] = mapped_column(
        String(320), nullable=False, unique=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    syllabi:    Mapped[list["Syllabus"]]   = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sessions:   Mapped[list["Session"]]    = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    magic_tokens: Mapped[list["MagicToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class MagicToken(Base):
    """One-time sign-in token. token_hash = HMAC-SHA-256(raw, SESSION_SECRET).
    Marked `used_at` on first redemption — single-use is enforced by checking
    used_at IS NULL during validation."""

    __tablename__ = "magic_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at:    Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="magic_tokens")


class Session(Base):
    """Server-side session row. session_hash = HMAC of the cookie value."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    expires_at:   Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at:   Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="sessions")


class Syllabus(Base):
    __tablename__ = "syllabi"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Now NOT NULL — every syllabus belongs to a user. Migration 0002 deletes
    # any orphan rows from the pre-auth era before tightening this column.
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename:   Mapped[str]  = mapped_column(String(512), nullable=False)
    data:       Mapped[dict] = mapped_column(JSONB, nullable=False)
    job_id:     Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime]   = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user: Mapped["User"] = relationship(back_populates="syllabi")