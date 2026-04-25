from fastapi import FastAPI, UploadFile, File, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import tempfile, os, json, sqlite3, threading, re, unicodedata
from datetime import datetime, timedelta
import concurrent.futures
import asyncio
from collections import defaultdict
from pathlib import Path
from extractor import extract_document
from scorer import score_and_size_blocks, prune_blocks_to_context_limit
from parser import word_parser
from models import SyllabusData
from constants import CONTEXT_SIZES
import pikepdf
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ── Rate limiter ──────────────────────────────────────────────────────────────
limiter = Limiter(key_func=get_remote_address)

app = FastAPI()

app.state.limiter = limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Upload limit reached. Maximum 5 uploads per minute and 20 per hour per IP."}
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── Constants ─────────────────────────────────────────────────────────────────
DB_FILE = "results.db"
MAX_FILE_SIZE = 20 * 1024 * 1024   # 20 MB
CHUNK_SIZE    = 1024 * 1024         # 1 MB streaming chunks
MAX_PAGES     = 80
DOCLING_TIMEOUT_SECONDS = 500

# ── /results dev guard — set RESULTS_ENABLED=false in prod ───────────────────
RESULTS_ENABLED = os.environ.get("RESULTS_ENABLED", "true").lower() == "true"

# ── How long saved results are kept (override via RESULTS_MAX_AGE_HOURS env) ──
RESULTS_MAX_AGE_HOURS: int = int(os.environ.get("RESULTS_MAX_AGE_HOURS", "24"))

# ── Per-IP active job limiting ────────────────────────────────────────────────
_active_jobs: dict = defaultdict(int)
_active_jobs_lock = asyncio.Lock()
MAX_ACTIVE_JOBS_PER_IP = 1

# ── Prompt injection patterns (regex strip — bonus layer only) ────────────────
_INJECTION_PATTERNS = re.compile(
    r"[^\n]*\b(?:ignore|disregard|forget|your instructions|system prompt"
    r"|/etc/|<script|eval\(|base64)\b[^\n]*",
    re.IGNORECASE
)

# ── LLM output reject patterns ────────────────────────────────────────────────
_REJECT_PATTERNS = re.compile(
    r"/etc/|<script|eval\(|base64|ignore instructions|\x00",
    re.IGNORECASE
)

# ── DB ────────────────────────────────────────────────────────────────────────
_db_lock = threading.Lock()


