from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import current_user, limiter
from app.models import Preference, RefreshToken, User
from app.schemas import LoginIn, PreferenceOut, RefreshIn, RegisterIn, TokenOut, UserOut
from app.security import (
    create_access_token,
    hash_password,
    hash_refresh,
    new_refresh_token,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])
_s = get_settings()
# Verifying against this when the user is unknown keeps login timing uniform.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


async def _issue(session: AsyncSession, user_id: str) -> TokenOut:
    raw, hashed = new_refresh_token()
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=hashed,
            expires_at=datetime.now(timezone.utc) + timedelta(days=get_settings().refresh_token_days),
        )
    )
    await session.commit()
    return TokenOut(access_token=create_access_token(user_id), refresh_token=raw)


@router.post("/register", response_model=TokenOut, status_code=201)
@limiter.limit(_s.rate_limit_auth)
async def register(request: Request, body: RegisterIn, session: AsyncSession = Depends(get_session)):
    user = User(email=body.email.lower(), password_hash=hash_password(body.password))
    user.preference = Preference()
    session.add(user)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, "Email already registered")
    return await _issue(session, user.id)


@router.post("/login", response_model=TokenOut)
@limiter.limit(_s.rate_limit_auth)
async def login(request: Request, body: LoginIn, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).where(User.email == body.email.lower()))).scalar_one_or_none()
    ok = verify_password(body.password, user.password_hash if user else _DUMMY_HASH)
    if not user or not ok:
        raise HTTPException(401, "Invalid email or password")
    return await _issue(session, user.id)


@router.post("/refresh", response_model=TokenOut)
@limiter.limit(_s.rate_limit_auth)
async def refresh(request: Request, body: RefreshIn, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh(body.refresh_token)))
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if not row or row.revoked or row.expires_at.replace(tzinfo=timezone.utc) < now:
        raise HTTPException(401, "Invalid refresh token")
    row.revoked = True  # rotation: each refresh token is single-use
    return await _issue(session, row.user_id)


@router.post("/logout", status_code=204)
async def logout(body: RefreshIn, session: AsyncSession = Depends(get_session)):
    row = (
        await session.execute(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh(body.refresh_token)))
    ).scalar_one_or_none()
    if row:
        row.revoked = True
        await session.commit()


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)):
    return UserOut(id=user.id, email=user.email, preferences=PreferenceOut.model_validate(user.preference))
