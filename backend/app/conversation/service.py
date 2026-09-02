from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message
from app.llm.base import Message as LLMMessage

_HISTORY_LIMIT = 40


async def get_or_create(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
) -> Conversation:
    if conversation_id is None:
        conv = Conversation(tenant_id=tenant_id, user_id=user_id)
        session.add(conv)
        await session.flush()
        return conv

    conv = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
                Conversation.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
    return conv


async def get_history(
    session: AsyncSession, conversation_id: uuid.UUID
) -> list[LLMMessage]:
    rows = (
        await session.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at)
            .limit(_HISTORY_LIMIT)
        )
    ).scalars().all()
    return [LLMMessage(role=m.role, content=m.content) for m in rows]


async def append(
    session: AsyncSession,
    conv: Conversation,
    *,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
) -> None:
    session.add(
        Message(
            conversation_id=conv.id, role=role, content=content, meta=meta
        )
    )
    if role == "user" and not conv.title:
        conv.title = content[:60]
    await session.flush()
