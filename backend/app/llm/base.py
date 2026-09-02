"""Provider-neutral LLM types and the LLMProvider interface.

Adapters translate these to/from a specific provider's wire format. Nothing
here knows about business tools, the database, or HTTP.
"""
from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Literal

from pydantic import BaseModel, Field

Role = Literal["system", "user", "assistant", "tool"]
StopReason = Literal["end_turn", "tool_use", "max_tokens", "error"]


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Message(BaseModel):
    role: Role
    content: str = ""
    # set on assistant messages that request tools
    tool_calls: list[ToolCall] | None = None
    # set on tool-result messages
    tool_call_id: str | None = None


class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class LLMResponse(BaseModel):
    text: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = "end_turn"
    usage: Usage | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self, messages: list[Message], tools: list[ToolSpec]
    ) -> LLMResponse:
        """One model turn. Returns text, or tool calls to execute."""


# ---- helpers for building the conversation ----------------------------------


def assistant_tool_calls(tool_calls: list[ToolCall], text: str = "") -> Message:
    return Message(role="assistant", content=text, tool_calls=tool_calls)


def tool_result_message(tool_call_id: str, result: dict[str, Any]) -> Message:
    return Message(
        role="tool",
        tool_call_id=tool_call_id,
        content=json.dumps(result, ensure_ascii=False, default=str),
    )
