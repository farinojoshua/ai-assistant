"""Now-playing / upcoming movie lookup via the SAMS Studios API.

Separate from ambil_data/daftar_data (those are scoped to company_db
views) and from the WA ticket_flow state machine (that's a guided booking
conversation, not a single query) — this is a plain read-only lookup the
chat agent can call on either channel.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.sams import client as sams
from app.sams.client import SamsApiError
from app.tools.base import Tool, ToolContext


class FilmBioskopArgs(BaseModel):
    kategori: Literal["now_playing", "upcoming"] = Field(
        description="'now_playing' untuk film yang sedang tayang, "
        "'upcoming' untuk film yang akan datang"
    )


class FilmBioskop(Tool):
    name = "film_bioskop"
    description = (
        "Lihat daftar film yang sedang tayang (now_playing) atau akan "
        "datang (upcoming) di bioskop SAMS Studios. Tidak butuh argumen "
        "lain selain kategori."
    )
    args_model = FilmBioskopArgs

    async def run(self, args: FilmBioskopArgs, ctx: ToolContext) -> dict[str, Any]:
        try:
            movies = (
                await sams.list_now_playing()
                if args.kategori == "now_playing"
                else await sams.list_upcoming()
            )
        except SamsApiError as e:
            return {"error": "gagal ambil data film", "hint": e.message}

        return {
            "film": [
                {
                    "judul": m.get("movie_name"),
                    "rating": m.get("rating_name"),
                    "genre": m.get("genre") or m.get("movie_type"),
                }
                for m in movies
            ]
        }
