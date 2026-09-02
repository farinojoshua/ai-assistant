from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.config import Settings
from app.llm.base import Message, ToolCall, ToolSpec, assistant_tool_calls
from app.llm.ollama import OllamaCloudProvider

STOCK_TOOL = ToolSpec(
    name="cek_stok",
    description="Cek stok barang",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
)


class _Capture:
    """Mock transport that records the last request and replies with `payload`."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.last_request: httpx.Request | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.last_request = request
        return httpx.Response(200, json=self.payload)

    @property
    def sent_body(self) -> dict[str, Any]:
        assert self.last_request is not None
        return json.loads(self.last_request.content)


@pytest.fixture
def capture():
    def _make(payload: dict[str, Any]) -> tuple[OllamaCloudProvider, _Capture]:
        cap = _Capture(payload)
        client = httpx.AsyncClient(transport=httpx.MockTransport(cap.handler))
        provider = OllamaCloudProvider(
            Settings(
                ollama_base_url="https://ollama.com",
                ollama_api_key="test-key",
                llm_model="qwen2.5:72b",
            ),
            http_client=client,
        )
        return provider, cap

    return _make


async def test_translation_tool_use(capture) -> None:
    provider, cap = capture(
        {
            "id": "c1",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "cek_stok",
                                    "arguments": '{"query": "kabel usb"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 8,
                "total_tokens": 20,
            },
        }
    )

    resp = await provider.chat(
        [Message(role="user", content="stok kabel usb?")], [STOCK_TOOL]
    )

    assert resp.stop_reason == "tool_use"
    assert len(resp.tool_calls) == 1
    tc = resp.tool_calls[0]
    assert (tc.id, tc.name) == ("call_1", "cek_stok")
    assert tc.arguments == {"query": "kabel usb"}
    assert resp.usage.input_tokens == 12

    assert cap.last_request.headers["authorization"] == "Bearer test-key"
    body = cap.sent_body
    assert body["tools"][0]["function"]["name"] == "cek_stok"


async def test_translation_end_turn(capture) -> None:
    provider, _ = capture(
        {
            "id": "c2",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Stok kabel USB ada 40 unit.",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
    )
    resp = await provider.chat(
        [Message(role="user", content="stok kabel usb?")], [STOCK_TOOL]
    )
    assert resp.stop_reason == "end_turn"
    assert resp.text == "Stok kabel USB ada 40 unit."
    assert resp.tool_calls == []


async def test_bad_tool_arguments_become_empty_dict(capture) -> None:
    provider, _ = capture(
        {
            "id": "c4",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_9",
                                "type": "function",
                                "function": {
                                    "name": "cek_stok",
                                    "arguments": "{not valid json",
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    )
    resp = await provider.chat([Message(role="user", content="x")], [STOCK_TOOL])
    assert resp.tool_calls[0].arguments == {}


async def test_tool_result_roundtrip_serialization(capture) -> None:
    provider, cap = capture(
        {
            "id": "c3",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }
            ],
        }
    )
    messages = [
        Message(role="user", content="stok kabel?"),
        assistant_tool_calls(
            [ToolCall(id="call_1", name="cek_stok", arguments={"query": "kabel"})]
        ),
        Message(
            role="tool",
            tool_call_id="call_1",
            content='{"rows": [{"sku": "KBL-1", "qty": 40}]}',
        ),
    ]
    await provider.chat(messages, [STOCK_TOOL])

    wire = cap.sent_body["messages"]
    assert wire[1]["tool_calls"][0]["id"] == "call_1"
    assert wire[2] == {
        "role": "tool",
        "tool_call_id": "call_1",
        "content": '{"rows": [{"sku": "KBL-1", "qty": 40}]}',
    }
