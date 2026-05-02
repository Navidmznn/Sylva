"""Privacy policy text + a minimal markdown renderer. Keep this in sync with
the actual data flow — if you swap Ollama for an external API or start
retaining raw PDFs, update the policy in the same change."""
from __future__ import annotations

PRIVACY_MARKDOWN = """\
# Privacy Policy

Last updated: 2026-04-26

syllabus.ai parses course syllabi you upload and turns them into a structured
dashboard. This page covers what gets stored and how to remove it.

## What is stored

* **Your email address.** Used to send sign-in links and tie saved syllabi to
  your account. Nothing else.
* **Sign-in and session tokens**, stored as HMAC-SHA-256 hashes only. The
  raw token is never written to the database. Magic-link tokens are
  single-use and expire after 15 minutes. Sessions live in an httpOnly cookie.
* **Parsed syllabus data.** When you upload a PDF, the extracted course
  information (title, code, instructor, assessments, schedule, grade weights)
  is saved as JSON on the server. The original PDF is deleted immediately
  after extraction and is never retained.
* **The filename** of each uploaded PDF, so your saved syllabi have a readable
  label.
* **A local browser cache** of the same parsed JSON, so the dashboard loads
  instantly on revisit. Clearing your browser data removes this; it has no
  effect on what's stored on the server.
* **Short-lived rate-limit counters** tied to your IP address, kept in Redis
  for roughly an hour. These are used to limit abuse on the upload and login
  endpoints and are not linked to your account in any way.

## What is NOT stored

* Passwords. There are none. Sign-in is magic-link only.
* The PDF itself. It is deleted after the extraction step finishes.
* Anything sent to a third-party AI service. All inference runs through a
  **local Ollama model** on the same machine as the app. Your syllabus
  contents never leave that host.

## Why things are kept

Your email is needed to send sign-in links and to scope your data so only
you can see it. The token hashes are needed to authenticate you without
storing anything that could be replayed if the database were ever read by
someone else. The parsed JSON is the whole point of the app. Filenames are
kept purely for display. Rate-limit counters exist to stop someone from
hammering the upload endpoint.

## How long data is kept

* **Sessions** expire 30 days after sign-in. Logging out ends the session
  right away.
* **Magic-link tokens** expire after 15 minutes and are invalidated on first
  use.
* **Parsed syllabus JSON** is kept until you delete it or close your account.
* **Rate-limit counters** expire after about an hour.

## Deleting a single syllabus

Open the course card in the app and click **Delete**. This removes that
syllabus from the server. It cannot be undone.

## Deleting your account

Choose **Delete account** from the account menu. This permanently deletes all
your saved syllabi, revokes every active session and magic token, and removes
your account. Your session cookie is cleared at the same time. There is no
recovery after this.

## Clearing only the browser cache

The **Clear browser data** button removes the locally cached copy of your
syllabi from this browser. It does not touch the server. Use **Delete account**
if you want to remove your data from the backend as well.

## How PDF processing works

When you upload a file, it is written to a temporary location on disk and
handed off to a background worker. The worker runs text and table extraction
with Docling, scores and prunes the output to fit the model's context window,
then calls a locally running Ollama model to produce structured JSON. Once
extraction finishes, whether it succeeds or fails, the temp file is deleted.
The structured result is validated against a schema before anything gets saved.

## Contact

This is a self-hosted project. If you are running it for others, add your
contact details here.
"""


def render_privacy_html() -> str:
    """Render the policy as a self-contained HTML page. Tiny inline parser —
    no markdown library for one page. Handles H1/H2, paragraphs, bullets,
    bold (**), and inline code (backticks)."""
    import html
    import re

    lines = PRIVACY_MARKDOWN.splitlines()
    out: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    def inline(text: str) -> str:
        text = html.escape(text)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        return text

    for raw in lines:
        line = raw.rstrip()
        if not line:
            close_list()
            continue
        if line.startswith("# "):
            close_list()
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("## "):
            close_list()
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("* "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
        else:
            close_list()
            out.append(f"<p>{inline(line)}</p>")
    close_list()

    body = "\n".join(out)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Privacy Policy — syllabus.ai</title>
  <style>
    body {{
      max-width: 720px;
      margin: 48px auto;
      padding: 0 24px 64px;
      font-family: 'DM Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      color: #3D3D3D;
      background: #FDF8F3;
      line-height: 1.6;
    }}
    h1 {{ font-family: 'Caveat', cursive; font-size: 42px; margin-bottom: 8px; }}
    h2 {{ font-size: 20px; margin-top: 32px; color: #6B9A7A; }}
    code {{ background: #F5EDE4; padding: 1px 6px; border-radius: 4px; font-size: 0.92em; }}
    ul  {{ padding-left: 22px; }}
    li  {{ margin: 4px 0; }}
    a   {{ color: #6B9A7A; }}
  </style>
</head>
<body>
{body}
</body>
</html>"""