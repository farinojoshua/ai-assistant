from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.db.models import User
from app.tools.ambil_data import AmbilData, AmbilDataArgs
from app.tools.base import ToolContext
from app.tools.daftar_data import DaftarData, DaftarDataArgs
from app.tools.schema import clear_cache


@pytest.fixture
def ctx(company_gateway) -> ToolContext:
    clear_cache()
    tid = uuid.uuid4()
    user = User(
        id=uuid.uuid4(), tenant_id=tid, email="u@t", password_hash="x",
        nama="U", role="user",
    )
    return ToolContext(user=user, tenant_id=tid, db=company_gateway)


async def test_daftar_data_lists_views_and_columns(ctx) -> None:
    out = await DaftarData().run(DaftarDataArgs(), ctx)
    views = {v["view"]: v for v in out["sumber_data"]}
    assert set(views) == {"v_stok", "v_karyawan", "v_transaksi"}
    stok_cols = {c["nama"] for c in views["v_stok"]["kolom"]}
    assert stok_cols == {"nama", "sku", "qty", "satuan", "gudang"}
    # sensitive columns never surface
    assert "harga_beli" not in stok_cols


async def test_simple_filter(ctx) -> None:
    out = await AmbilData().run(
        AmbilDataArgs(
            view="v_stok",
            filter=[{"kolom": "nama", "operator": "contains", "nilai": "kabel"}],
        ),
        ctx,
    )
    assert all("kabel" in r["nama"].lower() for r in out["rows"])
    assert len(out["rows"]) == 4


async def test_numeric_filter_and_projection(ctx) -> None:
    out = await AmbilData().run(
        AmbilDataArgs(
            view="v_stok",
            filter=[{"kolom": "qty", "operator": "<", "nilai": 10}],
            kolom=["nama", "qty"],
            urut={"kolom": "qty", "arah": "asc"},
        ),
        ctx,
    )
    assert [r["nama"] for r in out["rows"]][0] == "Adaptor Charger 65W"
    assert set(out["rows"][0]) == {"nama", "qty"}


async def test_aggregate_sum_group_by(ctx) -> None:
    out = await AmbilData().run(
        AmbilDataArgs(
            view="v_transaksi",
            filter=[
                {"kolom": "tgl", "operator": ">=", "nilai": "2026-08-01"},
                {"kolom": "tgl", "operator": "<=", "nilai": "2026-08-31"},
            ],
            agregasi={"fungsi": "sum", "kolom": "nominal", "group_by": "tipe"},
        ),
        ctx,
    )
    by = {r["grup"]: float(r["hasil"]) for r in out["agregasi"]}
    assert by["masuk"] == 68_400_000
    assert by["keluar"] == 27_800_000


async def test_aggregate_count(ctx) -> None:
    out = await AmbilData().run(
        AmbilDataArgs(
            view="v_karyawan",
            filter=[{"kolom": "departemen", "operator": "=", "nilai": "Gudang"}],
            agregasi={"fungsi": "count"},
        ),
        ctx,
    )
    assert int(out["agregasi"][0]["hasil"]) == 3


async def test_unknown_view_rejected(ctx) -> None:
    out = await AmbilData().run(AmbilDataArgs(view="v_gaji_rahasia"), ctx)
    assert "tidak tersedia" in out["error"]
    assert "v_stok" in out["hint"]["view_tersedia"]


async def test_unknown_column_rejected(ctx) -> None:
    out = await AmbilData().run(
        AmbilDataArgs(
            view="v_stok",
            filter=[{"kolom": "harga_beli", "operator": ">", "nilai": 0}],
        ),
        ctx,
    )
    assert "harga_beli" in out["error"]
    assert "kolom_valid" in out["hint"]


async def test_no_rows_hint(ctx) -> None:
    out = await AmbilData().run(
        AmbilDataArgs(
            view="v_stok",
            filter=[{"kolom": "nama", "operator": "=", "nilai": "tidak-ada"}],
        ),
        ctx,
    )
    assert out["rows"] == [] and "hint" in out


def test_limit_validation() -> None:
    with pytest.raises(ValidationError):
        AmbilDataArgs(view="v_stok", limit=500)


def test_specs_registered() -> None:
    from app.tools import registry

    names = {t.name for t in registry.all_tools()}
    assert names == {"daftar_data", "ambil_data"}
