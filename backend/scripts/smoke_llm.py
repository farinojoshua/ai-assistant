"""Manual check that the configured LLM provider can call a tool.

    # set LLM_PROVIDER + creds in .env first, then:
    python scripts/smoke_llm.py

Prints the raw LLMResponse. Expect a tool_use for `cek_stok`.
"""
from __future__ import annotations

import asyncio

from app.llm.base import Message, ToolSpec
from app.llm.registry import get_provider

CEK_STOK = ToolSpec(
    name="cek_stok",
    description="Cek jumlah stok barang di gudang berdasarkan nama atau SKU.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "nama produk atau SKU"}
        },
        "required": ["query"],
    },
)


async def main() -> None:
    provider = get_provider()
    resp = await provider.chat(
        messages=[
            Message(
                role="system",
                content="Kamu asisten gudang. Gunakan tool untuk cek data.",
            ),
            Message(role="user", content="berapa stok kabel usb?"),
        ],
        tools=[CEK_STOK],
    )
    print(resp.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
