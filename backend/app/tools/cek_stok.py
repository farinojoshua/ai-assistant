from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from app.tools.base import Tool, ToolContext

_SQL = text(
    """
    SELECT nama, sku, qty, satuan, gudang
    FROM v_stok
    WHERE (nama ILIKE :like_q OR sku ILIKE :q)
      AND (CAST(:gudang AS text) IS NULL OR gudang ILIKE CAST(:like_g AS text))
    ORDER BY nama
    LIMIT :limit
    """
)


class CekStokArgs(BaseModel):
    query: str = Field(description="nama produk atau kode SKU")
    gudang: str | None = Field(
        default=None, description="filter nama gudang (opsional)"
    )
    limit: int = Field(default=20, ge=1, le=100)


class CekStok(Tool):
    name = "cek_stok"
    description = (
        "Cek jumlah stok barang di gudang berdasarkan nama produk atau SKU. "
        "Bisa difilter per gudang."
    )
    args_model = CekStokArgs

    async def run(
        self, args: CekStokArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        rows = await ctx.db.fetch(
            _SQL,
            {
                "q": args.query,
                "like_q": f"%{args.query}%",
                "gudang": args.gudang,
                "like_g": f"%{args.gudang}%" if args.gudang else None,
                "limit": args.limit,
            },
        )
        if not rows:
            return {
                "rows": [],
                "hint": "tidak ada barang yang cocok dengan pencarian itu",
            }
        return {"rows": rows, "truncated": len(rows) == args.limit}
