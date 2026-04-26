"""
jobs.py — job-state schema + Redis read/write helpers.

The arq library tracks its own internal job lifecycle, but we need richer,
user-facing state (phase labels, percent-complete, terminal result/error). We
store that as a JSON blob at `job:<id>` which is updated by the worker as it
moves through phases.

Schema written under `job:<id>`:
    {
      "status":   "queued" | "running" | "complete" | "failed",
      "progress": int (0-100),
      "phase":    str (e.g. "extracting", "parsing"),
      "result":   { "filename": str, "data": dict } | null,
      "error":    str | null,
      "updated_at": iso8601 timestamp
    }

Keys live in db=0 with TTL = JOB_STATE_TTL_SECONDS so finished jobs eventually
fall off Redis without manual cleanup.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from redis_client import redis_client


JOB_STATE_TTL_SECONDS: int = int(os.environ.get("JOB_STATE_TTL_SECONDS", str(60 * 60 * 24)))

# Phase labels — surfaced verbatim to the frontend's loading-subtitle. Keep
# user-friendly; treat as part of the public API once the frontend reads them.
PHASE_LABELS: dict[str, str] = {
    "queued":     "Waiting in line...",
    "extracting": "Reading your PDF...",
    "scoring":    "Finding the important parts...",
    "parsing":    "Asking the AI to structure it...",
    "validating": "Double-checking the output...",
    "complete":   "Done!",
}

# Heuristic progress percentages per phase. Docling itself does not report
# progress, so the bar advances in coarse jumps. The user prompt acknowledges
# this is heuristic; values are tuned to roughly match observed wall-clock.
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


async def init_job(job_id: str) -> None:
    """Write the initial 'queued' state. Called by the API after enqueue."""
    await write_state(job_id, status="queued", phase="queued")


async def write_state(
    job_id: str,
    *,
    status: str,
    phase: str,
    result: dict | None = None,
    error: str | None = None,
) -> None:
    """Replace the job's state document. The worker calls this once per phase."""
    payload: dict[str, Any] = {
        "status":     status,
        "progress":   PHASE_PROGRESS.get(phase, 0),
        "phase":      PHASE_LABELS.get(phase, phase),
        "result":     result,
        "error":      error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await redis_client.set(_key(job_id), json.dumps(payload), ex=JOB_STATE_TTL_SECONDS)


async def read_state(job_id: str) -> dict | None:
    raw = await redis_client.get(_key(job_id))
    if raw is None:
        return None
    return json.loads(raw)
