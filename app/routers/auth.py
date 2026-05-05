"""Auth endpoints: login + current user."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services.auth import (
    create_access_token,
    current_user,
    verify_password,
)


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = (await db.execute(
        select(User).where(User.email == payload.email.lower())
    )).scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.password_hash):
        # Same message for both cases — don't leak which emails exist.
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is inactive")

    user.last_login_at = datetime.now(timezone.utc)
    await db.flush()

    token = create_access_token(str(user.id), user.email)
    return LoginResponse(
        access_token=token,
        user={"id": str(user.id), "email": user.email},
    )


@router.get("/me")
async def me(user: User | None = Depends(current_user)):
    """Current user info, or 401 if no valid token. Useful for the frontend
    to verify a stored token is still good on page load."""
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {
        "id": str(user.id),
        "email": user.email,
        "is_active": user.is_active,
        "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
    }
