"""Look up the locations this user has shared via WhatsApp.

Separate from ambil_data/daftar_data since this reads app_db (wa_locations)
rather than the company_db views those two are scoped to.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.db.app_db import get_sessionmaker
from app.db.models import WaLocation
from app.tools.base import Tool, ToolContext

_TZ = ZoneInfo("Asia/Jakarta")


class RiwayatLokasiArgs(BaseModel):
    tanggal: str | None = Field(
        default=None,
        description="Tanggal spesifik, format YYYY-MM-DD. Default hari ini "
        "kalau semua argumen kosong.",
    )
    dari_tanggal: str | None = Field(
        default=None, description="Awal rentang tanggal, format YYYY-MM-DD"
    )
    sampai_tanggal: str | None = Field(
        default=None, description="Akhir rentang tanggal, format YYYY-MM-DD"
    )
    limit: int = Field(default=50, ge=1, le=200)


class RiwayatLokasi(Tool):
    name = "riwayat_lokasi"
    description = (
        "Ambil riwayat lokasi yang pernah dibagikan user ini lewat WhatsApp "
        "(fitur share location). Pakai 'tanggal' untuk satu hari spesifik "
        "(mis. 'hari ini saya ke mana aja' -> tanggal hari ini), atau "
        "'dari_tanggal'/'sampai_tanggal' untuk rentang. Tanpa argumen = hari ini."
    )
    args_model = RiwayatLokasiArgs

    async def run(self, args: RiwayatLokasiArgs, ctx: ToolContext) -> dict[str, Any]:
        if args.tanggal:
            start_d = end_d = date.fromisoformat(args.tanggal)
        elif args.dari_tanggal or args.sampai_tanggal:
            today = datetime.now(_TZ).date()
            start_d = (
                date.fromisoformat(args.dari_tanggal) if args.dari_tanggal else today
            )
            end_d = (
                date.fromisoformat(args.sampai_tanggal)
                if args.sampai_tanggal
                else today
            )
        else:
            start_d = end_d = datetime.now(_TZ).date()

        start_dt = datetime.combine(start_d, time.min, tzinfo=_TZ)
        end_dt = datetime.combine(end_d, time.max, tzinfo=_TZ)

        async with get_sessionmaker()() as session:
            rows = (
                (
                    await session.execute(
                        select(WaLocation)
                        .where(
                            WaLocation.user_id == ctx.user.id,
                            WaLocation.created_at >= start_dt,
                            WaLocation.created_at <= end_dt,
                        )
                        .order_by(WaLocation.created_at)
                        .limit(args.limit)
                    )
                )
                .scalars()
                .all()
            )

        if not rows:
            return {"lokasi": [], "hint": "tidak ada lokasi tersimpan pada rentang ini"}

        return {
            "lokasi": [
                {
                    "waktu": r.created_at.astimezone(_TZ).isoformat(),
                    "alamat": r.address or r.name,
                    "latitude": r.latitude,
                    "longitude": r.longitude,
                }
                for r in rows
            ]
        }
