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

---

## Authentication (added in v3)

Magic-link, no passwords. Console mode is the default for local dev — the link is printed to the API process's stdout.

### Setup

1. **Generate a session secret** and put it in `.env`:
   ```bash
   python -c "import secrets; print('SESSION_SECRET=' + secrets.token_urlsafe(48))" >> .env
   ```
2. **Set frontend origin.** CORS now requires an exact origin (cookies + wildcard CORS are incompatible). If you serve the frontend from `:5500`:
   ```
   FRONTEND_ORIGIN=http://localhost:5500
   ```
   Live Server, http-server, etc. all default to a port — match it here.
3. **Run the new migration:**
   ```bash
   alembic upgrade head
   ```
   This adds `magic_tokens` + `sessions`, the `email_normalized` column, and tightens `syllabi.user_id` to NOT NULL. Pre-auth orphan rows are deleted (they were unreachable after `/results` was removed).
4. **Start the stack** as before:
   ```bash
   uvicorn api:app --reload
   arq worker.WorkerSettings
   ```

### How magic links work in dev

`EMAIL_MODE=console` (the default) skips SMTP entirely. When the user requests a link, the API prints something like:

```
────────────────────────────────────────────────────────────────
[email] To: nav@example.com
[email] http://localhost:8000/auth/verify?token=g7Q...
────────────────────────────────────────────────────────────────
```

Click that URL (or paste it into the browser). The `/auth/verify` route validates the token, mints a session, sets the `syllabus_session` httpOnly cookie, and 303-redirects to `FRONTEND_ORIGIN/?logged_in=1`.

### Switching to real email (prod)

```
EMAIL_MODE=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USER=apikey-or-username
SMTP_PASSWORD=•••
SMTP_FROM=no-reply@yourdomain
SMTP_USE_TLS=true
```

Also flip these for prod:
```
ENVIRONMENT=production    # makes missing SESSION_SECRET a hard boot error
COOKIE_SECURE=true        # cookie only over HTTPS
COOKIE_SAMESITE=strict    # no CSRF surface
```

### Why no CSRF tokens?

In production with `SameSite=strict`, browsers do not attach the session cookie to cross-site requests at all — including form submissions and `fetch()` from other origins. CSRF is unreachable.

In dev with `SameSite=lax`, the cookie is attached only to top-level GET navigation. All state-changing endpoints (`/upload`, `/auth/login`, `/auth/logout`, `DELETE /syllabi/*`, `DELETE /account`) are POST/DELETE, which `lax` does not auto-attach to cross-site. A separate CSRF token system would be redundant at this scope. If you ever add a state-changing GET endpoint, this analysis breaks — don't.

### What's protected

| Route                  | Auth required |
|------------------------|---------------|
| `POST /auth/login`     | no            |
| `GET  /auth/verify`    | no (the token IS the auth) |
| `GET  /auth/me`        | no (returns `{authenticated: false}` when out) |
| `POST /auth/logout`    | no (idempotent) |
| `GET  /privacy`        | no            |
| `POST /upload`         | **yes**       |
| `POST /upload-sync`    | **yes**       |
| `GET  /jobs/{id}`      | **yes**, scoped to owner (404 on cross-user) |
| `GET  /syllabi`        | **yes**       |
| `DELETE /syllabi/{id}` | **yes**, owner-only (404 on cross-user) |
| `DELETE /account`      | **yes**       |

### Removed routes

`GET /results` and `DELETE /results/clear` are gone. The frontend no longer calls them. The "clear data" button now wipes localStorage only — backend deletion goes through `DELETE /syllabi/{id}` (per-card) or `DELETE /account` (everything).

---

## Testing checklist

Run all of this against a fresh `alembic upgrade head` database. Two terminals: API and worker. Frontend served on `FRONTEND_ORIGIN`.

### 1. Request a magic link

```bash
curl -i -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com"}'
```

Expected: `200 OK`, body `{"ok":true,"message":"If that email is valid..."}`.

Watch the **uvicorn terminal** — you should see the printed magic link.

### 2. Use the dev-console magic link

Copy the URL from the uvicorn console and paste into a browser. Expected:
- 303 redirect to `http://localhost:5500/?logged_in=1`
- Toast: "Signed in."
- Header switches from email-input to the email pill + "Log out" + "Delete account".

### 3. Confirm the session cookie exists

DevTools → Application → Cookies → `http://localhost:5500` (or your frontend origin):
- Name: `syllabus_session`
- HttpOnly: ✓
- Secure: ✗ in dev (✓ in prod)
- SameSite: Lax in dev (Strict in prod)

