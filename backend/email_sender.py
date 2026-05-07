"""Email helper — Resend HTTP API for prod, console for dev."""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

import httpx


logger = logging.getLogger(__name__)

EMAIL_MODE: str = os.environ.get("EMAIL_MODE", "console").lower()

RESEND_API_KEY: str = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM: str = os.environ.get("RESEND_FROM", "onboarding@resend.dev")

SMTP_HOST: str = os.environ.get("SMTP_HOST", "")
SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER: str = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM: str = os.environ.get("SMTP_FROM", "no-reply@sylva.local")
SMTP_USE_TLS: bool = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"


async def _send_resend(to_email: str, subject: str, body: str) -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": RESEND_FROM,
                "to": [to_email],
                "subject": subject,
                "text": body,
            },
        )
        response.raise_for_status()


def _send_smtp_blocking(to_email: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    if SMTP_USE_TLS:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15,
                              context=ssl.create_default_context()) as smtp:
            if SMTP_USER:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg)


async def send_magic_link_email(to_email: str, link: str) -> None:
    subject = "Your Sylva sign-in link"
    body = (
        "Hi,\n\n"
        "Click the link below to sign in to Sylva. The link is single-use\n"
        "and will expire shortly.\n\n"
        f"{link}\n\n"
        "If you didn't request this, you can safely ignore this email.\n"
    )

    if EMAIL_MODE == "resend" and RESEND_API_KEY:
        try:
            await _send_resend(to_email, subject, body)
            logger.info("Magic link sent to %s via Resend", to_email)
            return
        except Exception:
            logger.exception("Resend send failed for %s", to_email)
            return

    if EMAIL_MODE == "smtp" and SMTP_HOST:
        try:
            await asyncio.to_thread(_send_smtp_blocking, to_email, subject, body)
            logger.info("Magic link sent to %s via SMTP", to_email)
            return
        except Exception:
            logger.exception("SMTP send failed for %s", to_email)
            return

    # console mode (or fallback when no provider is configured)
    banner = "─" * 64
    print(f"\n{banner}\n[email] To: {to_email}\n[email] {link}\n{banner}\n", flush=True)
    logger.info("Magic link for %s: %s", to_email, link)
