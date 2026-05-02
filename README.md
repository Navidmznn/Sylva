# Sylva

Upload a university syllabus PDF. Get structured assignments, deadlines,
grade weights, a calendar view, and a what-if grade calculator — all parsed
locally with a self-hosted LLM. No third-party AI API. No data leaves your
machine.

> **Demo:** [YouTube ↗](#) &nbsp;|&nbsp; **Status:** Working locally, not yet
> publicly deployed. See [Status & known limitations](#status--known-limitations).

---

## What it does

1. You drag a course syllabus PDF onto the upload zone.
2. The backend extracts the raw text with **Docling**, scores and prunes the
   blocks, then sends the result to a local **Ollama** model (`qwen3:8b`)
   with a structured-output prompt.
3. The model returns JSON. The backend validates it against a **Pydantic**
   schema and stores it in **Postgres**.
4. The frontend polls a job-status endpoint every 2 s, driving a real progress
   bar through the pipeline phases (`extracting → scoring → parsing → validating`).
5. On completion, the course card renders: assessment breakdown (Chart.js
   donut), calendar of deadlines, and an interactive grade calculator.

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML / CSS / JS, Chart.js |
| Backend | FastAPI (Python 3.12), async SQLAlchemy |
| Database | PostgreSQL 16 + Alembic migrations |
| Job queue | arq + Redis 7 |
| Auth | Magic-link, HMAC-SHA-256 session tokens, httpOnly cookies |
| PDF extraction | Docling |
| LLM inference | Ollama (`qwen3:8b`) — fully local |
| Dev infra | Docker Compose (Postgres + Redis) |

---

## Architecture

```
Browser
  │
  │  POST /upload (multipart PDF)
  ▼
FastAPI ──── validates file (type, size, page count, encryption check)
  │          writes PDF to UPLOAD_TMPDIR
  │          enqueues arq job
  │          returns {job_id}
  │
  │  GET /jobs/{id}  (polled every 2 s)
  │
arq Worker
  ├── Docling          → extract text blocks from PDF
  ├── scorer.py        → score + prune irrelevant blocks
  ├── parser.py        → build prompt, call Ollama /api/generate
  ├── Pydantic         → validate model output, reject hallucinations
  └── Postgres         → persist result under authenticated user
```

Job state (phase + percent) lives in Redis as a JSON blob. The API reads it
on every poll and streams it to the browser — the progress bar shows real
pipeline progress, not a CSS animation.

---

## Technical highlights

**Job queue architecture.** Docling + Ollama on CPU takes 30–90 seconds per
syllabus. Running that inside a request thread would block uvicorn. Instead,
`POST /upload` validates, writes to a temp file, and enqueues. The arq worker
consumes the job and writes progress back to Redis. The frontend polls
`GET /jobs/{id}` until `status === "complete"`.

**HMAC-hashed session tokens.** The database never stores raw magic-link or
session tokens — only an `HMAC-SHA-256(token, SESSION_SECRET)` digest. A
full database read leak cannot be used to log in; the attacker would also
need `SESSION_SECRET`. Rotating the secret invalidates all live sessions
immediately.

**Owner-scoped 404s.** Cross-user access to `/jobs/{id}` and
`/syllabi/{id}` returns `404`, not `403`. The existence of another user's
resource is not revealed.

**Redis-backed rate limiting.** `slowapi` uses Redis as its storage backend,
so limits survive multi-worker uvicorn restarts and are shared across
processes. Auth endpoints are double-limited: `5/minute` and `20/hour`.

**Prompt injection defence.** Syllabus text is wrapped in
`<untrusted_syllabus_text>` tags and the system prompt explicitly instructs
the model to ignore any directives found inside. The API layer also strips
known injection patterns before the text reaches the model.

**Sync fallback as a parity oracle.** `/upload-sync` runs the full pipeline
synchronously in-request. During the SQLite → Postgres refactor it served as
a byte-for-byte comparison point to confirm the refactor hadn't changed
extraction behaviour. Disabled in production via `UPLOAD_SYNC_ENABLED=false`.

---

## Quickstart

### Prerequisites

| Tool | Version | Notes |
|---|---|---|
| Python | 3.11 + | 3.12 recommended |
| Docker Desktop | 20 + | Runs Postgres + Redis. No manual DB install needed |
| Ollama | latest | Runs natively on macOS / Linux / Windows. **No WSL required** |

### 1. Clone

```bash
git clone https://github.com/Navidmznn/Course_helper.git
cd Course_helper
```

### 2. Start Postgres + Redis

```bash
docker compose up -d

# Wait until both services show "healthy":
docker compose ps
```

### 3. Pull the Ollama model

```bash
ollama pull qwen3:8b     # ~5 GB, one-time download
```

This is the model name hardcoded in `backend/constants.py`. The worker will
fail with a 404 from Ollama if this model isn't present.

### 4. Set up the Python environment

**macOS / Linux:**
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install docling torch
```

**Windows (PowerShell):**
```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install docling torch
```

`docling` and `torch` are required. They're not in `requirements.txt` because
torch wheel selection depends on your hardware (CPU vs CUDA). If the install
fails on Windows, install torch first:

```powershell
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install docling
```

### 5. Configure environment

```bash
cp .env.example .env
```

Then generate a session secret and append it:

**macOS / Linux:**
```bash
python -c "import secrets; print('SESSION_SECRET=' + secrets.token_urlsafe(48))" >> .env
```

**Windows (PowerShell):**
```powershell
python -c "import secrets; print('SESSION_SECRET=' + secrets.token_urlsafe(48))" | Add-Content .env
```

The defaults in `.env.example` work for local development. The only value
you must set manually is `SESSION_SECRET` (above) and `FRONTEND_ORIGIN`
if you serve the frontend on a port other than `3000`.

> **`FRONTEND_ORIGIN` must exactly match the URL in your browser's address
> bar.** `http://localhost:3000` and `http://127.0.0.1:3000` are different
> origins. A mismatch causes CORS errors on every request.

### 6. Load environment variables

**macOS / Linux:**
```bash
set -a; source .env; set +a
```

**Windows (PowerShell):**
```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#]' } | ForEach-Object {
    $k, $v = $_ -split '=', 2
    [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
}
```

Or install `python-dotenv` and let uvicorn load it automatically — either works.

### 7. Run database migrations

```bash
# Still inside backend/ with .venv active
alembic upgrade head
```

This creates `users`, `syllabi`, `magic_tokens`, and `sessions` tables.
Postgres must be healthy (step 2) before this runs.

### 8. Start everything

You need four terminals. All backend commands run from `backend/` with the
venv active.

| Terminal | Directory | Command |
|---|---|---|
| 1 — API | `backend/` | `uvicorn api:app --reload --host 0.0.0.0 --port 8000` |
| 2 — Worker | `backend/` | `arq worker.WorkerSettings` |
| 3 — Ollama | anywhere | `ollama serve` (skip if already running as a system service) |
| 4 — Frontend | `frontend/` | `python -m http.server 3000` |

### 9. Open the app

1. Go to `http://localhost:3000`.
2. Enter any email and click **Sign in**.
3. Watch **Terminal 1 (uvicorn)** for the magic link — it prints there, not in the browser.
4. Click the `http://localhost:8000/auth/verify?token=...` URL **in the same
   browser** you have the app open in.
5. You'll be redirected to `http://localhost:3000/?logged_in=1`.
6. Drag a PDF syllabus onto the upload zone.

---

## Environment variables

| Variable | Default | Required | Purpose |
|---|---|---|---|
| `SESSION_SECRET` | random ephemeral | **Yes (prod)** | HMAC key for all tokens. Rotating it invalidates all sessions |
| `FRONTEND_ORIGIN` | `http://localhost:5500` | **Yes** | CORS allowed origin + post-login redirect target |
| `DATABASE_URL` | `postgresql+asyncpg://syllabus:syllabus@localhost:5432/syllabus` | Yes | Postgres connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Yes | Redis (job queue + rate limiting) |
| `BACKEND_BASE_URL` | `http://localhost:8000` | Yes | Used to build magic-link URLs. Change if behind a reverse proxy |
| `EMAIL_MODE` | `console` | No | `console` prints links to stdout; `smtp` sends real email |
| `ENVIRONMENT` | `development` | No | Set to `production` to make missing `SESSION_SECRET` a hard boot error |
| `COOKIE_SECURE` | `false` | No | Set `true` in production (HTTPS only) |
| `COOKIE_SAMESITE` | `lax` | No | Set `strict` in production |
| `UPLOAD_SYNC_ENABLED` | `true` | No | Set `false` in production to disable `/upload-sync` |
| `UPLOAD_TMPDIR` | system temp dir | No | Where the API stages PDFs for the worker. Must be a shared path on multi-host |
| `MAGIC_LINK_TTL_MINUTES` | `15` | No | Magic-link expiry |
| `SESSION_TTL_DAYS` | `30` | No | Session cookie lifetime |
| `DOCLING_TIMEOUT_SECONDS` | `500` | No | Hard timeout for the Docling extraction step |
| `JOB_STATE_TTL_SECONDS` | `86400` | No | How long Redis retains job state after completion |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM/USE_TLS` | (empty) | No | Only required when `EMAIL_MODE=smtp` |

---

## API reference

### Auth routes

| Method | Route | Auth | Description |
|---|---|---|---|
| `POST` | `/auth/login` | No | Request a magic link. Always returns `200` regardless of whether the email exists (enumeration resistance) |
| `GET` | `/auth/verify?token=...` | No | Validate token, mint session, set httpOnly cookie, redirect to `FRONTEND_ORIGIN` |
| `GET` | `/auth/me` | No | Returns `{authenticated: false}` when logged out |
| `POST` | `/auth/logout` | No | Revokes session, clears cookie |

### Protected routes

| Method | Route | Description |
|---|---|---|
| `POST` | `/upload` | Enqueue a PDF parse job. Returns `{job_id}` |
| `GET` | `/jobs/{id}` | Poll job state. Returns `404` for other users' jobs (no cross-user leakage) |
| `GET` | `/syllabi` | List the authenticated user's parsed syllabi |
| `DELETE` | `/syllabi/{id}` | Delete one syllabus. Returns `404` for other users' IDs |
| `DELETE` | `/account` | Delete the authenticated user and all their data |
| `POST` | `/upload-sync` | Synchronous pipeline (dev/testing). Disable in prod |

---

## Security design

**No passwords.** Magic-link only. Users can't set a password that gets
breached.

**HMAC-stored tokens.** Raw tokens are never written to the database.
Only `HMAC-SHA-256(token, SESSION_SECRET)` is stored. A full DB dump
cannot be used to authenticate.

**SameSite cookies.** In development: `SameSite=Lax`. In production:
`SameSite=Strict`. With `Strict`, the browser does not attach the session
cookie to any cross-site request — CSRF is structurally unreachable without
a separate token.

**Prompt injection resistance.** Syllabus text (untrusted user content) is
wrapped in `<untrusted_syllabus_text>` tags. The system prompt instructs the
model to ignore directives found inside those tags. The API also strips lines
matching known injection patterns before they reach the model.

**Rate limiting.** `POST /auth/login` is capped at `5/minute` and `20/hour`
per IP. Rate-limit counters live in Redis, not process memory, so they survive
uvicorn restarts and are shared across workers.

---

## Development notes

### Generating future migrations

```bash
# After editing backend/db_models.py:
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

Always inspect the generated file before running upgrade. Alembic autogenerate
misses server-side defaults and JSONB indexes.

### Useful Redis introspection

```bash
redis-cli keys 'job:*'          # all tracked jobs
redis-cli get  'job:<id>'       # raw state JSON for one job
redis-cli keys 'active_jobs:*'  # per-IP concurrency slots
redis-cli keys 'arq:*'          # arq's internal queue keys
```

### Failure-mode behaviour

| Scenario | Expected |
|---|---|
| Worker not running | `/upload` returns `{job_id}`. `/jobs/{id}` stays `queued` forever |
| Encrypted PDF | `/upload` rejects `422` before touching the queue |
| PDF > 20 MB | `/upload` rejects `413` mid-stream |
| Two uploads from same IP | Second returns `429 "already processing"` |
| Postgres down | Worker logs a commit error and sets job state to `failed` |
| Ollama not running | Worker catches `ConnectError`, sets job state to `failed` |

### Testing the sync fallback

`/upload-sync` runs the full pipeline synchronously and returns the same JSON
shape as a completed job. Use it to verify the async path produces identical
output:

```bash
curl -F "file=@./sample.pdf" \
  -b "syllabus_session=<token>" \
  http://localhost:8000/upload-sync
```

---

## Status & known limitations

- **Not publicly deployed.** The app runs fully on `localhost`. Deployment
  requires a GPU host (or slow CPU inference), SMTP credentials, and a domain.
  A recorded demo is provided instead.
- **Single-host architecture.** The API and worker share `UPLOAD_TMPDIR` on
  the local filesystem. Multi-host deployment would require shared storage
  (S3, NFS) or passing an object URL through the queue instead of a file path.
- **Local LLM only.** Ollama is not horizontally scalable without a dedicated
  inference host. Swapping to a hosted model would be a one-line change in
  `constants.py` + `worker.py`.
- **Parsing speed.** Docling + Ollama `qwen3:8b` on CPU takes 30–90 seconds
  per syllabus depending on page count and hardware. GPU (CUDA) cuts this
  significantly.
- **No test suite yet.** Manual testing checklist is in
  [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md).
- **Rate limiting assumes direct client IPs.** `slowapi.util.get_remote_address`
  reads `request.client.host` — the immediate TCP peer. In dev that's the user.
  Behind nginx/Cloudflare in prod, that's the proxy, and all users share one
  rate-limit bucket. Before deploying, swap the key function for one that
  reads `X-Forwarded-For` only when the request comes from a trusted proxy
  IP, or run uvicorn with `--proxy-headers --forwarded-allow-ips=...`.
- **Magic links require console access in dev.** With `EMAIL_MODE=console`,
  the sign-in link prints to the uvicorn terminal. Production needs SMTP
  credentials.

---

## License

MIT
