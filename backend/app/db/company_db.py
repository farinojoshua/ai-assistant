"""Read-only gateway to the company's database.

The LLM never touches SQL directly — tool handlers call `fetch()` with a
parameterized statement. This class deliberately exposes no write path.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import TextClause
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings


class CompanyDbGateway:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_settings(cls) -> CompanyDbGateway:
        engine = create_async_engine(
            get_settings().company_database_url,
            pool_pre_ping=True,
            # belt-and-braces: the DB user should already be read-only
            execution_options={"postgresql_readonly": True},
        )
        return cls(engine)

    async def fetch(
        self, sql: TextClause, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            result = await conn.execute(sql, params or {})
            return [dict(row) for row in result.mappings().all()]

    async def dispose(self) -> None:
        await self._engine.dispose()


_gateway: CompanyDbGateway | None = None


def get_company_gateway() -> CompanyDbGateway:
    global _gateway
    if _gateway is None:
        _gateway = CompanyDbGateway.from_settings()
    return _gateway


class CompanyDbWriter:
    """Write-capable connection to the company DB, used only by the
    structured stock-update endpoint. In production the connection user is
    scoped to INSERT/UPDATE on stok_barang.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    @classmethod
    def from_settings(cls) -> CompanyDbWriter:
        return cls(
            create_async_engine(
                get_settings().company_database_write_url, pool_pre_ping=True
            )
        )

    async def fetch(
        self, sql: TextClause, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            result = await conn.execute(sql, params or {})
            return [dict(r) for r in result.mappings().all()]

    async def execute_returning(
        self, sql: TextClause, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        async with self._engine.begin() as conn:
            result = await conn.execute(sql, params)
            row = result.mappings().first()
            return dict(row) if row else None

    async def dispose(self) -> None:
        await self._engine.dispose()


_writer: CompanyDbWriter | None = None


def get_company_writer() -> CompanyDbWriter:
    global _writer
    if _writer is None:
        _writer = CompanyDbWriter.from_settings()
    return _writer
