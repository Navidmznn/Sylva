"""
redis_client.py — shared async Redis client.

Three users on this connection:
  * api.py    — per-IP active-job slots, job-state reads
  * worker.py — job-state writes (enqueue + progress + result/error)
  * slowapi   — rate-limit storage (configured via storage_uri, not this module)

We use db=0 for everything and rely on key prefixes to separate concerns:
  * `arq:*`         — owned by arq itself (queue, deferred jobs)
  * `LIMITS:*`      — owned by slowapi/limits
  * `job:<id>`      — our explicit job-state JSON blob
  * `active_jobs:<ip>` — our per-IP concurrency counter
"""
from __future__ import annotations

import os

import redis.asyncio as aioredis


REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

# Single connection pool reused across the FastAPI app + worker.
redis_client: aioredis.Redis = aioredis.from_url(
    REDIS_URL,
    encoding="utf-8",
    decode_responses=True,
    health_check_interval=30,
)
