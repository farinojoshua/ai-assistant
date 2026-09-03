from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agent.events import ErrorEvent, TextEvent, ToolEvent
from app.agent.orchestrator import run_turn
from app.auth.deps import CurrentUser
from app.conversation import service as conversation
from app.db.app_db import get_sessionmaker
from app.db.company_db import get_company_gateway
from app.chat.schemas import ChatRequest
from app.llm.registry import get_provider
from app.tools.base import ToolContext
from app.whatsapp.send import send_text as wa_send_text

router = APIRouter(prefix="/api", tags=["chat"])


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat(body: ChatRequest, user: CurrentUser) -> StreamingResponse:
    conv_uuid: uuid.UUID | None = None
    if body.conversation_id:
        try:
            conv_uuid = uuid.UUID(body.conversation_id)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="invalid conversation_id",
            ) from None

    user_id, tenant_id, message = user.id, user.tenant_id, body.message
    provider = get_provider()
    gateway = get_company_gateway()

    async def stream() -> AsyncIterator[str]:
        async with get_sessionmaker()() as session:
            try:
                conv = await conversation.get_or_create(
                    session,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    conversation_id=conv_uuid,
                )
            except HTTPException as e:
                yield _sse("error", {"message": e.detail})
                return

            history = await conversation.get_history(session, conv.id)
            await conversation.append(
                session, conv, role="user", content=message
            )
            await session.commit()

            ctx = ToolContext(user=user, tenant_id=tenant_id, db=gateway)
            final_text: str | None = None

            async for ev in run_turn(
                provider=provider,
                ctx=ctx,
                audit_session=session,
                history=history,
                user_message=message,
                conversation_id=conv.id,
            ):
                if isinstance(ev, ToolEvent):
                    yield _sse(
                        "tool", {"name": ev.name, "arguments": ev.arguments}
                    )
                elif isinstance(ev, TextEvent):
                    final_text = ev.text
                    yield _sse("token", {"text": ev.text})
                elif isinstance(ev, ErrorEvent):
                    yield _sse("error", {"message": ev.message})

            if final_text is not None:
                await conversation.append(
                    session, conv, role="assistant", content=final_text
                )
            await session.commit()
            if final_text is not None and body.notify_whatsapp:
                await wa_send_text(final_text)
            yield _sse("done", {"conversation_id": str(conv.id)})

    return StreamingResponse(stream(), media_type="text/event-stream")
