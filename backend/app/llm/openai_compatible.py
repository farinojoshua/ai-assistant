"""Adapter for any OpenAI-compatible chat-completions API.

Ollama Cloud, OpenAI, and several others speak this protocol, so the
translation lives here once and providers just supply base_url + api_key +
model.
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.llm.base import (
    LLMProvider,
    LLMResponse,
    Message,
    StopReason,
    ToolCall,
    ToolSpec,
    Usage,
)

_FINISH_REASON: dict[str, StopReason] = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "function_call": "tool_use",
    "length": "max_tokens",
}


def _to_wire_messages(messages: list[Message]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id,
                    "content": m.content,
                }
            )
        elif m.role == "assistant" and m.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(
                                    tc.arguments, ensure_ascii=False
                                ),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": m.role, "content": m.content})
    return out


def _to_wire_tools(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.input_schema,
            },
        }
        for t in tools
    ]


def _parse_tool_calls(raw: Any) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for tc in raw or []:
        fn = tc.function
        try:
            args = json.loads(fn.arguments) if fn.arguments else {}
        except json.JSONDecodeError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        calls.append(ToolCall(id=tc.id, name=fn.name, arguments=args))
    return calls


class OpenAICompatibleProvider(LLMProvider):
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {"base_url": base_url, "api_key": api_key or "-"}
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = AsyncOpenAI(**kwargs)
        self._model = model

    async def chat(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": _to_wire_messages(messages),
        }
        if tools:
            kwargs["tools"] = _to_wire_tools(tools)

        resp = await self._client.chat.completions.create(**kwargs)
        choice = resp.choices[0]
        tool_calls = _parse_tool_calls(choice.message.tool_calls)
        stop = _FINISH_REASON.get(choice.finish_reason or "stop", "end_turn")
        if tool_calls:
            stop = "tool_use"

        usage = None
        if resp.usage:
            usage = Usage(
                input_tokens=resp.usage.prompt_tokens or 0,
                output_tokens=resp.usage.completion_tokens or 0,
            )
        return LLMResponse(
            text=choice.message.content,
            tool_calls=tool_calls,
            stop_reason=stop,
            usage=usage,
        )
