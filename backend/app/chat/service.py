"""Non-streaming chat turn — shared by the WhatsApp webhook.

The SSE endpoint in ``routes.py`` stays as-is; this collapses the same
orchestrator run into a single final string for channels that can't stream.
"""
from __future__ import annotations

import uuid

from app.agent.events import ErrorEvent, TextEvent
from app.agent.orchestrator import run_turn
from app.conversation import service as conversation
from app.db.app_db import get_sessionmaker
from app.db.company_db import get_company_gateway
from app.db.models import User
from app.llm.registry import get_provider
from app.tools.base import ToolContext


async def run_chat_turn(
    *,
    user: User,
    message: str,
    conversation_id: uuid.UUID | None,
    channel: str = "web",
) -> tuple[str, uuid.UUID]:
    """Run one agent turn, persist it, return ``(reply_text, conversation_id)``."""
    provider = get_provider()
    gateway = get_company_gateway()

    async with get_sessionmaker()() as session:
        conv = await conversation.get_or_create(
            session,
            user_id=user.id,
            tenant_id=user.tenant_id,
            conversation_id=conversation_id,
        )
        history = await conversation.get_history(session, conv.id)
        await conversation.append(session, conv, role="user", content=message)
        await session.commit()

        ctx = ToolContext(user=user, tenant_id=user.tenant_id, db=gateway)
        final_text: str | None = None
        async for ev in run_turn(
            provider=provider,
            ctx=ctx,
            audit_session=session,
            history=history,
            user_message=message,
            conversation_id=conv.id,
            channel=channel,
        ):
            if isinstance(ev, TextEvent):
                final_text = ev.text
            elif isinstance(ev, ErrorEvent):
                final_text = final_text or ev.message

        reply = final_text or "Maaf, tidak ada jawaban yang bisa diberikan."
        await conversation.append(
            session, conv, role="assistant", content=reply
        )
        await session.commit()
        return reply, conv.id