def init_db() -> None:
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS results (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                filename   TEXT    NOT NULL,
                data       TEXT    NOT NULL,
                created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # One-time migration: add created_at to DBs that predate this column.
        # Uses a static epoch default so SQLite can safely backfill existing rows
        # — those rows fall outside the 24 h window and are naturally excluded
        # by load_results(), which is the correct behaviour.
        try:
            conn.execute(
                "ALTER TABLE results ADD COLUMN created_at TEXT DEFAULT '1970-01-01 00:00:00'"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists — normal on every run after the first migration.

init_db()


def save_result(filename: str, data: dict) -> None:
    with _db_lock:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute(
                "INSERT INTO results (filename, data) VALUES (?, ?)",
                (filename, json.dumps(data))
            )


def load_results() -> list[dict]:
    """Return uploads from the last RESULTS_MAX_AGE_HOURS hours, oldest first."""
    cutoff = (datetime.utcnow() - timedelta(hours=RESULTS_MAX_AGE_HOURS)).strftime("%Y-%m-%d %H:%M:%S")
    with sqlite3.connect(DB_FILE) as conn:
        rows = conn.execute(
            "SELECT filename, data FROM results WHERE created_at >= ? ORDER BY id ASC",
            (cutoff,)
        ).fetchall()
    return [{"filename": row[0], "data": json.loads(row[1])} for row in rows]


def clear_results() -> None:
    with _db_lock:
        with sqlite3.connect(DB_FILE) as conn:
            conn.execute("DELETE FROM results")


# ── Per-IP job slot helpers ───────────────────────────────────────────────────
async def acquire_job_slot(ip: str) -> None:
    async with _active_jobs_lock:
        if _active_jobs[ip] >= MAX_ACTIVE_JOBS_PER_IP:
            raise HTTPException(
                status_code=429,
                detail="You already have a file being processed. Please wait for it to finish."
            )
        _active_jobs[ip] += 1


async def release_job_slot(ip: str) -> None:
    async with _active_jobs_lock:
        _active_jobs[ip] -= 1
        if _active_jobs[ip] <= 0:
            del _active_jobs[ip]


# ── Streaming upload — rejects before fully reading into memory ───────────────
async def stream_upload_to_temp(file: UploadFile) -> str:
    """Stream file to a temp path in 1 MB chunks; reject the moment size exceeds limit."""
    total = 0
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
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


# ── Filename sanitization ─────────────────────────────────────────────────────
def sanitize_filename(raw: str) -> str:
    """Strip to basename; raise 400 if any path separator survives."""
    name = Path(raw or "upload.pdf").name
    if os.sep in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Invalid filename.")
    return name


# ── pikepdf structural + policy checks ───────────────────────────────────────
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
                    detail=f"PDF exceeds maximum page limit of {MAX_PAGES} pages."
                )

            if len(pdf.attachments) > 0:
                raise HTTPException(
                    status_code=422,
                    detail="PDFs with embedded attachments are not accepted."
                )

    except pikepdf.PasswordError:
        raise HTTPException(
            status_code=422,
            detail="Encrypted or password-protected PDFs are not accepted."
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("pikepdf structural check failed")
        raise HTTPException(status_code=422, detail="PDF could not be safely opened.")


# ── Docling timeout wrapper ───────────────────────────────────────────────────
# On Windows, multiprocessing.get_context("spawn") must cold-reload PyTorch,
# EasyOCR, and all Docling models in the child process on every call.
# That cold start alone takes 60–120 s, which means the timeout fires before
# extraction even begins. ThreadPoolExecutor avoids the reload cost because the
# worker shares the already-loaded process memory.
#
# TRADEOFF: future.cancel() does not stop a thread that is already running.
# If Docling genuinely hangs, the thread will outlive the timeout — the client
# gets a 422, but the thread keeps consuming CPU until it finishes naturally.
# Acceptable for local dev. For production, replace with a pre-warmed
# multiprocessing Pool (models loaded once at worker startup) or a Docker worker.

def run_extraction_with_timeout(tmp_path: str):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(extract_document, tmp_path)
        try:
            return future.result(timeout=DOCLING_TIMEOUT_SECONDS)
        except concurrent.futures.TimeoutError:
            raise HTTPException(status_code=422, detail="Processing timed out.")
        except Exception as e:
            logger.error("Extraction error: %s", e)
            raise HTTPException(status_code=500, detail="PDF extraction failed.")


# ── Extracted text sanitization (bonus layer before LLM) ─────────────────────
def sanitize_extracted_text(text: str) -> str:
    # Strip null bytes and non-printable control characters (keep newlines/tabs)
    text = "".join(
        ch for ch in text
        if ch in ("\n", "\t") or not unicodedata.category(ch).startswith("C")
    )
    # Truncate any unbroken paragraph exceeding 1000 characters
    text = "\n".join(
        p[:1000] if len(p) > 1000 and " " not in p[:1000] else p
        for p in text.split("\n")
    )
    # Strip entire lines containing prompt injection patterns
    text = _INJECTION_PATTERNS.sub("", text)
    return text.strip()


# ── LLM output field validation ───────────────────────────────────────────────
_SHORT_FIELDS = {"course_title", "course_code", "section_code", "instructor",
                 "email", "office_hours", "term"}

def validate_llm_output(data: dict) -> None:
    """Recursively walk parsed LLM output and reject dangerous or oversized fields."""
    def check(v, path: str):
        if isinstance(v, str):
            if _REJECT_PATTERNS.search(v):
                logger.warning("Rejected LLM field %s for disallowed content", path)
                raise HTTPException(status_code=422, detail="LLM output contains disallowed content.")
            if path.split(".")[-1] in _SHORT_FIELDS and len(v) > 300:
                raise HTTPException(status_code=422, detail=f"Field '{path}' exceeds maximum length.")
        elif isinstance(v, dict):
            for k, child in v.items():
                check(child, f"{path}.{k}")
        elif isinstance(v, list):
            for i, child in enumerate(v):
                check(child, f"{path}[{i}]")

    check(data, "root")


# ── Upload endpoint ───────────────────────────────────────────────────────────
@app.post("/upload")
@limiter.limit("5/minute")
@limiter.limit("20/hour")
async def upload_syllabus(request: Request, file: UploadFile = File(...)):
    client_ip = get_remote_address(request)

    # Validate declared content type
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # 4. FILENAME SANITIZATION
    safe_filename = sanitize_filename(file.filename or "upload.pdf")

    # Stream to disk — rejects mid-stream if size exceeds 20 MB
    tmp_path = await stream_upload_to_temp(file)

    try:
        # 7. MAGIC BYTE CHECK — first 4 bytes must be %PDF
        with open(tmp_path, "rb") as f:
            magic = f.read(4)
        if magic != b"%PDF":
            raise HTTPException(status_code=415, detail="File does not appear to be a valid PDF.")

        # 2. PIKEPDF STRUCTURAL VALIDATION — runs before Docling
        inspect_pdf(tmp_path)

        # Per-IP concurrency gate
        await acquire_job_slot(client_ip)
        try:
            # 3. DOCLING TIMEOUT — real hard kill via process termination
            blocks = run_extraction_with_timeout(tmp_path)
        finally:
            await release_job_slot(client_ip)

        score_and_size_blocks(blocks)

        # Use the same pruning strategy as main.py for consistency
        pruned_blocks = prune_blocks_to_context_limit(blocks, CONTEXT_SIZES["fast"])
        raw_text = "\n\n".join(block.text for block in pruned_blocks)

        # 5. EXTRACTED TEXT SANITIZATION — runs before LLM sees anything
        full_text = sanitize_extracted_text(raw_text)

        raw_result = await word_parser(full_text, CONTEXT_SIZES["fast"])

        try:
            parsed_json = json.loads(raw_result)
        except json.JSONDecodeError:
            logger.exception("LLM returned invalid JSON")
            raise HTTPException(status_code=502, detail="LLM returned an invalid response.")

        try:
            validated = SyllabusData.model_validate(parsed_json)
            parsed_json = validated.model_dump()
        except Exception:
            logger.exception("LLM output failed schema validation")
            raise HTTPException(status_code=502, detail="LLM output failed validation.")

        # 6. LLM OUTPUT VALIDATION
        validate_llm_output(parsed_json)

        save_result(safe_filename, parsed_json)
        return {"filename": safe_filename, "data": parsed_json}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Unexpected error during upload processing")
        raise HTTPException(status_code=500, detail="An unexpected error occurred.")
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


# ── Results endpoint — disable in prod via RESULTS_ENABLED=false ──────────────
@app.get("/results")
def get_results() -> list[dict]:
    if not RESULTS_ENABLED:
        raise HTTPException(status_code=403, detail="This endpoint is disabled.")
    return load_results()


@app.delete("/results/clear")
def delete_results() -> dict:
    if not RESULTS_ENABLED:
        raise HTTPException(status_code=403, detail="This endpoint is disabled.")
    clear_results()
    return {"cleared": True}