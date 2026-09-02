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
