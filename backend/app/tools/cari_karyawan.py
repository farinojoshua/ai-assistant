from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import text

from app.tools.base import Tool, ToolContext

_SQL = text(
    """
    SELECT nama, nip, departemen, jabatan, status
    FROM v_karyawan
    WHERE (nama ILIKE :like_q OR nip ILIKE :q)
      AND (CAST(:dep AS text) IS NULL OR departemen ILIKE CAST(:like_dep AS text))
      AND (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
    ORDER BY nama
    LIMIT :limit
    """
)


class CariKaryawanArgs(BaseModel):
    query: str = Field(
        default="", description="nama atau NIP karyawan; kosongkan untuk semua"
    )
    departemen: str | None = Field(default=None, description="filter departemen")
    status: str | None = Field(
        default=None, description="filter status: aktif | cuti | nonaktif"
    )
    limit: int = Field(default=20, ge=1, le=100)


class CariKaryawan(Tool):
    name = "cari_karyawan"
    description = (
        "Cari data karyawan berdasarkan nama atau NIP. Bisa difilter per "
        "departemen dan status (aktif/cuti/nonaktif). Mengembalikan nama, NIP, "
        "departemen, jabatan, status. Tidak termasuk gaji atau NIK."
    )
    args_model = CariKaryawanArgs

    async def run(
        self, args: CariKaryawanArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        rows = await ctx.db.fetch(
            _SQL,
            {
                "q": args.query or "%",
                "like_q": f"%{args.query}%",
                "dep": args.departemen,
                "like_dep": f"%{args.departemen}%" if args.departemen else None,
                "status": args.status,
                "limit": args.limit,
            },
        )
        if not rows:
            return {"rows": [], "hint": "tidak ada karyawan yang cocok"}
        return {"rows": rows, "truncated": len(rows) == args.limit}
