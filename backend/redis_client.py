"""Shared async Redis client. Used for job state, per-IP slots, rate limits, and arq."""
from __future__ import annotations

import os

import redis.asyncio as aioredis


REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

redis_client: aioredis.Redis = aioredis.from_url(
    REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
    health_check_interval=30,
)