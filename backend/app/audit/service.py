from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.llm.base import ToolCall


def _summarize(result: dict[str, Any]) -> tuple[int | None, str | None]:
    if "error" in result:
        return None, str(result["error"])
    rows = result.get("rows")
    if isinstance(rows, list):
        return len(rows), None
    return None, None


async def log(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    tool_call: ToolCall,
    result: dict[str, Any],
) -> None:
    row_count, error = _summarize(result)
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            tool_name=tool_call.name,
            arguments=tool_call.arguments,
            row_count=row_count,
            error=error,
        )
    )
    await session.flush()
