"""
db_models.py — SQLAlchemy ORM models.

The `Syllabus` table replaces the `results` table from the SQLite era. The
column shape is preserved on the wire (load_results() in api.py still emits
`{"filename": ..., "data": {...}}` rows) so the frontend's persistence layer
needs no changes.

`User` is a placeholder for the next prompt's auth work. It carries enough
columns to be referenceable from `Syllabus.user_id` today; full auth fields
will be added when the actual auth feature lands.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


class User(Base):
    """Placeholder user — fields will be expanded when auth lands."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(String(320), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    syllabi: Mapped[list["Syllabus"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Syllabus(Base):
    """One uploaded + parsed syllabus. `data` is the same JSON the API
    historically returned to the frontend."""

    __tablename__ = "syllabi"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Nullable until auth lands — current uploads have no owning user.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    # JSONB so we can index on parsed fields later if we want to.
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user: Mapped["User | None"] = relationship(back_populates="syllabi")
