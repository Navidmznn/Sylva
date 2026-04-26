"""
api.py — FastAPI entry point.

Architecture (v2 — job-queue model)
───────────────────────────────────
POST /upload    : validates the PDF (mime, size, magic bytes, pikepdf
                  structure, per-IP slot), writes the bytes to a temp path
                  the worker will read, enqueues an arq job, and returns
                  {"job_id": str, "filename": str}. Returns *immediately* —
                  the heavy extraction runs in worker.py.

GET  /jobs/{id} : returns {status, progress, phase, result?, error?}
                  by reading the JSON blob worker.py writes to Redis.
                  Frontend polls this every 2 s.

POST /upload-sync : the previous synchronous extraction path, kept verbatim
                    as a fallback. Useful for parity testing and for when
                    Redis/worker aren't running. Disabled by default in
                    production via UPLOAD_SYNC_ENABLED=false.

GET  /results, DELETE /results/clear : unchanged in shape; backed by
                    Postgres now via SQLAlchemy. The wire format
                    [{"filename": ..., "data": ...}, ...] is preserved so
                    the frontend's persistence layer needs no changes.

Redis-backed concerns
─────────────────────
* slowapi rate-limit storage (was in-memory) → REDIS_URL via storage_uri.
* per-IP active-job counter (was a defaultdict + asyncio.Lock) →
  INCR/DECR on `active_jobs:<ip>` with a safety TTL.
"""

from typing import Annotated
import logging
import os
import re
import tempfile
import unicodedata
import uuid
from pathlib import Path

import pikepdf
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import delete, select

from db import AsyncSessionLocal
from db_models import Syllabus
from jobs import init_job, read_state
from redis_client import REDIS_URL, redis_client


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = 20 * 1024 * 1024   # 20 MB
CHUNK_SIZE    = 1024 * 1024         # 1 MB streaming chunks
MAX_PAGES     = 80
DOCLING_TIMEOUT_SECONDS = 500
MAX_ACTIVE_JOBS_PER_IP  = 1
# Per-IP slot expiry safety net — if the worker crashes mid-job and the
# DECR never fires, the slot self-clears after this many seconds.
ACTIVE_JOB_TTL_SECONDS  = 30 * 60

RESULTS_ENABLED      = os.environ.get("RESULTS_ENABLED",      "true").lower() == "true"
UPLOAD_SYNC_ENABLED  = os.environ.get("UPLOAD_SYNC_ENABLED",  "true").lower() == "true"

# Where the worker reads incoming PDFs. The default tempdir works for single-
# host dev (api + worker share the filesystem). For multi-host deployments
# this needs to be a shared volume — flagged in README.md.
UPLOAD_TMPDIR = os.environ.get("UPLOAD_TMPDIR", tempfile.gettempdir())

# ── Prompt-injection / LLM-output filters (kept here for /upload-sync use) ────
_INJECTION_PATTERNS = re.compile(
    r"[^\n]*\b(?:ignore|disregard|forget|your instructions|system prompt"
    r"|/etc/|<script|eval\(|base64)\b[^\n]*",
    re.IGNORECASE,
)
_REJECT_PATTERNS = re.compile(
    r"/etc/|<script|eval\(|base64|ignore instructions|\x00",
    re.IGNORECASE,
)
_SHORT_FIELDS = {"course_title", "course_code", "section_code", "instructor",
                 "email", "office_hours", "term"}


# ── Rate limiter (Redis-backed) ───────────────────────────────────────────────
# storage_uri moves slowapi's accounting from in-memory (per-process, lost on
# restart, broken under multiple workers) to Redis (shared across uvicorn
# workers and across container restarts).
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL,
    strategy="fixed-window",
)


# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI()
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Upload limit reached. Maximum 5 uploads per minute and 20 per hour per IP."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── arq pool lifecycle ────────────────────────────────────────────────────────
@app.on_event("startup")
async def _create_arq_pool() -> None:
    app.state.arq = await create_pool(RedisSettings.from_dsn(REDIS_URL))


@app.on_event("shutdown")
async def _close_arq_pool() -> None:
    pool: ArqRedis | None = getattr(app.state, "arq", None)
    if pool is not None:
        await pool.close()


# ── Per-IP slot helpers (Redis) ───────────────────────────────────────────────
# We use INCR + a TTL on first acquire. The TTL is a best-effort safety net
# (slot self-clears even if a worker dies); the happy-path DECR runs in the
# worker's finally clause via /jobs/<id> reads. We over-acquire defensively:
# if an INCR overshoots, we DECR back and reject.
def _slot_key(ip: str) -> str:
    return f"active_jobs:{ip}"


async def acquire_job_slot(ip: str) -> None:
    key = _slot_key(ip)
    new_count = await redis_client.incr(key)
    if new_count == 1:
        await redis_client.expire(key, ACTIVE_JOB_TTL_SECONDS)
    if new_count > MAX_ACTIVE_JOBS_PER_IP:
        await redis_client.decr(key)
        raise HTTPException(
            status_code=429,
            detail="You already have a file being processed. Please wait for it to finish.",
        )


