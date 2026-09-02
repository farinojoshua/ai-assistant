from __future__ import annotations

from app.llm.base import ToolSpec
from app.tools.base import Tool
from app.tools.cari_karyawan import CariKaryawan
from app.tools.cari_transaksi import CariTransaksi
from app.tools.cek_stok import CekStok

_TOOLS: list[Tool] = [CekStok(), CariKaryawan(), CariTransaksi()]

_BY_NAME: dict[str, Tool] = {t.name: t for t in _TOOLS}


def all_tools() -> list[Tool]:
    return list(_TOOLS)


def all_specs() -> list[ToolSpec]:
    return [t.spec for t in _TOOLS]


def get(name: str) -> Tool | None:
    return _BY_NAME.get(name)
