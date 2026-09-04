from __future__ import annotations

from app.llm.base import ToolSpec
from app.tools.ambil_data import AmbilData
from app.tools.base import Tool
from app.tools.daftar_data import DaftarData
from app.tools.film_bioskop import FilmBioskop
from app.tools.riwayat_lokasi import RiwayatLokasi

_TOOLS: list[Tool] = [DaftarData(), AmbilData(), RiwayatLokasi(), FilmBioskop()]

_BY_NAME: dict[str, Tool] = {t.name: t for t in _TOOLS}


def all_tools() -> list[Tool]:
    return list(_TOOLS)


def all_specs() -> list[ToolSpec]:
    return [t.spec for t in _TOOLS]


def get(name: str) -> Tool | None:
    return _BY_NAME.get(name)
