"""Privacy policy text + a minimal markdown renderer. Keep this in sync with
the actual data flow — if you swap Ollama for an external API or start
retaining raw PDFs, update the policy in the same change."""
from __future__ import annotations

PRIVACY_MARKDOWN = """\
# Privacy Policy

Last updated: 2026-04-26

This service ("syllabus.ai") parses university course syllabi you upload and
visualizes the extracted information. This page describes exactly what data
is stored, why, and how to remove it.

## What is stored

* **Your email address.** Used as the sole identifier for your account.
* **Sign-in tokens** (magic-link tokens and session tokens), stored only as
  HMAC-SHA-256 hashes — the raw tokens are never persisted server-side.
  Magic tokens are single-use; sessions live in an httpOnly cookie.
* **Parsed syllabus data.** When you upload a PDF, the extracted course
  information (title, code, instructor, assessments, schedule, weights) is
  saved as structured JSON associated with your account. The original PDF
  is **not** retained — it is deleted from temporary storage after extraction.
* **Filenames** of uploaded PDFs (so you can identify your saved syllabi).
* **Browser localStorage:** the same parsed JSON is also cached in your
  browser so the UI can render instantly when you reload. Nothing else
  about you is kept in localStorage.
* **IP-derived rate-limit counters** (in Redis, ~1 hour TTL) used to throttle
  abuse on `/upload` and `/auth/login`. Not associated with your account.

## What is NOT stored

* Passwords (there are none — sign-in is magic-link only).
* The raw PDF you upload.
* Any data sent to third-party AI providers — extraction runs through a
  **local Ollama model**. Your PDF contents do not leave the host this
  service runs on.

## Why each item is stored

* Email — to send sign-in links and identify your saved syllabi.
* Magic-token / session hashes — to authenticate you securely.
* Parsed syllabus JSON — that is the product; without it the UI has nothing
  to display.
* Filenames — to label saved syllabi in your list.
* Rate-limit counters — to prevent abuse.

## How long data is kept

* **Sessions:** up to 30 days from sign-in, then auto-expire. Logging out
  ends the session immediately.
* **Magic-link tokens:** 15 minutes; deleted on first use.
* **Syllabus JSON:** kept indefinitely until you delete it (or your account).
* **Rate-limit counters:** about 1 hour.
* **Account row:** kept until you trigger account deletion.

## How to delete a single syllabus

In the app, open a course card and use the **Delete** button. This calls
`DELETE /syllabi/{id}`, which removes only that syllabus from your account.
Backend deletion is irreversible.

## How to delete your account

In the app's account menu, choose **Delete account**. This calls
`DELETE /account`, which:

1. Deletes all your syllabi.
2. Revokes all your active sessions and magic tokens.
3. Deletes your user row.
4. Clears your session cookie.

Account deletion is irreversible and immediate.

## How to clear browser-side data only

The **Clear browser data** button in the app removes the cached parsed
syllabi from your browser's localStorage. It does not touch the backend.
Use **Delete account** above to remove backend data.

## PDF processing

Uploaded PDFs are written to a temporary file, parsed by Docling for text
and table extraction, scored and pruned, then sent to a **locally running
Ollama model** for structured extraction. The temp file is deleted in the
worker's `finally` block whether extraction succeeds or fails.

## Contact

This is a self-hosted demo. If you are running it for someone else, fill in
contact details here. If you are running it for yourself, that's you.
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