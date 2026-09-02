"""Whitelist of company views the assistant may read, plus runtime column
discovery.

Adding a new data source = create a VIEW in the company DB and add one line
to EXPOSED_VIEWS. No code changes.
"""
from __future__ import annotations

from sqlalchemy import text

from app.db.company_db import CompanyDbGateway

EXPOSED_VIEWS: dict[str, str] = {
    "v_stok": "Stok barang per gudang (nama, sku, qty, satuan, gudang)",
    "v_karyawan": "Data karyawan (nama, nip, departemen, jabatan, status)",
    "v_transaksi": (
        "Transaksi keuangan (tgl, no_transaksi, tipe [masuk/keluar], "
        "nominal, keterangan)"
    ),
}

_COLUMNS_SQL = text(
    """
    SELECT column_name, data_type
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = :view
    ORDER BY ordinal_position
    """
)
_MAX_DISTINCT = 12  # show sample values only for low-cardinality text columns

# process-lifetime caches
_cols_cache: dict[str, dict[str, str]] = {}
_vals_cache: dict[str, dict[str, list[str]]] = {}


async def columns_of(gateway: CompanyDbGateway, view: str) -> dict[str, str]:
    if view not in _cols_cache:
        rows = await gateway.fetch(_COLUMNS_SQL, {"view": view})
        _cols_cache[view] = {r["column_name"]: r["data_type"] for r in rows}
    return _cols_cache[view]


async def sample_values(
    gateway: CompanyDbGateway, view: str
) -> dict[str, list[str]]:
    """For each text column with <= _MAX_DISTINCT distinct values, the list."""
    if view in _vals_cache:
        return _vals_cache[view]
    cols = await columns_of(gateway, view)
    result: dict[str, list[str]] = {}
    for col, typ in cols.items():
        if typ not in ("text", "character varying", "character"):
            continue
        rows = await gateway.fetch(
            text(
                f'SELECT DISTINCT "{col}" AS v FROM {view} '
                f'WHERE "{col}" IS NOT NULL ORDER BY 1 LIMIT :n'
            ),
            {"n": _MAX_DISTINCT + 1},
        )
        vals = [r["v"] for r in rows]
        if 0 < len(vals) <= _MAX_DISTINCT:
            result[col] = vals
    _vals_cache[view] = result
    return result


async def describe_all(gateway: CompanyDbGateway) -> list[dict]:
    out = []
    for view, desc in EXPOSED_VIEWS.items():
        cols = await columns_of(gateway, view)
        vals = await sample_values(gateway, view)
        out.append(
            {
                "view": view,
                "deskripsi": desc,
                "kolom": [
                    {"nama": c, "tipe": t, **({"nilai": vals[c]} if c in vals else {})}
                    for c, t in cols.items()
                ],
            }
        )
    return out


async def format_for_prompt(gateway: CompanyDbGateway) -> str:
    lines = ["Data yang tersedia (pakai lewat tool `ambil_data`):"]
    for v in await describe_all(gateway):
        lines.append(f"\n• {v['view']} — {v['deskripsi']}")
        for c in v["kolom"]:
            extra = f"  nilai: {', '.join(c['nilai'])}" if "nilai" in c else ""
            lines.append(f"    - {c['nama']} ({c['tipe']}){extra}")
    return "\n".join(lines)


def clear_cache() -> None:
    _cols_cache.clear()
    _vals_cache.clear()
