"""Job state helpers — reads/writes Redis blobs that track pipeline progress."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from redis_client import redis_client


JOB_STATE_TTL_SECONDS: int = int(os.environ.get("JOB_STATE_TTL_SECONDS", str(60 * 60 * 24)))

MAX_ACTIVE_JOBS_PER_IP: int = 1
ACTIVE_JOB_TTL_SECONDS: int = int(os.environ.get("ACTIVE_JOB_TTL_SECONDS", str(10 * 60)))

PHASE_LABELS: dict[str, str] = {
    "queued":     "Waiting in line...",
    "extracting": "Reading your PDF...",
    "scoring":    "Finding the important parts...",
    "parsing":    "Asking the AI to structure it...",
    "validating": "Double-checking the output...",
    "complete":   "Done!",
}

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
    # preserve user_id and uploader_ip across phase transitions
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

def _slot_key(ip: str) -> str:
    return f"active_jobs:{ip}"


def _slot_release_marker(job_id: str) -> str:
    return f"job:{job_id}:slot_released"


async def acquire_job_slot(ip: str, max_active: int = MAX_ACTIVE_JOBS_PER_IP) -> None:
    """Increment per-IP job counter. 429 if over the limit."""
    from fastapi import HTTPException

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
    """Release one slot. Safe to call multiple times — only decrements once."""
    marker = _slot_release_marker(job_id)
    was_first = await redis_client.set(marker, "1", ex=3600, nx=True)
    if not was_first:
        return
    key = _slot_key(ip)
    val = await redis_client.decr(key)
    if val <= 0:
        await redis_client.delete(key)