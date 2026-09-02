from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

import app  # noqa: F401  (installs the Windows selector event-loop policy)
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Test DB URL — override with TEST_APP_DATABASE_URL if needed.
TEST_APP_DB_URL = os.environ.get(
    "TEST_APP_DATABASE_URL",
    "postgresql+psycopg://app:app@localhost:5432/app_test",
)
TEST_COMPANY_DB_URL = os.environ.get(
    "TEST_COMPANY_DATABASE_URL",
    "postgresql+psycopg://company:company@localhost:5433/company_test",
)
_SEED_SQL = (
    Path(__file__).resolve().parent.parent / "scripts" / "seed_company_db.sql"
).read_text()

from app.db.models import Base  # noqa: E402


@pytest_asyncio.fixture(scope="session")
async def _engine():
    engine = create_async_engine(TEST_APP_DB_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db(_engine) -> AsyncIterator[AsyncSession]:
    """Fresh session per test; rows are truncated afterwards."""
    maker = async_sessionmaker(_engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    async with _engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.exec_driver_sql(
                f'TRUNCATE TABLE "{table.name}" CASCADE'
            )


@pytest_asyncio.fixture(scope="session")
async def _company_engine():
    engine = create_async_engine(TEST_COMPANY_DB_URL, poolclass=None)
    async with engine.begin() as conn:
        await conn.exec_driver_sql(_SEED_SQL)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def company_gateway(_company_engine):
    from app.db.company_db import CompanyDbGateway

    return CompanyDbGateway(_company_engine)


@pytest_asyncio.fixture
async def company_writer(_company_engine):
    """Write-capable company DB; restores the seed after the test so writes
    don't leak into other tests sharing the session-scoped engine."""
    from app.db.company_db import CompanyDbWriter

    yield CompanyDbWriter(_company_engine)
    async with _company_engine.begin() as conn:
        await conn.exec_driver_sql(_SEED_SQL)


@pytest_asyncio.fixture
async def client(_engine) -> AsyncIterator[AsyncClient]:
    from app.db import app_db
    from app.main import app

    maker = async_sessionmaker(_engine, expire_on_commit=False)

    async def _get_db() -> AsyncIterator[AsyncSession]:
        async with maker() as session:
            yield session

    app.dependency_overrides[app_db.get_db] = _get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()
