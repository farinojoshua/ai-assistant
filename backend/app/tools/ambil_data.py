from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import text

from app.tools.base import Tool, ToolContext
from app.tools.schema import EXPOSED_VIEWS, columns_of

Operator = Literal["=", "!=", ">", ">=", "<", "<=", "contains"]

_OP_SQL: dict[str, str] = {
    "=": "=",
    "!=": "<>",
    ">": ">",
    ">=": ">=",
    "<": "<",
    "<=": "<=",
}


_KOLOM_KEYS = ("kolom", "col", "column", "field", "name")
_OP_KEYS = ("operator", "op", "operation")
_NILAI_KEYS = ("nilai", "value", "val", "v")
_FUNGSI = ("sum", "count", "avg", "min", "max")


class Filter(BaseModel):
    kolom: str
    operator: Operator
    nilai: str | float | int | bool

    @model_validator(mode="before")
    @classmethod
    def _accept_variants(cls, v):
        # ["kolom", "op", "nilai"]
        if isinstance(v, (list, tuple)) and len(v) == 3:
            return {"kolom": v[0], "operator": v[1], "nilai": v[2]}
        if isinstance(v, dict):
            out = dict(v)
            for keys, canon in (
                (_KOLOM_KEYS, "kolom"),
                (_OP_KEYS, "operator"),
                (_NILAI_KEYS, "nilai"),
            ):
                if canon not in out:
                    for k in keys:
                        if k in out:
                            out[canon] = out.pop(k)
                            break
            return out
        return v


class Urut(BaseModel):
    kolom: str
    arah: Literal["asc", "desc"] = "asc"

    @model_validator(mode="before")
    @classmethod
    def _accept_variants(cls, v):
        if isinstance(v, str):
            return {"kolom": v}
        if isinstance(v, dict):
            out = dict(v)
            for k in _KOLOM_KEYS:
                if k in out and "kolom" not in out:
                    out["kolom"] = out.pop(k)
            for k in ("arah", "order", "direction", "dir"):
                if k in out and "arah" not in out:
                    out["arah"] = out.pop(k)
            return out
        return v


class Agregasi(BaseModel):
    fungsi: Literal["sum", "count", "avg", "min", "max"]
    kolom: str | None = Field(
        default=None, description="wajib kecuali fungsi 'count'"
    )
    group_by: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_variants(cls, v):
        if not isinstance(v, dict):
            return v
        out = dict(v)
        # {"sum": "qty"} or {"sum": ["qty"]}
        if "fungsi" not in out:
            for f in _FUNGSI:
                if f in out:
                    val = out.pop(f)
                    out["fungsi"] = f
                    if val not in (None, True, [], "") and "kolom" not in out:
                        out["kolom"] = val[0] if isinstance(val, list) else val
                    break
        for k in _KOLOM_KEYS:
            if k in out and "kolom" not in out:
                out["kolom"] = out.pop(k)
        if isinstance(out.get("kolom"), list):
            out["kolom"] = out["kolom"][0] if out["kolom"] else None
        for k in ("group_by", "groupby", "group", "per"):
            if k in out and "group_by" not in out:
                out["group_by"] = out.pop(k)
        return out


class AmbilDataArgs(BaseModel):
    view: str = Field(description="nama view, lihat daftar_data")
    filter: list[Filter] = Field(default_factory=list)
    kolom: list[str] | None = Field(
        default=None, description="kolom yang diambil; default semua"
    )
    urut: Urut | None = None
    agregasi: Agregasi | None = None
    limit: int = Field(default=50, ge=1, le=200)


def _err(msg: str, hint: Any = None) -> dict[str, Any]:
    out: dict[str, Any] = {"error": msg}
    if hint is not None:
        out["hint"] = hint
    return out


class AmbilData(Tool):
    name = "ambil_data"
    description = (
        "Ambil baris dari sebuah view perusahaan. Bentuk argumen:\n"
        '  view: "v_stok"\n'
        '  filter: [{"kolom": "gudang", "operator": "=", "nilai": "Gudang B"}]\n'
        "  operator: = != > >= < <= contains (contains = cocok sebagian teks)\n"
        '  kolom: ["nama","qty"]  (opsional, default semua)\n'
        '  urut: {"kolom": "qty", "arah": "asc"}  (opsional)\n'
        '  agregasi: {"fungsi": "sum", "kolom": "nominal", "group_by": "tipe"}\n'
        "    (opsional; fungsi: sum/count/avg/min/max)\n"
        "Untuk pertanyaan 'total/berapa/rata-rata' pakai agregasi, jangan "
        "tarik semua baris lalu hitung sendiri."
    )
    args_model = AmbilDataArgs

    async def run(self, args: AmbilDataArgs, ctx: ToolContext) -> dict[str, Any]:
        if args.view not in EXPOSED_VIEWS:
            return _err(
                f"view {args.view!r} tidak tersedia",
                {"view_tersedia": list(EXPOSED_VIEWS)},
            )
        cols = await columns_of(ctx.db, args.view)

        referenced = [f.kolom for f in args.filter]
        referenced += args.kolom or []
        if args.urut:
            referenced.append(args.urut.kolom)
        if args.agregasi:
            if args.agregasi.kolom:
                referenced.append(args.agregasi.kolom)
            if args.agregasi.group_by:
                referenced.append(args.agregasi.group_by)
        unknown = sorted({c for c in referenced if c not in cols})
        if unknown:
            return _err(
                f"kolom tidak dikenal: {unknown}",
                {"kolom_valid": list(cols)},
            )

        params: dict[str, Any] = {"_limit": args.limit}
        where_parts: list[str] = []
        for i, f in enumerate(args.filter):
            p = f"p{i}"
            if f.operator == "contains":
                where_parts.append(f'"{f.kolom}"::text ILIKE :{p}')
                params[p] = f"%{f.nilai}%"
            else:
                where_parts.append(f'"{f.kolom}" {_OP_SQL[f.operator]} :{p}')
                params[p] = f.nilai
        where = f" WHERE {' AND '.join(where_parts)}" if where_parts else ""

        if args.agregasi:
            ag = args.agregasi
            if ag.fungsi == "count":
                expr = "COUNT(*)"
            else:
                if not ag.kolom:
                    return _err(f"fungsi {ag.fungsi!r} butuh 'kolom'")
                expr = f'{ag.fungsi.upper()}("{ag.kolom}")'
            if ag.group_by:
                sql = (
                    f'SELECT "{ag.group_by}" AS grup, {expr} AS hasil '
                    f'FROM {args.view}{where} GROUP BY "{ag.group_by}" '
                    f'ORDER BY "{ag.group_by}"'
                )
            else:
                sql = f"SELECT {expr} AS hasil FROM {args.view}{where}"
            rows = await ctx.db.fetch(text(sql), params)
            return {"agregasi": rows}

        projection = (
            ", ".join(f'"{c}"' for c in args.kolom) if args.kolom else "*"
        )
        order = ""
        if args.urut:
            order = f' ORDER BY "{args.urut.kolom}" {args.urut.arah.upper()}'
        sql = f"SELECT {projection} FROM {args.view}{where}{order} LIMIT :_limit"
        rows = await ctx.db.fetch(text(sql), params)
        if not rows:
            return {"rows": [], "hint": "tidak ada baris yang cocok"}
        return {"rows": rows, "truncated": len(rows) == args.limit}
