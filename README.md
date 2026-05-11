# Sylva

Drop a syllabus PDF, get a structured dashboard with all your deadlines,
grade weights, a calendar, and a "what-if" grade calculator.

**[Live demo →](https://sylva-9wn.pages.dev)**

---

## What it does

You upload a PDF. Sylva extracts everything — instructor, meeting times,
every assessment with its weight and date, the weekly schedule, course
policies — and turns it into a clean dashboard. Pie chart of grade
weights, calendar of every deadline, and a calculator that tells you
what scores you need on remaining work to hit any target grade.

Takes about 10–15 seconds per PDF.

---

## Stack

Frontend is vanilla HTML/CSS/JS with Chart.js and FullCalendar, hosted on
**Cloudflare Pages**.

Backend is **FastAPI** on **Railway**, Postgres on **Neon**, Redis on
**Upstash**. All four sit on their respective free tiers.

For parsing: **Mistral OCR** turns the PDF into clean markdown, then
**Gemini 2.5 Flash** reads the markdown and returns structured JSON
matching a schema.

For auth: magic-link email via **Resend**. No passwords.

---

## How it works

```
Browser
  │
  │  POST /upload-sync (multipart PDF, ~10–15s)
  ▼
FastAPI ─── validates file (size, page count, encryption)
  │     ─── Mistral OCR     → markdown
  │     ─── Gemini           → structured JSON
  │     ─── Pydantic schema  → reject hallucinations
  │     ─── Postgres         → persist if signed in
  ▼
Dashboard data returned to the browser
```

An earlier version used a separate background worker and a job queue,
because Docling + a self-hosted Ollama model took 30–90 seconds per
upload. That version still lives on the [`local`](https://github.com/Navidmznn/Sylva/tree/local)
branch — it runs entirely on your own machine with zero external API
calls. The `main` branch swaps both for hosted APIs so it fits on
free-tier hosting.

---

## Things worth pointing out

**No raw tokens in the database.** Magic-link tokens and session
cookies are both HMAC-hashed before they hit Postgres. A full DB read
leak can't be used to sign in unless `SESSION_SECRET` also leaks.

**Prompt injection defence.** The syllabus text is wrapped in
`<untrusted_syllabus_text>` tags before it reaches the LLM, and the
system prompt explicitly tells the model to ignore any directives
inside those tags. The API also strips known injection patterns before
the text gets there.

**Owner-scoped 404s.** Cross-user access to someone else's syllabus
returns `404`, not `403` — the existence of another user's data is
never disclosed.

**Redis-backed rate limiting.** Limits live in Redis (not in-process),
so they survive restarts and are shared across processes. Auth endpoints
are capped at 5/minute and 20/hour per IP.

---

## Running it locally

The `local` branch is the original self-hosted setup: Docling for OCR,
Ollama for the LLM, no external APIs. Slower (30–90s per PDF) but
offline-capable and free forever.

```bash
git clone https://github.com/Navidmznn/Sylva.git
cd Sylva
git checkout local
docker compose up -d   # Postgres + Redis
ollama pull qwen3:8b   # ~5 GB
```

For the `main` branch (the deployed version), you'd need a
`backend/.env` with API keys:

```
MISTRAL_API_KEY=...
GEMINI_API_KEY=...
RESEND_API_KEY=...   # optional, magic-link emails
SESSION_SECRET=...   # any random string, prod requires it
```

Plus Postgres and Redis reachable from wherever you run it.

---

## Status

- Magic-link emails currently use Resend's testing mode, which only
  delivers to my own address. Verifying a real domain is on the todo
  list.
- Still on Cloudflare's `pages.dev` subdomain — custom domain might
  come later.
- No automated test suite yet.

---

## License

MIT
