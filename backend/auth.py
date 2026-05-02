"""Magic-link auth + session management. Tokens are HMAC'd before storage."""
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


SESSION_SECRET: str = os.environ.get("SESSION_SECRET", "")
if not SESSION_SECRET:
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
    """Issue a magic token, creating the user if needed. Always returns 200."""
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
                await session.flush()
            except IntegrityError:
                # race on first signup — re-fetch the winning row
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
    """Validate and consume a magic token. Generic 400 on every failure path."""
    if not raw_token or not isinstance(raw_token, str) or len(raw_token) > 200:
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    token_hash = hash_token(raw_token)
    now = _now()

    # atomic check-and-mark — prevents double-use
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
        await db.rollback()
        raise HTTPException(status_code=400, detail="Invalid or expired link.")

    await db.commit()
    return user


# Sessions

async def create_session(user_id: uuid.UUID, db: AsyncSession) -> str:
    """Create session, return raw token for cookie."""
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
    """Returns logged-in user or None."""
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