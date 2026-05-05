"""
Auth primitives — password hashing, JWT mint/verify, current_user dependency.

When AUTH_REQUIRED is False (default), `current_user` returns None and routes
that depend on it run anonymously. Flip AUTH_REQUIRED=true in .env once the
frontend login flow is wired.
"""
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User


JWT_ALGORITHM = "HS256"


# ----- password hashing ------------------------------------------------------

def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ----- JWT -------------------------------------------------------------------

def _require_secret() -> str:
    if not settings.JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is empty. Set it in .env to a long random string "
            "before enabling AUTH_REQUIRED."
        )
    return settings.JWT_SECRET


def create_access_token(user_id: str, email: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.JWT_EXPIRES_HOURS)).timestamp()),
    }
    return jwt.encode(payload, _require_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, _require_secret(), algorithms=[JWT_ALGORITHM])


# ----- FastAPI dependency ----------------------------------------------------

async def _user_from_request(
    request: Request,
    db: AsyncSession,
) -> User | None:
    """Extract the user from the Authorization header. Returns None when no
    valid token is supplied. Raises 401 only if a token is present but bad."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header.removeprefix("Bearer ").strip()
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = (await db.execute(
        select(User).where(User.id == user_id)
    )).scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Dependency: returns the authenticated user, or None if anonymous.

    When AUTH_REQUIRED is False, anonymous requests pass through. When True,
    a missing Authorization header → 401."""
    user = await _user_from_request(request, db)
    if user is None and settings.AUTH_REQUIRED:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user
