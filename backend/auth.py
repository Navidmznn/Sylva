"""Magic-link auth and session management.

Tokens are generated with secrets.token_urlsafe(32) and never stored raw.
The DB only sees an HMAC-SHA-256(token, SESSION_SECRET) digest, so a DB
read leak alone can't be used to log in. Rotating SESSION_SECRET
invalidates every live token — by design.

CSRF: production uses SameSite=strict, so the session cookie isn't sent on
cross-site requests at all. Dev uses SameSite=lax; every state-changing
endpoint is POST/DELETE, which lax doesn't auto-attach. No CSRF token
infra needed at this scope. (Don't add a state-changing GET endpoint.)
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
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db import AsyncSessionLocal, get_session
from db_models import MagicToken, Session as SessionRow, User


# Configuration
SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
    # Hard fail in prod. Dev gets an ephemeral key — tokens won't survive a restart.
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


# Helpers

def normalize_email(raw: str) -> str:
    """Lowercase + strip. We don't try to canonicalize plus-tags or punycode —
    just dedup on accidental case/whitespace differences."""
    if not isinstance(raw, str):
        raise HTTPException(status_code=400, detail="Email is required.")
    out = raw.strip().lower()
    if "@" not in out or len(out) > 320:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    return out


def hash_token(raw_token: str) -> str:
    return hmac.new(
        SESSION_SECRET.encode("utf-8"),
        raw_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# Magic-link issuance

async def request_magic_link(email_raw: str) -> tuple[str, User]:
    """Create or fetch the user, issue a fresh token, return (raw_token, user).
    Caller is responsible for emailing the link. Always succeeds for any
    well-formed email — never reveals whether the user pre-existed."""
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
            try:
                await session.flush()  # populate user.id for the FK below
            except IntegrityError:
                # A concurrent /auth/login for the same brand-new email
                # committed between our SELECT and our INSERT. The unique
                # constraint on email_normalized just rejected us. Roll back,
                # re-fetch the row the other request created, and continue —
                # the caller still gets a fresh magic token bound to the
                # canonical user row, and the anti-enumeration response in
                # api.py stays a constant 200.
                await session.rollback()
                user = (await session.execute(
                    select(User).where(User.email_normalized == email)
                )).scalar_one()

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
    the owning user. Generic 400 on every failure path — don't tell the
    client whether the token was malformed, expired, or already used.

    The UPDATE … WHERE used_at IS NULL … RETURNING is atomic: two concurrent
    redemptions of the same token can't both win. Only the first will match
    the predicate; the second sees rowcount=0 and 400s like a stale link.
    Without this, a double-click (or an attacker racing a stolen link) would
    yield two valid sessions from a single-use token.
    """
    if not raw_token or not isinstance(raw_token, str) or len(raw_token) > 200:
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    token_hash = hash_token(raw_token)
    now = _now()

    stmt = (
        update(MagicToken)
        .where(
            MagicToken.token_hash == token_hash,
            MagicToken.used_at.is_(None),
            MagicToken.expires_at >= now,
        )
        .values(used_at=now)
        .returning(MagicToken.user_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    user = await db.get(User, row.user_id)
    if user is None:
        # Token was valid but the user vanished (e.g. account deleted between
        # the UPDATE and the SELECT). Same generic 400 — don't disclose this.
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    await db.commit()
    return user


# Sessions

async def create_session(user_id: uuid.UUID, db: AsyncSession) -> str:
    """Issue a session row, return the raw token for the cookie. Only the
    HMAC is persisted."""
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
    # Must echo the original path/samesite/secure or some browsers leave the
    # cookie in place.
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
    )


# FastAPI dependencies

async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_session),
) -> Optional[User]:
    """Logged-in User or None. For routes that optionally personalize."""
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
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return user