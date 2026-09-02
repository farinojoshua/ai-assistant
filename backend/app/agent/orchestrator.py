from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.events import ErrorEvent, Event, TextEvent, ToolEvent
from app.agent.prompts import SYSTEM_PROMPT
from app.audit import service as audit
from app.config import Settings, get_settings
from app.llm.base import (
    LLMProvider,
    Message,
    ToolCall,
    assistant_tool_calls,
    tool_result_message,
)
from app.tools import registry
from app.tools.base import ToolContext


async def _run_tool(
    tc: ToolCall, ctx: ToolContext, timeout_s: float
) -> dict:
    tool = registry.get(tc.name)
    if tool is None:
        return {
            "error": "tool tidak tersedia",
            "hint": f"tidak ada tool bernama {tc.name!r}",
        }
    try:
        args = tool.parse_args(tc.arguments)
    except ValidationError as e:
        return {"error": "argumen tool tidak valid", "hint": e.errors(include_url=False)}
    try:
        return await asyncio.wait_for(tool.run(args, ctx), timeout=timeout_s)
    except asyncio.TimeoutError:
        return {"error": "timeout", "hint": f"tool {tc.name} melebihi {timeout_s}s"}
    except Exception as e:  # noqa: BLE001 - surface as data, keep the loop alive
        return {"error": "tool gagal dijalankan", "hint": str(e)}


async def run_turn(
    *,
    provider: LLMProvider,
    ctx: ToolContext,
    audit_session: AsyncSession,
    history: list[Message],
    user_message: str,
    conversation_id: uuid.UUID | None = None,
    settings: Settings | None = None,
) -> AsyncIterator[Event]:
    settings = settings or get_settings()
    messages: list[Message] = [
        Message(role="system", content=SYSTEM_PROMPT),
        *history,
        Message(role="user", content=user_message),
    ]
    specs = registry.all_specs()

    for _ in range(settings.agent_max_iterations):
        try:
            resp = await provider.chat(messages, specs)
        except Exception as e:  # noqa: BLE001
            yield ErrorEvent(f"LLM error: {e}")
            return

        if resp.stop_reason == "tool_use" and resp.tool_calls:
            calls = resp.tool_calls[: settings.agent_max_tool_calls_per_turn]
            messages.append(assistant_tool_calls(calls, resp.text or ""))
            for tc in calls:
                yield ToolEvent(name=tc.name, arguments=tc.arguments)
                result = await _run_tool(
                    tc, ctx, float(settings.agent_tool_timeout_s)
                )
                await audit.log(
                    audit_session,
                    user_id=ctx.user.id,
                    tenant_id=ctx.tenant_id,
                    conversation_id=conversation_id,
                    tool_call=tc,
                    result=result,
                )
                messages.append(tool_result_message(tc.id, result))
            continue

        if resp.stop_reason in ("end_turn", "max_tokens"):
            yield TextEvent(resp.text or "")
            return

        yield ErrorEvent(f"stop_reason tak terduga: {resp.stop_reason}")
        return

    yield ErrorEvent(
        "Tidak bisa menyelesaikan permintaan dalam batas langkah yang ada."
    )
