# syllabus.ai — backend (job-queue architecture)

## What changed from the previous SQLite + synchronous `/upload`

| Concern              | Before                              | After                                                  |
|----------------------|-------------------------------------|--------------------------------------------------------|
| Database             | SQLite (`results.db`)               | Postgres via SQLAlchemy + alembic                      |
| Upload behaviour     | Single request did everything       | `/upload` enqueues; worker does heavy lifting          |
| Progress feedback    | Cosmetic CSS animation              | Real `/jobs/{id}` polling, percent + phase             |
| Rate-limit storage   | In-process memory                   | Redis (shared across uvicorn workers)                  |
| Active-job slots     | `defaultdict` + `asyncio.Lock`      | Redis INCR/DECR with safety TTL                        |
| Job runtime          | Inside the request                  | `arq` worker process                                   |
| Fallback path        | n/a                                 | `POST /upload-sync` (toggle with `UPLOAD_SYNC_ENABLED`)|

The on-the-wire shape `{"filename": ..., "data": {...}}` is preserved. The
frontend's persistence layer, course/chart/calendar/grade-calc rendering, and
all schemas (`SyllabusData`, `Course`, `Assessment`, …) are untouched.

---

## File-by-file

### New
- **`db.py`** — async SQLAlchemy engine + session factory; sync engine for alembic.
- **`db_models.py`** — `User` (placeholder, fields will expand with auth) and `Syllabus` (replaces the SQLite `results` table).
- **`redis_client.py`** — single shared async Redis pool used by `api.py`, `worker.py`, and (via `storage_uri`) slowapi.
- **`jobs.py`** — schema + helpers for the JSON job-state blob at `job:<id>`.
- **`worker.py`** — arq worker. Runs the same Docling → score → prune → Ollama → validate pipeline that was inside `/upload` before.
- **`alembic.ini`, `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/0001_initial.py`** — migration setup + initial migration.
- **`docker-compose.yml`** — Postgres + Redis for local dev.
- **`requirements.txt`, `.env.example`** — dependency + config docs.

### Modified
- **`api.py`** — split into validation (sync) + enqueue (async). Adds `/jobs/{id}` and `/upload-sync`. Postgres-backed `/results` and `/results/clear`. Redis-backed slowapi + active-job slots.
- **`app.js`** — POST `/upload`, then poll `/jobs/{id}` every 2 s. Drives the loading bar from real progress.
- **`style.css`** — disables the cosmetic infinite-loop progress animation when JS-driven (`.loading-bar-fill.is-driven`).

### Untouched
`extractor.py`, `scorer.py`, `parser.py`, `models.py`, `block.py`, `constants.py`, `index.html`, and every other JS module. The extraction pipeline is called from a new place but its code is unchanged.

---

## Setup (first time)

### 1. Bring up Postgres + Redis

```bash
docker compose up -d
```

Wait until both services are healthy:

```bash
docker compose ps
```

### 2. Install Python deps

```bash
python -m venv .venv
source .venv/bin/activate                # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# Plus your existing extraction deps (only if not already installed):
# pip install docling torch
```

### 3. Configure env

```bash
cp .env.example .env
# Edit .env if you want non-default Postgres/Redis URLs.
```

Then export it for your shell (or use `python-dotenv`/your shell loader):

```bash
set -a; source .env; set +a              # bash/zsh
```

### 4. Run migrations

```bash
alembic upgrade head
```

This creates the `users` and `syllabi` tables.

---

## Running (every time)

You need three processes. Open three terminals (or use `tmux`/`overmind`/etc.):

### Terminal 1 — FastAPI

```bash
uvicorn api:app --reload --host 0.0.0.0 --port 8000
```

### Terminal 2 — arq worker

```bash
arq worker.WorkerSettings
```

### Terminal 3 — Ollama (if not already running)

```bash
ollama serve
```

The frontend (`index.html` + the JS modules) can be opened directly or served from any static host on `:5500`/`:5173`/etc. as before.

---

## Testing the new flow

### Happy path (frontend)

1. Open the app.
2. Upload a PDF.
3. You should see the loading modal appear, with **the bar advancing in real steps** as the worker moves through `extracting → scoring → parsing → validating`. The subtitle reads the worker's phase label.
4. On completion, the assessment breakdown / calendar / grade calc all populate as before.

### Happy path (curl)

```bash
# 1. Enqueue
curl -F "file=@./sample.pdf" http://localhost:8000/upload
# {"job_id": "ab12...", "filename": "sample.pdf"}

# 2. Poll
watch -n 2 'curl -s http://localhost:8000/jobs/ab12...'
# Returns {"status":"running","progress":15,"phase":"Reading your PDF...","result":null,"error":null,...}
# until status flips to "complete" with result populated.
```

### Fallback / parity check

The synchronous path is preserved at `/upload-sync`:

```bash
curl -F "file=@./sample.pdf" http://localhost:8000/upload-sync
# Returns the same {"filename": ..., "data": {...}} shape the v1 /upload did.
```

This route is the canonical comparison point for "did the refactor change behaviour?" — its output is byte-for-byte the v1 contract. Disable in production via `UPLOAD_SYNC_ENABLED=false`.

### Failure-mode smoke tests

| Scenario                              | Expected                                                              |
|---------------------------------------|-----------------------------------------------------------------------|
| Worker not running                    | `/upload` returns `{job_id}`. `/jobs/{id}` stays in `queued` forever. |
| Encrypted PDF                         | `/upload` rejects with 422 — never reaches the queue.                 |
| 21 MB PDF                             | `/upload` rejects with 413 mid-stream.                                |
| Two concurrent uploads from same IP   | Second one returns 429 "already processing".                          |
| Postgres down                         | Job runs but worker logs a commit error and writes `failed` state.    |

### Useful Redis introspection

```bash
redis-cli keys 'job:*'                   # list all tracked jobs
redis-cli get  'job:<id>'                # raw state JSON
redis-cli keys 'active_jobs:*'           # see who's holding a slot
redis-cli keys 'arq:*'                   # arq's internal queue keys
```

---

## Generating future migrations

After editing `db_models.py`:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

Always inspect the generated file before running upgrade — autogenerate misses things like server-side defaults and JSONB indexes.

---

## Production caveats

1. **Shared filesystem requirement.** `/upload` writes the PDF to `UPLOAD_TMPDIR` and the worker reads from the same path. Single host: `/tmp` is fine. Multi-host: mount a shared volume (NFS/EFS) and point both processes' `UPLOAD_TMPDIR` there, or change the contract so the API uploads to object storage and passes a URL to the worker.
2. **Disable `/upload-sync`.** Set `UPLOAD_SYNC_ENABLED=false`. The route is intentionally not behind any auth.
3. **Active-job slot leak.** The slot-release path runs in `/jobs/{id}` once the job is terminal. If a client never polls again, the slot expires after `ACTIVE_JOB_TTL_SECONDS` (30 min). For a public deployment, lower that TTL.
4. **Secrets.** Don't commit `.env`. The `DATABASE_URL` shipped here is `syllabus:syllabus` for local dev only.