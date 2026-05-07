"""FastAPI app. Auth, upload, job polling, syllabus CRUD."""
# load env before any other imports read env vars
from dotenv import load_dotenv
load_dotenv()

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
from pydantic import TypeAdapter
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
from jobs import acquire_job_slot, init_job, read_state, release_job_slot
from models import Course
from privacy import render_privacy_html
from redis_client import REDIS_URL, redis_client


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 20 * 1024 * 1024
CHUNK_SIZE    = 1024 * 1024
MAX_PAGES     = 80
DOCLING_TIMEOUT_SECONDS = 500

UPLOAD_TMPDIR = os.environ.get("UPLOAD_TMPDIR", tempfile.gettempdir())

FRONTEND_ORIGIN  = os.environ.get("FRONTEND_ORIGIN",  "http://localhost:3000")
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

# compiled once at startup
_COURSES_ADAPTER: TypeAdapter[list[Course]] = TypeAdapter(list[Course])


# redis-backed so limits are shared across workers
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL,
    strategy="fixed-window",
)


app = FastAPI()
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Try again in a minute."},
    )


# wildcard origin incompatible with credentials
app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _create_arq_pool() -> None:
    app.state.arq = await create_pool(RedisSettings.from_dsn(REDIS_URL))


@app.on_event("shutdown")
async def _close_arq_pool() -> None:
    pool: Optional[ArqRedis] = getattr(app.state, "arq", None)
    if pool is not None:
        await pool.close()


# Auth routes

@app.post("/auth/login")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def auth_login(request: Request) -> dict:
    """Send magic link. Always 200 regardless of whether the email exists."""
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    email = body.get("email") if isinstance(body, dict) else None
    if not isinstance(email, str):
        raise HTTPException(status_code=400, detail="Email is required.")

    raw_token, user = await request_magic_link(email)
    link = f"{BACKEND_BASE_URL}/auth/verify?token={raw_token}"
    await send_magic_link_email(user.email, link)

    return {"ok": True, "message": "If that email is valid, a sign-in link is on its way."}


@app.get("/auth/verify")
async def auth_verify(
    token: str,
    response: Response,
    db: AsyncSession = Depends(get_session),
):
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


# Upload helpers

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


# Upload routes

@app.post("/upload")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def upload_syllabus(
    request: Request,
    file: Annotated[UploadFile, File()],
    user: Optional[User] = Depends(get_current_user),
) -> dict:
    """Accept upload, validate, enqueue. Guests skip DB persistence."""
    client_ip = get_remote_address(request)
    tmp_path, safe_filename = await _validate_pdf(file, dirpath=UPLOAD_TMPDIR)

    try:
        await acquire_job_slot(client_ip)
    except HTTPException:
        os.unlink(tmp_path)
        raise

    job_id = uuid.uuid4().hex
    user_id_str: str | None = str(user.id) if user is not None else None
    try:
        await init_job(job_id, user_id=user_id_str, uploader_ip=client_ip)
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
        await release_job_slot(job_id, client_ip)
        raise

    return {"job_id": job_id, "filename": safe_filename}


@app.get("/jobs/{job_id}")
async def get_job(
    job_id: str,
    request: Request,
    user: Optional[User] = Depends(get_current_user),
) -> dict:
    """Poll job status. 404 for other users' jobs."""
    state = await read_state(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")

    job_user_id = state.get("user_id")
    if job_user_id is not None:
        if user is None or job_user_id != str(user.id):
            raise HTTPException(status_code=404, detail="Unknown job id.")
    else:
        if state.get("uploader_ip") != get_remote_address(request):
            raise HTTPException(status_code=404, detail="Unknown job id.")

    if state["status"] in ("complete", "failed"):
        # release slot if worker didn't get a chance to
        ip_to_release = state.get("uploader_ip") or get_remote_address(request)
        await release_job_slot(job_id, ip_to_release)

    return {k: v for k, v in state.items() if k not in ("user_id", "uploader_ip")}


@app.post("/upload-sync")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def upload_syllabus_sync(
    request: Request,
    file: Annotated[UploadFile, File()],
    user: Optional[User] = Depends(get_current_user),
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

    sync_job_id = uuid.uuid4().hex

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
            await release_job_slot(sync_job_id, client_ip)

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

        raw_result = await word_parser(full_text)
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

        if user is not None:
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


# Per-user syllabi

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
@limiter.limit("60/minute")
async def patch_syllabus(
    syllabus_id: str,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    """Update courses array on a syllabus row. Re-validates against schema."""
    try:
        sid = uuid.UUID(syllabus_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found.")

    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")

    raw_courses = body.get("courses") if isinstance(body, dict) else None
    if not isinstance(raw_courses, list):
        raise HTTPException(status_code=400, detail="'courses' must be a list.")

    try:
        validated = _COURSES_ADAPTER.validate_python(raw_courses)
    except Exception:
        # generic error — don't leak schema details
        raise HTTPException(status_code=422, detail="Invalid courses payload.")
    normalized = [c.model_dump() for c in validated]

    result = await db.execute(
        select(Syllabus).where(Syllabus.id == sid, Syllabus.user_id == user.id)
    )
    row: Syllabus | None = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Not found.")

    row.data = {**row.data, "courses": normalized}
    await db.commit()
    return {"updated": True}


@app.delete("/syllabi/{syllabus_id}")
@limiter.limit("60/minute")
async def delete_syllabus(
    syllabus_id: str,
    request: Request,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
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


@app.delete("/account")
@limiter.limit("3/minute")
async def delete_account(
    request: Request,
    response: Response,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_session),
) -> dict:
    uid = user.id
    await db.execute(delete(Syllabus).where(Syllabus.user_id == uid))
    await db.execute(delete(SessionRow).where(SessionRow.user_id == uid))
    await db.execute(delete(MagicToken).where(MagicToken.user_id == uid))
    await db.execute(delete(User).where(User.id == uid))
    await db.commit()

    clear_session_cookie(response)
    return {"deleted": True}


@app.get("/privacy", response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    return HTMLResponse(content=render_privacy_html())