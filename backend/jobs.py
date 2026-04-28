"""Job-state schema and Redis read/write helpers.

arq tracks its own job lifecycle, but we need richer user-facing state
(phase labels, percent-complete, terminal result/error). We store that as
a JSON blob at job:<id> with a TTL so finished jobs eventually fall off
Redis on their own.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from redis_client import redis_client


JOB_STATE_TTL_SECONDS: int = int(os.environ.get("JOB_STATE_TTL_SECONDS", str(60 * 60 * 24)))

# Per-IP concurrency. One in-flight upload at a time, with a recovery TTL
# in case the slot release path doesn't fire (worker killed mid-job, etc.).
# Tuned to be longer than the slowest realistic Docling+Ollama wall-clock
# but short enough that a stuck slot doesn't lock a real user out for long.
MAX_ACTIVE_JOBS_PER_IP: int = 1
ACTIVE_JOB_TTL_SECONDS: int = int(os.environ.get("ACTIVE_JOB_TTL_SECONDS", str(10 * 60)))

# Surfaced verbatim to the frontend's loading-subtitle. Treat as part of the
# public contract once the frontend reads them.
PHASE_LABELS: dict[str, str] = {
    "queued":     "Waiting in line...",
    "extracting": "Reading your PDF...",
    "scoring":    "Finding the important parts...",
    "parsing":    "Asking the AI to structure it...",
    "validating": "Double-checking the output...",
    "complete":   "Done!",
}

# Heuristic per-phase percentages — Docling itself doesn't report progress,
# so the bar advances in coarse jumps tuned to observed wall-clock.
PHASE_PROGRESS: dict[str, int] = {
    "queued":      5,
    "extracting": 15,
    "scoring":    60,
    "parsing":    70,
    "validating": 95,
    "complete":  100,
}


def _key(job_id: str) -> str:
    return f"job:{job_id}"


async def init_job(job_id: str, user_id: str | None, uploader_ip: str) -> None:
    """user_id is None for guest uploads. The /jobs/{id} handler must then
    fall back to IP-based ownership instead of user-based."""
    await write_state(
        job_id,
        status="queued",
        phase="queued",
        user_id=user_id,
        uploader_ip=uploader_ip,
    )


async def write_state(
    job_id: str,
    *,
    status: str,
    phase: str,
    result: dict | None = None,
    error: str | None = None,
    user_id: str | None = None,
    uploader_ip: str | None = None,
) -> None:
    """Replace the job's state document. user_id and uploader_ip are sticky —
    the worker passes None for both and we preserve whatever the API initially
    set, so authorization checks in /jobs/{id} still work across phase
    transitions and the slot release can target the original uploader's IP
    (not the poller's, which can differ if the user changes networks)."""
    if user_id is None or uploader_ip is None:
        prior = await read_state(job_id) or {}
        if user_id is None:
            user_id = prior.get("user_id")
        if uploader_ip is None:
            uploader_ip = prior.get("uploader_ip")

    payload: dict[str, Any] = {
        "status":      status,
        "progress":    PHASE_PROGRESS.get(phase, 0),
        "phase":       PHASE_LABELS.get(phase, phase),
        "result":      result,
        "error":       error,
        "user_id":     user_id,
        "uploader_ip": uploader_ip,
        "updated_at":  datetime.now(timezone.utc).isoformat(),
    }
    await redis_client.set(_key(job_id), json.dumps(payload), ex=JOB_STATE_TTL_SECONDS)


async def read_state(job_id: str) -> dict | None:
    raw = await redis_client.get(_key(job_id))
    if raw is None:
        return None
    return json.loads(raw)


# Per-IP concurrency slot
#
# Acquire on /upload, release when the job hits a terminal state. The release
# path needs to fire reliably from at least one of two places:
#   1. The worker's finally block — guaranteed to run for any caught failure
#      or successful completion. Primary release path.
#   2. The API's GET /jobs/{id} when status becomes terminal — backstop for
#      jobs whose worker process died before reaching its finally block.
# The slot_released marker makes both paths idempotent — only the first call
# for a given job_id actually decrements. Without it, both paths racing on
# completion would double-decrement and leak a slot on the next user.
def _slot_key(ip: str) -> str:
    return f"active_jobs:{ip}"


def _slot_release_marker(job_id: str) -> str:
    return f"job:{job_id}:slot_released"


async def acquire_job_slot(ip: str, max_active: int = MAX_ACTIVE_JOBS_PER_IP) -> None:
    """Increment the per-IP active-job counter. Raises 429 if the cap is hit.
    The TTL is set on first acquire; subsequent increments inherit it, which
    is correct because the slot's lifetime is tied to the in-flight job."""
    from fastapi import HTTPException  # local import — keeps jobs.py importable from non-FastAPI contexts

    key = _slot_key(ip)
    new_count = await redis_client.incr(key)
    if new_count == 1:
        await redis_client.expire(key, ACTIVE_JOB_TTL_SECONDS)
    if new_count > max_active:
        await redis_client.decr(key)
        raise HTTPException(
            status_code=429,
            detail="You already have a file being processed. Please wait for it to finish.",
        )


async def release_job_slot(job_id: str, ip: str) -> None:
    """Idempotent. Safe to call from both worker.finally and api.get_job —
    only the first caller for a given job_id actually decrements. The marker
    has its own TTL so it doesn't leak Redis keys for completed jobs."""
    marker = _slot_release_marker(job_id)
    was_first = await redis_client.set(marker, "1", ex=3600, nx=True)
    if not was_first:
        return
    key = _slot_key(ip)
    val = await redis_client.decr(key)
    if val <= 0:
        await redis_client.delete(key)