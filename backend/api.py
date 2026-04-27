"""
api.py — FastAPI entry point (with magic-link auth).

What changed from the prior job-queue version
─────────────────────────────────────────────
* Authentication: magic-link only. New endpoints under /auth/*.
* /upload now requires an authenticated user; the user's id is stored with
  the job state so /jobs/{id} can authorize.
* /jobs/{id} returns 404 (not 403) for jobs the current user doesn't own,
  so the existence of another user's job is not revealed.
* /results and /results/clear are GONE. Replaced by per-user /syllabi
  routes. The frontend's prior best-effort wipe of /results is also removed.
* CORS: allow_origins is now a single explicit FRONTEND_ORIGIN, plus
  allow_credentials=True so the session cookie rides along.
* /privacy renders the privacy policy as plain HTML.

Note: this module deliberately does NOT use `from __future__ import
annotations` — turning FastAPI parameter annotations into strings breaks
Pydantic v2's TypeAdapter resolution at OpenAPI-build time.
"""
import json as _json
import logging
import os
import re
import tempfile
import unicodedata
import uuid
from pathlib import Path
from typing import Annotated, Optional

import pikepdf
from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

import auth
from auth import (
    COOKIE_NAME,
    clear_session_cookie,
    create_session,
    get_current_user,
    redeem_magic_link,
    request_magic_link,
    require_user,
    revoke_session,
    set_session_cookie,
)
from db import AsyncSessionLocal, get_session
from db_models import MagicToken, Session as SessionRow, Syllabus, User
from email_sender import send_magic_link_email
from jobs import init_job, read_state
from privacy import render_privacy_html
from redis_client import REDIS_URL, redis_client


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
MAX_FILE_SIZE = 20 * 1024 * 1024
CHUNK_SIZE    = 1024 * 1024
MAX_PAGES     = 80
DOCLING_TIMEOUT_SECONDS = 500
MAX_ACTIVE_JOBS_PER_IP  = 1
ACTIVE_JOB_TTL_SECONDS  = 30 * 60

UPLOAD_TMPDIR = os.environ.get("UPLOAD_TMPDIR", tempfile.gettempdir())

# Where to send the user after a successful magic-link redemption.
FRONTEND_ORIGIN  = os.environ.get("FRONTEND_ORIGIN",  "http://localhost:5500")
BACKEND_BASE_URL = os.environ.get("BACKEND_BASE_URL", "http://localhost:8000")

UPLOAD_SYNC_ENABLED = os.environ.get("UPLOAD_SYNC_ENABLED", "true").lower() == "true"

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
        content={"detail": "Too many requests. Try again in a minute."},
    )


# CORS now requires an exact origin (no wildcard) because we want the browser
# to send the session cookie along. allow_credentials=True is incompatible
# with allow_origins=["*"].
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── arq pool lifecycle ────────────────────────────────────────────────────────
@app.on_event("startup")
async def _create_arq_pool() -> None:
    app.state.arq = await create_pool(RedisSettings.from_dsn(REDIS_URL))


@app.on_event("shutdown")
async def _close_arq_pool() -> None:
    pool: Optional[ArqRedis] = getattr(app.state, "arq", None)
    if pool is not None:
        await pool.close()


# ═════════════════════════════════════════════════════════════════════════════
# AUTH
# ═════════════════════════════════════════════════════════════════════════════
@app.post("/auth/login")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def auth_login(request: Request) -> dict:
    """Request a magic link.

    Always returns the same payload regardless of whether the email already
    has an account, to prevent enumeration. The user is auto-created on
    first contact.
    """
    body = await request.json()
    email = (body or {}).get("email")
    if not isinstance(email, str):
        raise HTTPException(status_code=400, detail="Email is required.")

    raw_token, user = await request_magic_link(email)
    link = f"{BACKEND_BASE_URL}/auth/verify?token={raw_token}"
    await send_magic_link_email(user.email, link)

    # Generic, non-revealing response.
    return {"ok": True, "message": "If that email is valid, a sign-in link is on its way."}


@app.get("/auth/verify")
async def auth_verify(
    token: str,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
    """Validate a magic token, mint a session, set the cookie, redirect to
    the frontend."""
    user = await redeem_magic_link(token, db)
    raw_session = await create_session(user.id, db)

    redirect = RedirectResponse(url=f"{FRONTEND_ORIGIN}/?logged_in=1", status_code=303)
    set_session_cookie(redirect, raw_session)
    return redirect


@app.get("/auth/me")
async def auth_me(user: Optional[User] = Depends(get_current_user)) -> dict:
    if user is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {"id": str(user.id), "email": user.email},
    }


@app.post("/auth/logout")
async def auth_logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_session),
) -> dict:
    raw = request.cookies.get(COOKIE_NAME)
    if raw:
        await revoke_session(raw, db)
    clear_session_cookie(response)
    return {"ok": True}


# ═════════════════════════════════════════════════════════════════════════════
# UPLOAD HELPERS
# ═════════════════════════════════════════════════════════════════════════════
async def stream_upload_to_temp(file: UploadFile, *, dirpath: Optional[str] = None) -> str:
    total = 0
    tmp_path: Optional[str] = None
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


async def _validate_pdf(file: UploadFile, *, dirpath: Optional[str] = None) -> tuple[str, str]:
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
        await redis_client.delete(key)


