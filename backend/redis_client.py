"""Shared async Redis client. Used by api.py (job slots, state reads),
worker.py (state writes), and slowapi (rate limits, via storage_uri).
Single db=0; key prefixes separate concerns:
  arq:*          — owned by arq itself
  LIMITS:*       — owned by slowapi
  job:<id>       — our job-state JSON blob
  active_jobs:*  — our per-IP concurrency counter
"""
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