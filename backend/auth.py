"""
auth.py — magic-link auth + session core.

Design notes
────────────
Tokens (magic + session) are generated with `secrets.token_urlsafe(32)` and
NEVER stored in the database. The DB only ever sees an HMAC-SHA-256 of the
token, keyed by SESSION_SECRET. This means:

  * A DB read leak does not enable login (attacker would need SESSION_SECRET).
  * SESSION_SECRET rotation invalidates all live tokens — intentional.

The opaque session token rides in an httpOnly cookie. Cookie attributes are
fully env-driven so dev (insecure, SameSite=lax) and prod (Secure,
SameSite=strict) share one code path.

Anti-enumeration: `request_magic_link` is idempotent and silently
auto-creates users on first contact. Callers should never branch their
response on whether a user pre-existed.

CSRF: with SameSite=strict in prod, the cookie isn't attached to cross-site
requests at all, so CSRF is not reachable. In dev (SameSite=lax) the cookie
is attached only on top-level GET navigation; our state-changing endpoints
are POST/DELETE so lax is sufficient for local development. No CSRF token
infrastructure is needed at this scope. (Documented also in README.)
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSessionLocal, get_session
from db_models import MagicToken, Session as SessionRow, User


# ── Configuration (env) ──────────────────────────────────────────────────────
SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    # Fail loud at import time in production. Local dev gets a stable random
    # default so the app boots, but tokens won't survive a restart.
    if os.environ.get("ENVIRONMENT", "development").lower() == "production":
        raise RuntimeError("SESSION_SECRET must be set in production.")
    SESSION_SECRET = "dev-only-not-secret-" + secrets.token_hex(8)

MAGIC_LINK_TTL_MINUTES: int = int(os.environ.get("MAGIC_LINK_TTL_MINUTES", "15"))
SESSION_TTL_DAYS:       int = int(os.environ.get("SESSION_TTL_DAYS", "30"))

COOKIE_NAME            = "syllabus_session"
COOKIE_SECURE          = os.environ.get("COOKIE_SECURE", "false").lower() == "true"
COOKIE_SAMESITE: str   = os.environ.get("COOKIE_SAMESITE", "lax").lower()
if COOKIE_SAMESITE not in ("strict", "lax", "none"):
    COOKIE_SAMESITE = "lax"


# ── Helpers ──────────────────────────────────────────────────────────────────
def normalize_email(raw: str) -> str:
    """Lowercase + strip. Sufficient for our scope; we don't try to canonicalize
    plus-tags or punycode hosts — the goal is dedup on accidental case/whitespace
    differences, not to fight every edge case."""
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="Email is required.")
    out = raw.strip().lower()
    if "@" not in out or len(out) > 320:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return out


def hash_token(raw_token: str) -> str:
    """HMAC-SHA-256(token, SESSION_SECRET) → hex. Constant length, safe to
    store and to use in DB equality lookups."""
    return hmac.new(
        SESSION_SECRET.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Magic-link issuance ──────────────────────────────────────────────────────
async def request_magic_link(email_raw: str) -> tuple[str, User]:
    """Create (or fetch) the user, issue a fresh magic token, return
    (raw_token, user). The caller is responsible for emailing the link.

    Always succeeds for any well-formed email. Never reveals whether the user
    pre-existed.
    """
    email = normalize_email(email_raw)
    raw_token = secrets.token_urlsafe(32)
    token_hash = hash_token(raw_token)
    expires_at = _now() + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(User).where(User.email_normalized == email))
        user: Optional[User] = result.scalar_one_or_none()

        if user is None:
            user = User(email=email, email_normalized=email)
            session.add(user)
            await session.flush()  # populate user.id for FK below

        session.add(MagicToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
        ))
        await session.commit()
        await session.refresh(user)

    return raw_token, user


async def redeem_magic_link(raw_token: str, db: AsyncSession) -> User:
    """Validate a magic token (not expired, not used), mark it used, return
    the owning user. Caller is responsible for creating the session +
    setting the cookie.

    Generic 400 on every failure path — never tell the client whether the
    token was malformed, expired, or already used. (Reduces signal for
    brute-force attempts.)
    """
    if not raw_token or not isinstance(raw_token, str) or len(raw_token) > 200:
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    token_hash = hash_token(raw_token)
    now = _now()

    result = await db.execute(
        select(MagicToken).where(MagicToken.token_hash == token_hash)
    )
    mt: Optional[MagicToken] = result.scalar_one_or_none()
    if mt is None or mt.used_at is not None or mt.expires_at < now:
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    mt.used_at = now
    user = await db.get(User, mt.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    await db.commit()
    return user


# ── Sessions ─────────────────────────────────────────────────────────────────
async def create_session(user_id: uuid.UUID, db: AsyncSession) -> str:
    """Issue a session row and return the raw session token to put in the
    cookie. Hash is stored, raw is not."""
    raw = secrets.token_urlsafe(32)
    expires_at = _now() + timedelta(days=SESSION_TTL_DAYS)

    db.add(SessionRow(
        user_id=user_id,
        session_hash=hash_token(raw),
        expires_at=expires_at,
    ))
    await db.commit()
    return raw


async def revoke_session(raw_token: str, db: AsyncSession) -> None:
    if not raw_token:
        return
    await db.execute(
        delete(SessionRow).where(SessionRow.session_hash == hash_token(raw_token))
    )
    await db.commit()


def set_session_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=raw_token,
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    # delete_cookie must echo the same path/samesite/secure as the original
    # set, otherwise some browsers leave the cookie in place.
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )


# ── FastAPI dependencies ─────────────────────────────────────────────────────
async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> Optional[User]:
    """Returns the logged-in User or None. Use this for endpoints that
    optionally personalize but don't require auth."""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None

    sess = (
        await db.execute(
            select(SessionRow).where(SessionRow.session_hash == hash_token(raw))
        )
    ).scalar_one_or_none()
    if sess is None or sess.expires_at < _now():
        return None

    return await db.get(User, sess.user_id)


async def require_user(
    user: Optional[User] = Depends(get_current_user),
) -> User:
    """Dependency for protected routes. 401 if not logged in."""
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user
