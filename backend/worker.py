"""
worker.py — arq worker entry point.

Run with:
    arq worker.WorkerSettings

The worker pulls jobs off the `arq:queue:default` list, runs the same
extraction pipeline that lived synchronously inside api.py before, and
persists the result both to Postgres (via SQLAlchemy) and to a Redis
job-state blob (via jobs.write_state).

This file does NOT modify any of the existing extraction modules
(extractor.py, scorer.py, parser.py, models.py). It just orchestrates
them — exactly as api.py used to.
"""
from __future__ import annotations

import concurrent.futures
import json
import logging
import os
from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import insert

from constants import CONTEXT_SIZES
from db import AsyncSessionLocal
from db_models import Syllabus
from extractor import extract_document
from jobs import write_state
from models import SyllabusData
from parser import word_parser
from scorer import prune_blocks_to_context_limit, score_and_size_blocks


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mirrors api.py — defense in depth even though arq has its own job timeout.
DOCLING_TIMEOUT_SECONDS: int = int(os.environ.get("DOCLING_TIMEOUT_SECONDS", "500"))
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _redis_settings_from_url(url: str) -> RedisSettings:
    """Convert a redis:// URL into arq's RedisSettings dataclass."""
    return RedisSettings.from_dsn(url)


# ── The validation helpers that previously lived in api.py ────────────────────
# These are literal copies of the api.py functions. They run inside the worker
# (post-extraction) because the LLM output cannot be validated until after
# parsing. Keeping them here means the worker has zero runtime dependency on
# the FastAPI app module.

import re                       # noqa: E402
import unicodedata               # noqa: E402

_INJECTION_PATTERNS = re.compile(
    r"[^\n]*\b(?:ignore|disregard|forget|your instructions|system prompt"
    r"|/etc/|<script|eval\(|base64)\b[^\n]*",
    re.IGNORECASE,
)
_REJECT_PATTERNS = re.compile(
    r"/etc/|<script|eval\(|base64|ignore instructions|\x00",
    re.IGNORECASE,
)
_SHORT_FIELDS = {
    "course_title", "course_code", "section_code", "instructor",
    "email", "office_hours", "term",
}


def sanitize_extracted_text(text: str) -> str:
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    text = "\n".join(
        p[:1000] if len(p) > 1000 and " " not in p[:1000] else p
        for p in text.split("\n")
    )
    text = _INJECTION_PATTERNS.sub("", text)
    return text.strip()


class _LLMOutputError(Exception):
    """Raised when the LLM's parsed JSON fails validation. The worker catches
    this and writes a 'failed' state with the message preserved."""


def validate_llm_output(data: dict) -> None:
    def check(v: Any, path: str) -> None:
        if isinstance(v, str):
            if _REJECT_PATTERNS.search(v):
                raise _LLMOutputError(f"LLM output contained disallowed content at {path}.")
            if path.split(".")[-1] in _SHORT_FIELDS and len(v) > 300:
                raise _LLMOutputError(f"Field {path!r} exceeds maximum length.")
        elif isinstance(v, dict):
            for k, child in v.items():
                check(child, f"{path}.{k}")
        elif isinstance(v, list):
            for i, child in enumerate(v):
                check(child, f"{path}[{i}]")

    check(data, "root")


def _run_extraction_with_timeout(tmp_path: str):
    """Same pattern as api.py's run_extraction_with_timeout: ThreadPoolExecutor
    avoids the cold-start cost of multiprocessing.spawn on Windows."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(extract_document, tmp_path)
        try:
            return future.result(timeout=DOCLING_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            raise _LLMOutputError("Processing timed out during extraction.")


# ── The actual job ────────────────────────────────────────────────────────────
async def process_syllabus(ctx: dict, job_id: str, tmp_path: str, safe_filename: str) -> dict:
    """Run the full extraction pipeline and persist the result.

    The return value is also what `arq` records as the job's result, but
    callers should poll Redis state via `jobs.read_state` for the user-facing
    status — that's where progress and phase labels live.
    """
    logger.info("[%s] starting job for %s", job_id, safe_filename)

    try:
        # ── Phase: extracting ────────────────────────────────────────────────
        await write_state(job_id, status="running", phase="extracting")
        blocks = _run_extraction_with_timeout(tmp_path)

        # ── Phase: scoring + pruning ─────────────────────────────────────────
        await write_state(job_id, status="running", phase="scoring")
        score_and_size_blocks(blocks)
        pruned = prune_blocks_to_context_limit(blocks, CONTEXT_SIZES["fast"])
        raw_text = "\n\n".join(b.text for b in pruned)
        full_text = sanitize_extracted_text(raw_text)

        # ── Phase: LLM parsing ───────────────────────────────────────────────
        await write_state(job_id, status="running", phase="parsing")
        raw_result = await word_parser(full_text, CONTEXT_SIZES["fast"])

        try:
            parsed_json = json.loads(raw_result)
        except json.JSONDecodeError as e:
            raise _LLMOutputError("LLM returned invalid JSON.") from e

        # ── Phase: validating ────────────────────────────────────────────────
        await write_state(job_id, status="running", phase="validating")
        try:
            validated = SyllabusData.model_validate(parsed_json)
            parsed_json = validated.model_dump()
        except Exception as e:
            raise _LLMOutputError("LLM output failed schema validation.") from e

        validate_llm_output(parsed_json)

        # ── Persist to Postgres ──────────────────────────────────────────────
        async with AsyncSessionLocal() as session:
            await session.execute(
                insert(Syllabus).values(
                    filename=safe_filename,
                    data=parsed_json,
                    job_id=job_id,
                )
            )
            await session.commit()

        # ── Final state ──────────────────────────────────────────────────────
        # Result shape mirrors what /upload returned in the synchronous era:
        #   { "filename": str, "data": dict }
        # This is what the frontend reads via the polling endpoint's `result`.
        result = {"filename": safe_filename, "data": parsed_json}
        await write_state(job_id, status="complete", phase="complete", result=result)
        logger.info("[%s] complete", job_id)
        return result

    except _LLMOutputError as e:
        logger.warning("[%s] failed: %s", job_id, e)
        await write_state(job_id, status="failed", phase="validating", error=str(e))
        # Re-raise so arq records this as a job failure too.
        raise

    except Exception as e:
        logger.exception("[%s] unexpected failure", job_id)
        await write_state(
            job_id,
            status="failed",
            phase="validating",
            error="An unexpected error occurred during processing.",
        )
        raise

    finally:
        # The temp file was created by the API and handed off via path. The
        # worker owns its lifecycle from enqueue onward.
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            logger.warning("[%s] could not delete temp file %s", job_id, tmp_path)


class WorkerSettings:
    """arq picks this up via `arq worker.WorkerSettings`."""

    functions = [process_syllabus]
    redis_settings = _redis_settings_from_url(REDIS_URL)

    # arq's per-job hard ceiling. The Docling timeout inside the function
    # hits first under normal failure; this is a backstop for everything else.
    job_timeout = DOCLING_TIMEOUT_SECONDS + 60

    # We don't retry: extraction failures are almost always deterministic
    # (bad PDF, LLM output shape) and a retry just wastes ~60 s.
    max_tries = 1

    # Keep a small history so duplicate-job-id submissions can be detected.
    keep_result = 60 * 60   # 1 hour
