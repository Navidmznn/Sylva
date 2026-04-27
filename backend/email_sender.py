"""
email_sender.py — async email abstraction.

Two modes selected via EMAIL_MODE:
  * console — prints the magic link to stdout. The default for local dev so
              you don't need an SMTP account to test the flow end-to-end.
  * smtp    — sends via stdlib smtplib (TLS optional), executed on a
              threadpool because smtplib is sync.

Choosing stdlib over aiosmtplib keeps requirements.txt unchanged. Email
sending is not on a hot path, so the threadpool detour is negligible.
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage


logger = logging.getLogger(__name__)

EMAIL_MODE: str = os.environ.get("EMAIL_MODE", "console").lower()
SMTP_HOST: str = os.environ.get("SMTP_HOST", "")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER: str = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM: str = os.environ.get("SMTP_FROM", "no-reply@syllabus.local")
SMTP_USE_TLS: bool = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"


def _send_smtp_blocking(to_email: str, subject: str, body: str) -> None:
    """Synchronous SMTP send. Runs inside asyncio.to_thread."""
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if SMTP_USE_TLS:
        # STARTTLS upgrade (port 587 typical).
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        # Implicit TLS (port 465) — uncommon but supported.
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15,
                              context=ssl.create_default_context()) as smtp:
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)


async def send_magic_link_email(to_email: str, link: str) -> None:
    """Send the magic link (or print it, in console mode)."""
    subject = "Your syllabus.ai sign-in link"
    body = (
        "Hi,\n\n"
        "Click the link below to sign in to syllabus.ai. The link is single-use\n"
        "and will expire shortly.\n\n"
        f"{link}\n\n"
        "If you didn't request this, you can safely ignore this email.\n"
    )

    if EMAIL_MODE == "console" or not SMTP_HOST:
        # Print rather than log — easier to spot in dev terminals, and also
        # logged at INFO so it shows up in structured log capture.
        banner = "─" * 64
        print(f"\n{banner}\n[email] To: {to_email}\n[email] {link}\n{banner}\n", flush=True)
        logger.info("Magic link for %s: %s", to_email, link)
        return

    try:
        await asyncio.to_thread(_send_smtp_blocking, to_email, subject, body)
        logger.info("Magic link sent to %s via SMTP", to_email)
    except Exception:
        # Don't surface SMTP errors to the client — that would let an attacker
        # learn whether SMTP is misconfigured by triggering /auth/login. Log
        # and silently succeed; the user just won't get an email.
        logger.exception("SMTP send failed for %s", to_email)