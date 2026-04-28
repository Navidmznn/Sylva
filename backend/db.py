"""SQLAlchemy engines + session helpers.

Async engine for the FastAPI app and the worker (asyncpg). Sync engine
exists only for alembic, which expects a synchronous engine. DATABASE_URL
is the canonical source — we swap the driver suffix for the sync version.
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
    return url.replace("+asyncpg", "+psycopg", 1)


# Async engine — used by FastAPI and the worker.
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


# Sync engine — alembic only.
sync_engine = create_engine(_to_sync_url(DATABASE_URL), pool_pre_ping=True, future=True)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session