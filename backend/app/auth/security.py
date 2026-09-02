"""Password hashing and JWT helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings

ALGORITHM = "HS256"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def _encode(claims: dict, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {**claims, "iat": now, "exp": now + ttl}
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def create_access_token(
    sub: str, tenant_id: str, ttl_minutes: int | None = None
) -> str:
    minutes = (
        ttl_minutes
        if ttl_minutes is not None
        else get_settings().jwt_access_ttl_min
    )
    return _encode(
        {"sub": sub, "tenant_id": tenant_id, "type": "access"},
        timedelta(minutes=minutes),
    )


def create_refresh_token(sub: str, ttl_days: int | None = None) -> str:
    days = ttl_days if ttl_days is not None else get_settings().jwt_refresh_ttl_days
    return _encode({"sub": sub, "type": "refresh"}, timedelta(days=days))


def decode_token(token: str, *, expected_type: str) -> dict:
    """Return the payload, or raise JWTError if invalid/expired/wrong type."""
    payload = jwt.decode(
        token, get_settings().jwt_secret, algorithms=[ALGORITHM]
    )
    if payload.get("type") != expected_type:
        raise JWTError(f"expected {expected_type} token")
    return payload
