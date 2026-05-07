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


async def _send_resend(to_email: str, subject: str, body: str, html: str | None = None) -> None:
    payload = {
        "from": RESEND_FROM,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    if html:
        payload["html"] = html

    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()


def _build_magic_link_html(link: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background-color:#FDF8F3;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#FDF8F3;padding:48px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="480" cellpadding="0" cellspacing="0" border="0" style="background-color:#FFFFFF;border-radius:16px;border:1px solid #E6DFD3;box-shadow:0 4px 20px rgba(143,184,158,0.08);padding:40px;max-width:480px;">
          <tr>
            <td>
              <div style="margin-bottom:32px;">
                <h1 style="margin:0;font-size:34px;font-weight:700;color:#6F9A7A;letter-spacing:-0.5px;">Sylva</h1>
                <p style="margin:4px 0 0;font-size:13px;color:#A0958A;">Your College Companion</p>
              </div>

              <h2 style="margin:0 0 12px;font-size:22px;font-weight:600;color:#3D3D3D;">Sign in to Sylva</h2>
              <p style="margin:0 0 28px;font-size:16px;line-height:1.5;color:#5A5A5A;">
                Click the button below to sign in. This link is single-use and expires in 15 minutes.
              </p>

              <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 28px;">
                <tr>
                  <td style="background-color:#8FB89E;border-radius:10px;">
                    <a href="{link}" style="display:inline-block;padding:14px 32px;color:#FFFFFF;font-size:15px;font-weight:600;text-decoration:none;letter-spacing:0.2px;">Sign in to Sylva &rarr;</a>
                  </td>
                </tr>
              </table>

              <p style="margin:0 0 8px;font-size:13px;color:#999;">
                Or copy and paste this URL into your browser:
              </p>
              <p style="margin:0;font-size:12px;line-height:1.5;word-break:break-all;">
                <a href="{link}" style="color:#6F9A7A;text-decoration:none;">{link}</a>
              </p>

              <hr style="border:none;border-top:1px solid #E6DFD3;margin:32px 0 24px;">

              <p style="margin:0;font-size:13px;line-height:1.5;color:#A0958A;">
                Didn't request this? You can safely ignore this email.
              </p>
            </td>
          </tr>
        </table>

        <p style="margin:24px 0 0;font-size:12px;color:#A0958A;">
          Sylva &middot; Made with care for students everywhere
        </p>
      </td>
    </tr>
  </table>
</body>
</html>"""


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
        "and expires in 15 minutes.\n\n"
        f"{link}\n\n"
        "If you didn't request this, you can safely ignore this email.\n"
    )
    html = _build_magic_link_html(link)

    if EMAIL_MODE == "resend" and RESEND_API_KEY:
        try:
            await _send_resend(to_email, subject, body, html)
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
