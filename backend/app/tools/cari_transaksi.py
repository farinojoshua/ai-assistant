from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from app.tools.base import Tool, ToolContext

_SQL = text(
    """
    SELECT tgl, no_transaksi, tipe, nominal, keterangan
    FROM v_transaksi
    WHERE tgl BETWEEN :dari AND :sampai
      AND (CAST(:tipe AS text) IS NULL OR tipe = CAST(:tipe AS text))
      AND (CAST(:min_nominal AS numeric) IS NULL
           OR nominal >= CAST(:min_nominal AS numeric))
    ORDER BY tgl DESC
    LIMIT :limit
    """
)
_SUM_SQL = text(
    """
    SELECT tipe, COUNT(*) AS jumlah, SUM(nominal) AS total
    FROM v_transaksi
    WHERE tgl BETWEEN :dari AND :sampai
    GROUP BY tipe
    """
)


class CariTransaksiArgs(BaseModel):
    dari: date = Field(description="tanggal mulai (YYYY-MM-DD), inklusif")
    sampai: date = Field(description="tanggal akhir (YYYY-MM-DD), inklusif")
    tipe: str | None = Field(default=None, description="filter: masuk | keluar")
    min_nominal: float | None = Field(
        default=None, ge=0, description="nominal minimum"
    )
    limit: int = Field(default=50, ge=1, le=200)

    @model_validator(mode="after")
    def _check_range(self) -> "CariTransaksiArgs":
        if self.sampai < self.dari:
            raise ValueError("'sampai' harus >= 'dari'")
        return self


class CariTransaksi(Tool):
    name = "cari_transaksi"
    description = (
        "Cari transaksi keuangan dalam rentang tanggal. Bisa difilter tipe "
        "(masuk/keluar) dan nominal minimum. Mengembalikan daftar transaksi "
        "plus ringkasan jumlah & total per tipe untuk rentang itu."
    )
    args_model = CariTransaksiArgs

    async def run(
        self, args: CariTransaksiArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        params = {
            "dari": args.dari,
            "sampai": args.sampai,
            "tipe": args.tipe,
            "min_nominal": args.min_nominal,
            "limit": args.limit,
        }
        rows = await ctx.db.fetch(_SQL, params)
        ringkasan = await ctx.db.fetch(
            _SUM_SQL, {"dari": args.dari, "sampai": args.sampai}
        )
        if not rows:
            return {
                "rows": [],
                "ringkasan": ringkasan,
                "hint": "tidak ada transaksi pada rentang/filter itu",
            }
        return {
            "rows": rows,
            "ringkasan": ringkasan,
            "truncated": len(rows) == args.limit,
        }