The cookie value is the raw session token. **It must not be readable from JS** — confirm in the Console:
```js
document.cookie
// Should NOT contain "syllabus_session"
```

### 4. Upload while logged in

Drop a PDF. Expected: progress bar advances through phases, course card appears.

Verify the row is scoped to your user:
```bash
psql -U syllabus -d syllabus -c \
  "SELECT id, user_id, filename, created_at FROM syllabi ORDER BY created_at DESC LIMIT 1;"
```
`user_id` must be non-null and match your `users.id`:
```bash
psql -U syllabus -d syllabus -c \
  "SELECT id, email FROM users WHERE email_normalized = 'test@example.com';"
```

### 5. Verify logged-out upload is rejected

In DevTools → Application → Cookies, delete `syllabus_session`. Try to upload again. Expected:
- Toast: "Please sign in first to upload a syllabus."
- File dialog never opens.

Or test the raw endpoint:
```bash
curl -i -X POST http://localhost:8000/upload -F "file=@./sample.pdf"
# 401 {"detail":"Sign in to continue."}
```

### 6. Verify cross-user job leakage is blocked

In one browser (User A), upload a PDF and capture the `job_id` from the network tab. Log out. Sign in as User B (different email). Try to fetch User A's job:
```bash
curl -i -b "syllabus_session=<USER_B_COOKIE>" \
  http://localhost:8000/jobs/<USER_A_JOB_ID>
# 404 {"detail":"Unknown job id."}
```
Same response as a non-existent id — no information leak.

### 7. DELETE /syllabi/{id}

List your syllabi:
```bash
curl -b "syllabus_session=<COOKIE>" http://localhost:8000/syllabi
# [{"id":"...","filename":"...","data":{...},"created_at":"..."}]
```
Delete one:
```bash
curl -i -X DELETE -b "syllabus_session=<COOKIE>" \
  http://localhost:8000/syllabi/<ID>
# 200 {"deleted":true}
```
Try deleting someone else's id (or a made-up UUID):
```bash
curl -i -X DELETE -b "syllabus_session=<COOKIE>" \
  http://localhost:8000/syllabi/00000000-0000-0000-0000-000000000000
# 404 {"detail":"Not found."}
```

### 8. DELETE /account

```bash
curl -i -X DELETE -b "syllabus_session=<COOKIE>" \
  http://localhost:8000/account
# 200 {"deleted":true}
# Set-Cookie: syllabus_session=""; ... (cookie cleared)
```
Verify the database is empty for that user:
```bash
psql -U syllabus -d syllabus -c \
  "SELECT COUNT(*) FROM users WHERE email_normalized = 'test@example.com';"
# 0

psql -U syllabus -d syllabus -c \
  "SELECT COUNT(*) FROM sessions, magic_tokens, syllabi;"
# All zero (assuming this was the only user)
```
Subsequent `/auth/me` returns `{"authenticated": false}`.

### 9. Logout

```bash
curl -i -X POST -b "syllabus_session=<COOKIE>" \
  http://localhost:8000/auth/logout
# 200 {"ok":true}
# Set-Cookie clears the session cookie

# The session row is gone from the DB:
psql -U syllabus -d syllabus -c "SELECT COUNT(*) FROM sessions;"
```

In the UI: clicking "Log out" toasts "Logged out.", clears localStorage, and reloads the page in the logged-out state.

### 10. Verify old /results endpoints are gone

```bash
curl -i http://localhost:8000/results
# 404 Not Found

curl -i -X DELETE http://localhost:8000/results/clear
# 405 Method Not Allowed (or 404; either is fine — both confirm absence)
```

### 11. Verify magic-link single-use + expiry

Use a magic link once — it works. Click the same link again:
```
400 {"detail":"Invalid or expired link."}
```
For expiry: lower `MAGIC_LINK_TTL_MINUTES=1` in `.env`, restart, request a link, wait 90 seconds, click. Expect the same 400.

### 12. Verify rate limiting

```bash
for i in $(seq 1 6); do
  curl -s -o /dev/null -w "%{http_code}\n" -X POST \
    http://localhost:8000/auth/login \
    -H "Content-Type: application/json" \
    -d '{"email":"test@example.com"}'
done
# 200 200 200 200 200 429
```

### 13. Verify enumeration resistance

Request a magic link for an email that has never registered:
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"never-seen@example.com"}'
# 200 {"ok":true,"message":"If that email is valid, a sign-in link is on its way."}
```
Identical response to a registered email. The user IS auto-created (visible in the `users` table), but the API surface gives no signal.

### 14. Privacy page

```bash
curl http://localhost:8000/privacy | head -30
```
Expected: HTML page rendering the privacy policy. The footer link in the app opens the same page.