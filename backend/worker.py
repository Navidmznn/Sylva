"""arq worker. Runs the Docling → score → prune → Ollama → validate pipeline
off the request thread. Run with: `arq worker.WorkerSettings`."""
from __future__ import annotations

# Load .env BEFORE sibling imports — same reasoning as api.py: constants.py,
# db.py, and redis_client.py all read env vars at import time.
from dotenv import load_dotenv
load_dotenv()

import concurrent.futures
import json
import logging
import os
import re
import unicodedata
from typing import Any

from arq.connections import RedisSettings
from sqlalchemy import insert

from constants import CONTEXT_SIZES
from db import AsyncSessionLocal
from db_models import Syllabus
from extractor import extract_document
from jobs import read_state, release_job_slot, write_state
from models import SyllabusData
from parser import word_parser
from scorer import prune_blocks_to_context_limit, score_and_size_blocks


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Mirrors api.py — defense in depth on top of arq's job_timeout.
DOCLING_TIMEOUT_SECONDS: int = int(os.environ.get("DOCLING_TIMEOUT_SECONDS", "500"))
REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


def _redis_settings_from_url(url: str) -> RedisSettings:
    return RedisSettings.from_dsn(url)


# Validation helpers — duplicated from api.py so the worker has no runtime
# dependency on the FastAPI app module. Keep these in sync if the patterns
# change.
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
    """LLM output failed validation. The worker writes a 'failed' state with
    this message preserved."""


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
    # ThreadPoolExecutor (not multiprocessing) avoids the cold-start cost of
    # spawn() on Windows.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(extract_document, tmp_path)
        try:
            return future.result(timeout=DOCLING_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            raise _LLMOutputError("Processing timed out during extraction.")


# The job

async def process_syllabus(
    ctx: dict,
    job_id: str,
    tmp_path: str,
    safe_filename: str,
    user_id: str | None,
) -> dict:
    """Run the extraction pipeline. user_id is the User UUID supplied by the
    API at enqueue time, or None for guest uploads. Guest jobs skip the DB
    insert — their parsed result lives only in Redis job state (TTL'd) and
    in the requesting browser's memory. No persistence, by design."""
    logger.info(
        "[%s] starting job for %s (user=%s)",
        job_id, safe_filename, user_id or "<guest>",
    )

    try:
        await write_state(job_id, status="running", phase="extracting")
        blocks = _run_extraction_with_timeout(tmp_path)

        await write_state(job_id, status="running", phase="scoring")
        score_and_size_blocks(blocks)
        pruned = prune_blocks_to_context_limit(blocks, CONTEXT_SIZES["fast"])
        raw_text = "\n\n".join(b.text for b in pruned)
        full_text = sanitize_extracted_text(raw_text)

        await write_state(job_id, status="running", phase="parsing")
        raw_result = await word_parser(full_text, CONTEXT_SIZES["fast"])

        try:
            parsed_json = json.loads(raw_result)
        except json.JSONDecodeError as e:
            raise _LLMOutputError("LLM returned invalid JSON.") from e

        await write_state(job_id, status="running", phase="validating")
        try:
            validated = SyllabusData.model_validate(parsed_json)
            parsed_json = validated.model_dump()
        except Exception as e:
            raise _LLMOutputError("LLM output failed schema validation.") from e

        validate_llm_output(parsed_json)

        # Guests skip persistence entirely. Their result still flows back to
        # the browser via /jobs/{id} (Redis state, TTL'd) — they just don't
        # get a syllabus row, can't list it via /syllabi, and can't refresh
        # to recover it. "Sign in to save" is the upgrade path.
        if user_id is not None:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    insert(Syllabus).values(
                        user_id=user_id,
                        filename=safe_filename,
                        data=parsed_json,
                        job_id=job_id,
                    )
                )
                await session.commit()

        # Result shape matches the v1 synchronous /upload contract:
        #   { "filename": str, "data": dict }
        result = {"filename": safe_filename, "data": parsed_json}
        await write_state(job_id, status="complete", phase="complete", result=result)
        logger.info("[%s] complete", job_id)
        return result

    except _LLMOutputError as e:
        logger.warning("[%s] failed: %s", job_id, e)
        await write_state(job_id, status="failed", phase="validating", error=str(e))
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
        # Release the per-IP concurrency slot. This is the PRIMARY release
        # path — guaranteed to fire for any caught exception or successful
        # completion. The API's GET /jobs/{id} also calls release on terminal
        # status as a backstop for cases where this finally never runs (the
        # worker process was killed). Both paths are idempotent via the
        # slot_released marker inside release_job_slot.
        try:
            state = await read_state(job_id)
            uploader_ip = (state or {}).get("uploader_ip")
            if uploader_ip:
                await release_job_slot(job_id, uploader_ip)
        except Exception:
            logger.exception("[%s] slot release failed", job_id)

        # Worker owns the temp file from enqueue onward.
        try:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except OSError:
            logger.warning("[%s] could not delete temp file %s", job_id, tmp_path)


class WorkerSettings:
    functions = [process_syllabus]
    redis_settings = _redis_settings_from_url(REDIS_URL)

    # Backstop for everything Docling's own timeout doesn't catch.
    job_timeout = DOCLING_TIMEOUT_SECONDS + 60

    # Don't retry — extraction failures are deterministic (bad PDF / bad LLM
    # output shape) and a retry just wastes ~60 s.
    max_tries = 1

    keep_result = 60 * 60