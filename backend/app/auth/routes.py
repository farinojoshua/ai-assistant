from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.app_db import get_db
from app.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

_BAD_CREDS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
)


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access: str
    refresh: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh: str


class AccessToken(BaseModel):
    access: str
    token_type: str = "bearer"


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> TokenPair:
    user = (
        await db.execute(select(User).where(User.email == body.email))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise _BAD_CREDS
    return TokenPair(
        access=create_access_token(str(user.id), str(user.tenant_id)),
        refresh=create_refresh_token(str(user.id)),
    )


@router.post("/refresh", response_model=AccessToken)
async def refresh(
    body: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]
) -> AccessToken:
    try:
        payload = decode_token(body.refresh, expected_type="refresh")
    except JWTError:
        raise _BAD_CREDS from None

    user = (
        await db.execute(select(User).where(User.id == payload.get("sub")))
    ).scalar_one_or_none()
    if user is None:
        raise _BAD_CREDS
    return AccessToken(
        access=create_access_token(str(user.id), str(user.tenant_id))
    )
