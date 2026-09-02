"""Manual check that the configured LLM provider can call a tool.

    # set LLM_PROVIDER + creds in .env first, then:
    python scripts/smoke_llm.py

Prints the raw LLMResponse. Expect a tool_use for ambil_data or daftar_data.
"""
from __future__ import annotations

import asyncio

from app.llm.base import Message
from app.llm.registry import get_provider
from app.tools import registry


async def main() -> None:
    provider = get_provider()
    resp = await provider.chat(
        messages=[
            Message(
                role="system",
                content="Kamu asisten data. Gunakan tool untuk cek data.",
            ),
            Message(role="user", content="berapa stok kabel usb?"),
        ],
        tools=registry.all_specs(),
    )
    print(resp.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
