"""
db.py — SQLAlchemy engine + session helpers.

Two engines are exposed:
  * `async_engine` / `AsyncSessionLocal` — the production path used by the
    FastAPI app and the arq worker. Driver: asyncpg.
  * `sync_engine` — used only by alembic, which historically expects a
    synchronous engine for migrations. Driver: psycopg.

The DATABASE_URL env var is the canonical source for both. Examples:

    DATABASE_URL=postgresql+asyncpg://syllabus:syllabus@localhost:5432/syllabus

For alembic we substitute the driver portion at config time
(`postgresql+asyncpg://` → `postgresql+psycopg://`).
"""
from __future__ import annotations

import os
from typing import AsyncIterator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


DATABASE_URL: str = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://syllabus:syllabus@localhost:5432/syllabus",
)


def _to_sync_url(url: str) -> str:
    """Map an asyncpg URL to the psycopg sync driver for alembic."""
    return url.replace("+asyncpg", "+psycopg", 1)


# ── Async engine (FastAPI + worker) ──────────────────────────────────────────
async_engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=async_engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


# ── Sync engine (alembic only — do not use elsewhere) ────────────────────────
sync_engine = create_engine(_to_sync_url(DATABASE_URL), pool_pre_ping=True, future=True)


# ── FastAPI dependency ───────────────────────────────────────────────────────
async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session
