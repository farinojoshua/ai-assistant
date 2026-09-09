"""Now-playing / upcoming movie lookup via the SAMS Studios API.

Separate from ambil_data/daftar_data (those are scoped to company_db
views) and from the WA ticket_flow state machine (that's a guided booking
conversation, not a single query) — this is a plain read-only lookup the
chat agent can call on either channel.
"""
from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.sams import client as sams
from app.sams.client import SamsApiError
from app.tools.base import Tool, ToolContext

# Titles just shown to a user, so a follow-up like "mau dong baby udon" can
# be recognized deterministically (as a booking intent for a real, just-
# mentioned title) instead of relying on the LLM to notice on its own —
# see app/whatsapp/ticket_flow.py's should_start(). Global, not per-user:
# the movie catalog is the same for everyone, TTL just bounds staleness.
_RECENT_TTL_S = 600
_recent_titles: dict[str, float] = {}


def _remember_titles(movies: list[dict]) -> None:
    now = time.monotonic()
    for m in movies:
        title = m.get("movie_name")
        if title:
            _recent_titles[title] = now


def recent_titles() -> list[str]:
    now = time.monotonic()
    return [t for t, seen_at in _recent_titles.items() if now - seen_at < _RECENT_TTL_S]


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

        _remember_titles(movies)
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
