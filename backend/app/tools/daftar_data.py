from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from app.tools.base import Tool, ToolContext
from app.tools.schema import describe_all


class DaftarDataArgs(BaseModel):
    pass


class DaftarData(Tool):
    name = "daftar_data"
    description = (
        "Lihat data apa saja yang bisa diakses: daftar tabel/view perusahaan "
        "beserta deskripsi dan nama kolomnya. Panggil ini lebih dulu bila "
        "belum yakin sumber data mana yang dipakai."
    )
    args_model = DaftarDataArgs

    async def run(
        self, args: DaftarDataArgs, ctx: ToolContext
    ) -> dict[str, Any]:
        return {"sumber_data": await describe_all(ctx.db)}
