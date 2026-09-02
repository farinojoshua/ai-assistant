from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.security import create_access_token, hash_password
from app.db.models import Tenant, User


@pytest.fixture
async def seeded_user(db: AsyncSession) -> User:
    tenant = Tenant(nama="Acme")
    db.add(tenant)
    await db.flush()
    user = User(
        tenant_id=tenant.id,
        email="budi@acme.test",
        password_hash=hash_password("rahasia123"),
        nama="Budi",
        role="admin",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def test_login_ok(client: AsyncClient, seeded_user: User) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"email": "budi@acme.test", "password": "rahasia123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access"] and body["refresh"]
    assert body["token_type"] == "bearer"


async def test_login_wrong_password(
    client: AsyncClient, seeded_user: User
) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"email": "budi@acme.test", "password": "salah"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login",
        json={"email": "nobody@acme.test", "password": "x"},
    )
    assert resp.status_code == 401


async def test_me_requires_token(client: AsyncClient) -> None:
    resp = await client.get("/api/me")
    assert resp.status_code == 401


async def test_me_with_token(client: AsyncClient, seeded_user: User) -> None:
    login = await client.post(
        "/api/auth/login",
        json={"email": "budi@acme.test", "password": "rahasia123"},
    )
    access = login.json()["access"]
    resp = await client.get(
        "/api/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "budi@acme.test"
    assert body["tenant_id"] == str(seeded_user.tenant_id)
    assert body["role"] == "admin"


async def test_refresh(client: AsyncClient, seeded_user: User) -> None:
    login = await client.post(
        "/api/auth/login",
        json={"email": "budi@acme.test", "password": "rahasia123"},
    )
    refresh = login.json()["refresh"]
    resp = await client.post("/api/auth/refresh", json={"refresh": refresh})
    assert resp.status_code == 200
    access = resp.json()["access"]
    me = await client.get(
        "/api/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert me.status_code == 200


async def test_refresh_rejects_access_token(
    client: AsyncClient, seeded_user: User
) -> None:
    login = await client.post(
        "/api/auth/login",
        json={"email": "budi@acme.test", "password": "rahasia123"},
    )
    access = login.json()["access"]
    resp = await client.post("/api/auth/refresh", json={"refresh": access})
    assert resp.status_code == 401


async def test_expired_token(client: AsyncClient, seeded_user: User) -> None:
    token = create_access_token(
        str(seeded_user.id), str(seeded_user.tenant_id), ttl_minutes=-1
    )
    resp = await client.get(
        "/api/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 401


async def test_malformed_token(client: AsyncClient) -> None:
    resp = await client.get(
        "/api/me", headers={"Authorization": "Bearer not-a-jwt"}
    )
    assert resp.status_code == 401