# ═════════════════════════════════════════════════════════════════════════════
# /upload  (now requires auth)
# ═════════════════════════════════════════════════════════════════════════════
@app.post("/upload")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def upload_syllabus(
    request: Request,
    file: Annotated[UploadFile, File()],
    user: User = Depends(require_user),
) -> dict:
    client_ip = get_remote_address(request)
    tmp_path, safe_filename = await _validate_pdf(file, dirpath=UPLOAD_TMPDIR)

    try:
        await acquire_job_slot(client_ip)
    except HTTPException:
        os.unlink(tmp_path)
        raise

    job_id = uuid.uuid4().hex
    user_id_str = str(user.id)
    try:
        await init_job(job_id, user_id=user_id_str)
        enqueued = await app.state.arq.enqueue_job(
            "process_syllabus",
            job_id, tmp_path, safe_filename, user_id_str,
            _job_id=job_id,
        )
        if enqueued is None:
            raise HTTPException(status_code=500, detail="Could not enqueue job.")
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        await release_job_slot(client_ip)
        raise

    return {"job_id": job_id, "filename": safe_filename}


# ═════════════════════════════════════════════════════════════════════════════
# /jobs/{id}  (scoped to current user)
# ═════════════════════════════════════════════════════════════════════════════
@app.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    user: User = Depends(require_user),
) -> dict:
    state = await read_state(job_id)

    # Two failure modes deliberately collapse to 404 so we don't reveal that
    # *some* user has a job with this id:
    #   1. job doesn't exist
    #   2. job exists but belongs to someone else
    if state is None or state.get("user_id") != str(user.id):
        raise HTTPException(status_code=404, detail="Unknown job id.")

    if state["status"] in ("complete", "failed"):
        client_ip = get_remote_address(request)
        marker = f"job:{job_id}:slot_released"
        was_set = await redis_client.set(marker, "1", ex=3600, nx=True)
        if was_set:
            await release_job_slot(client_ip)

    # Strip user_id from the response — callers don't need it and it's
    # internal bookkeeping.
    return {k: v for k, v in state.items() if k != "user_id"}


# ═════════════════════════════════════════════════════════════════════════════
# /upload-sync  (legacy fallback, now also auth-gated and user-scoped)
# ═════════════════════════════════════════════════════════════════════════════
@app.post("/upload-sync")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def upload_syllabus_sync(
    request: Request,
    file: Annotated[UploadFile, File()],
    user: User = Depends(require_user),
) -> dict:
    if not UPLOAD_SYNC_ENABLED:
        raise HTTPException(status_code=403, detail="The synchronous upload path is disabled.")

    import concurrent.futures

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

        async with AsyncSessionLocal() as session:
            session.add(Syllabus(user_id=user.id, filename=safe_filename, data=parsed_json))
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
# /syllabi  (per-user)
# ═════════════════════════════════════════════════════════════════════════════
@app.get("/syllabi")
async def list_syllabi(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> list[dict]:
    rows = (
        await db.execute(
            select(Syllabus.id, Syllabus.filename, Syllabus.data, Syllabus.created_at)
            .where(Syllabus.user_id == user.id)
            .order_by(Syllabus.created_at.asc())
        )
    ).all()
    return [
        {
            "id":         str(r.id),
            "filename":   r.filename,
            "data":       r.data,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]


@app.patch("/syllabi/{syllabus_id}")
async def patch_syllabus(
    syllabus_id: str,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Update the courses array inside a syllabus row.

    Called when the user deletes a single course from a PDF that contained
    multiple courses — the row survives but with the deleted course removed.
    The WHERE clause is pinned to user_id so cross-user writes are impossible.
    """
    try:
        sid = uuid.UUID(syllabus_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found.")

    body = await request.json()
    updated_courses = body.get("courses")
    if not isinstance(updated_courses, list):
        raise HTTPException(status_code=400, detail="'courses' must be a list.")

    result = await db.execute(
        select(Syllabus).where(Syllabus.id == sid, Syllabus.user_id == user.id)
    )
    row: Syllabus | None = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found.")

    # Merge into the existing data blob so any other top-level keys
    # (instructor, term, etc. at the syllabus level) are preserved.
    row.data = {**row.data, "courses": updated_courses}
    await db.commit()
    return {"updated": True}


@app.delete("/syllabi/{syllabus_id}")
async def delete_syllabus(
    syllabus_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Delete one syllabus owned by the current user.

    The WHERE clause is pinned to user_id so cross-user delete attempts can
    never match. We surface 404 — not 403 — to avoid revealing that the id
    exists for another user.
    """
    try:
        sid = uuid.UUID(syllabus_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found.")

    result = await db.execute(
        delete(Syllabus).where(Syllabus.id == sid, Syllabus.user_id == user.id)
    )
    await db.commit()
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Not found.")
    return {"deleted": True}


# ═════════════════════════════════════════════════════════════════════════════
# /account  — full deletion
# ═════════════════════════════════════════════════════════════════════════════
@app.delete("/account")
async def delete_account(
    response: Response,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Wipe the current user's data and sign them out.

    syllabi/sessions/magic_tokens cascade-delete via the FK constraint, so
    deleting the User row drops everything in one statement. We do it
    explicitly anyway to be unambiguous.
    """
    uid = user.id
    await db.execute(delete(Syllabus).where(Syllabus.user_id == uid))
    await db.execute(delete(SessionRow).where(SessionRow.user_id == uid))
    await db.execute(delete(MagicToken).where(MagicToken.user_id == uid))
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()

    clear_session_cookie(response)
    return {"deleted": True}


# ═════════════════════════════════════════════════════════════════════════════
# /privacy
# ═════════════════════════════════════════════════════════════════════════════
@app.get("/privacy", response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    return HTMLResponse(content=render_privacy_html())