async def release_job_slot(ip: str) -> None:
    key = _slot_key(ip)
    val = await redis_client.decr(key)
    if val <= 0:
        # Don't leave stale 0s lying around — they consume keyspace and
        # confuse debugging. Atomic via DEL.
        await redis_client.delete(key)


# ── Streaming upload (unchanged) ──────────────────────────────────────────────
async def stream_upload_to_temp(file: UploadFile, *, dirpath: str | None = None) -> str:
    """Stream file to a temp path in 1 MB chunks; reject the moment size exceeds limit.

    `dirpath` lets the caller place the file in the worker-readable shared
    directory (UPLOAD_TMPDIR) instead of the OS default tempdir.
    """
    total = 0
    tmp_path: str | None = None
    target_dir = dirpath or tempfile.gettempdir()
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf", dir=target_dir) as tmp:
            tmp_path = tmp.name
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_SIZE:
                    raise HTTPException(status_code=413, detail="File too large. Maximum size is 20MB.")
                tmp.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="Empty files are not accepted.")
        return tmp_path
    except HTTPException:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def sanitize_filename(raw: str) -> str:
    name = Path(raw or "upload.pdf").name
    if os.sep in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return name


def inspect_pdf(path: str) -> None:
    """Validate structure, page count, encryption, and attachments."""
    try:
        with pikepdf.open(path) as pdf:
            page_count = len(pdf.pages)
            if page_count == 0:
                raise HTTPException(status_code=422, detail="PDF has no pages.")
            if page_count > MAX_PAGES:
                raise HTTPException(
                    status_code=413,
                    detail=f"PDF exceeds maximum page limit of {MAX_PAGES} pages.",
                )
            if len(pdf.attachments) > 0:
                raise HTTPException(
                    status_code=422,
                    detail="PDFs with embedded attachments are not accepted.",
                )
    except pikepdf.PasswordError:
        raise HTTPException(
            status_code=422,
            detail="Encrypted or password-protected PDFs are not accepted.",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("pikepdf structural check failed")
        raise HTTPException(status_code=422, detail="PDF could not be safely opened.")


async def _validate_pdf(file: UploadFile, *, dirpath: str | None = None) -> tuple[str, str]:
    """Shared validation pipeline for both /upload and /upload-sync.

    Returns (tmp_path, safe_filename) on success. Caller owns tmp_path
    cleanup if it doesn't enqueue downstream.
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    safe_filename = sanitize_filename(file.filename or "upload.pdf")
    tmp_path = await stream_upload_to_temp(file, dirpath=dirpath)

    try:
        with open(tmp_path, "rb") as f:
            magic = f.read(4)
        if magic != b"%PDF":
            raise HTTPException(status_code=415, detail="File does not appear to be a valid PDF.")

        inspect_pdf(tmp_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise

    return tmp_path, safe_filename


# ═════════════════════════════════════════════════════════════════════════════
# /upload — async (job-queue) path. This is what the frontend talks to.
# ═════════════════════════════════════════════════════════════════════════════
@app.post("/upload")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def upload_syllabus(request: Request, file: Annotated[UploadFile, File()]) -> dict:
    client_ip = get_remote_address(request)

    # Place the temp file inside UPLOAD_TMPDIR so the worker (potentially a
    # different process) can read it. On single-host dev this is just /tmp.
    tmp_path, safe_filename = await _validate_pdf(file, dirpath=UPLOAD_TMPDIR)

    try:
        await acquire_job_slot(client_ip)
    except HTTPException:
        os.unlink(tmp_path)
        raise

    job_id = uuid.uuid4().hex
    try:
        await init_job(job_id)
        # Enqueue with our generated id so we know the lookup key up-front.
        # If arq dedupes a colliding id (extremely unlikely with hex UUIDs)
        # it returns None and we treat that as enqueue failure.
        enqueued = await app.state.arq.enqueue_job(
            "process_syllabus", job_id, tmp_path, safe_filename, _job_id=job_id,
        )
        if enqueued is None:
            raise HTTPException(status_code=500, detail="Could not enqueue job.")
    except Exception:
        # Clean up if enqueue itself fails — the worker would have owned this.
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        await release_job_slot(client_ip)
        raise

    return {"job_id": job_id, "filename": safe_filename}


# ═════════════════════════════════════════════════════════════════════════════
# /jobs/{id} — frontend polls this every 2 s while a job is running.
# ═════════════════════════════════════════════════════════════════════════════
@app.get("/jobs/{job_id}")
async def get_job(job_id: str, request: Request) -> dict:
    state = await read_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")

    # Release the per-IP slot exactly once when the job leaves the running
    # state. Doing this here (rather than in the worker) keeps the IP↔slot
    # mapping out of the worker's concerns. The slot key has a TTL backstop
    # so this branch failing is non-fatal.
    if state["status"] in ("complete", "failed"):
        client_ip = get_remote_address(request)
        # Marker key so concurrent pollers can't double-decrement.
        marker = f"job:{job_id}:slot_released"
        was_set = await redis_client.set(marker, "1", ex=3600, nx=True)
        if was_set:
            await release_job_slot(client_ip)

    return state


# ═════════════════════════════════════════════════════════════════════════════
# /upload-sync — legacy synchronous path, kept as fallback.
# ═════════════════════════════════════════════════════════════════════════════
# Lives behind UPLOAD_SYNC_ENABLED so production can disable it. Useful for:
#   * end-to-end parity tests without Redis/worker running
#   * curl debugging when you want the parsed JSON in one call
#   * fallback if arq has a problem we haven't diagnosed yet
@app.post("/upload-sync")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def upload_syllabus_sync(request: Request, file: Annotated[UploadFile, File()]) -> dict:
    if not UPLOAD_SYNC_ENABLED:
        raise HTTPException(status_code=403, detail="The synchronous upload path is disabled.")

    # Imports kept local — these modules are heavy and only needed on this path.
    import concurrent.futures
    import json as _json

    from constants import CONTEXT_SIZES
    from extractor import extract_document
    from models import SyllabusData
    from parser import word_parser
    from scorer import prune_blocks_to_context_limit, score_and_size_blocks

    client_ip = get_remote_address(request)
    tmp_path, safe_filename = await _validate_pdf(file)

    try:
        await acquire_job_slot(client_ip)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(extract_document, tmp_path)
                try:
                    blocks = future.result(timeout=DOCLING_TIMEOUT_SECONDS)
                except concurrent.futures.TimeoutError:
                    raise HTTPException(status_code=422, detail="Processing timed out.")
                except Exception as e:
                    logger.error("Extraction error: %s", e)
                    raise HTTPException(status_code=500, detail="PDF extraction failed.")
        finally:
            await release_job_slot(client_ip)

        score_and_size_blocks(blocks)
        pruned_blocks = prune_blocks_to_context_limit(blocks, CONTEXT_SIZES["fast"])
        raw_text = "\n\n".join(b.text for b in pruned_blocks)

        # Inline the same sanitizer used by the worker — duplicated rather
        # than imported because worker.py imports lots of arq machinery we
        # don't want loaded just to serve /upload-sync.
        text = "".join(
            ch for ch in raw_text
            if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
        )
        text = "\n".join(
            p[:1000] if len(p) > 1000 and " " not in p[:1000] else p
            for p in text.split("\n")
        )
        full_text = _INJECTION_PATTERNS.sub("", text).strip()

        raw_result = await word_parser(full_text, CONTEXT_SIZES["fast"])
        try:
            parsed_json = _json.loads(raw_result)
        except _json.JSONDecodeError:
            logger.exception("LLM returned invalid JSON")
            raise HTTPException(status_code=502, detail="LLM returned an invalid response.")

        try:
            validated = SyllabusData.model_validate(parsed_json)
            parsed_json = validated.model_dump()
        except Exception:
            logger.exception("LLM output failed schema validation")
            raise HTTPException(status_code=502, detail="LLM output failed validation.")

        # Inline LLM output validator — see note above.
        def _check(v, path: str) -> None:
            if isinstance(v, str):
                if _REJECT_PATTERNS.search(v):
                    raise HTTPException(status_code=422, detail="LLM output contains disallowed content.")
                if path.split(".")[-1] in _SHORT_FIELDS and len(v) > 300:
                    raise HTTPException(status_code=422, detail=f"Field '{path}' exceeds maximum length.")
            elif isinstance(v, dict):
                for k, child in v.items():
                    _check(child, f"{path}.{k}")
            elif isinstance(v, list):
                for i, child in enumerate(v):
                    _check(child, f"{path}[{i}]")

        _check(parsed_json, "root")

        # Persist via Postgres (was sqlite3 in v1).
        async with AsyncSessionLocal() as session:
            session.add(Syllabus(filename=safe_filename, data=parsed_json))
            await session.commit()

        return {"filename": safe_filename, "data": parsed_json}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during /upload-sync")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ═════════════════════════════════════════════════════════════════════════════
# /results — same wire shape as v1, backed by Postgres.
# ═════════════════════════════════════════════════════════════════════════════
RESULTS_MAX_AGE_HOURS: int = int(os.environ.get("RESULTS_MAX_AGE_HOURS", "24"))


@app.get("/results")
async def get_results() -> list[dict]:
    if not RESULTS_ENABLED:
        raise HTTPException(status_code=403, detail="This endpoint is disabled.")

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RESULTS_MAX_AGE_HOURS)

    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(Syllabus.filename, Syllabus.data)
                .where(Syllabus.created_at >= cutoff)
                .order_by(Syllabus.created_at.asc())
            )
        ).all()

    return [{"filename": r.filename, "data": r.data} for r in rows]


@app.delete("/results/clear")
async def delete_results() -> dict:
    if not RESULTS_ENABLED:
        raise HTTPException(status_code=403, detail="This endpoint is disabled.")
    async with AsyncSessionLocal() as session:
        await session.execute(delete(Syllabus))
        await session.commit()
    return {"cleared": True}