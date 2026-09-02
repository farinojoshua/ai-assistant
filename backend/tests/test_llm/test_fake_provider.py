from __future__ import annotations

import json

import pytest

from app.llm.base import (
    LLMResponse,
    Message,
    ToolCall,
    tool_result_message,
)
from app.llm.fake import FakeProvider


async def test_returns_script_in_order() -> None:
    p = FakeProvider(
        script=[
            LLMResponse(stop_reason="tool_use", tool_calls=[
                ToolCall(id="1", name="cek_stok", arguments={"query": "kabel"})
            ]),
            LLMResponse(text="stok kabel 40", stop_reason="end_turn"),
        ]
    )
    r1 = await p.chat([Message(role="user", content="stok kabel?")], [])
    assert r1.stop_reason == "tool_use"
    assert r1.tool_calls[0].name == "cek_stok"

    r2 = await p.chat([Message(role="user", content="x")], [])
    assert r2.text == "stok kabel 40"


async def test_script_exhausted_raises() -> None:
    p = FakeProvider(script=[LLMResponse(text="hi")])
    await p.chat([], [])
    with pytest.raises(AssertionError):
        await p.chat([], [])


async def test_records_messages() -> None:
    p = FakeProvider(script=[LLMResponse(text="ok"), LLMResponse(text="ok2")])
    await p.chat([Message(role="user", content="first")], [])
    await p.chat([Message(role="user", content="second")], [])
    assert len(p.calls) == 2
    assert p.recorded_messages[0].content == "second"


async def test_can_script_an_exception() -> None:
    p = FakeProvider(script=[RuntimeError("boom")])
    with pytest.raises(RuntimeError, match="boom"):
        await p.chat([], [])


def test_tool_result_message_shape() -> None:
    msg = tool_result_message("call_7", {"rows": [{"sku": "A1"}]})
    assert msg.role == "tool"
    assert msg.tool_call_id == "call_7"
    assert json.loads(msg.content) == {"rows": [{"sku": "A1"}]}
