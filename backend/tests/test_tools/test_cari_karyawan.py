from __future__ import annotations

import uuid

import pytest

from app.db.models import User
from app.tools.base import ToolContext
from app.tools.cari_karyawan import CariKaryawan, CariKaryawanArgs


@pytest.fixture
def ctx(company_gateway) -> ToolContext:
    tid = uuid.uuid4()
    user = User(
        id=uuid.uuid4(), tenant_id=tid, email="u@t", password_hash="x",
        nama="U", role="user",
    )
    return ToolContext(user=user, tenant_id=tid, db=company_gateway)


async def test_by_name(ctx) -> None:
    out = await CariKaryawan().run(CariKaryawanArgs(query="budi"), ctx)
    assert out["rows"][0]["nama"] == "Budi Santoso"
    assert "gaji" not in out["rows"][0] and "nik" not in out["rows"][0]


async def test_by_nip(ctx) -> None:
    out = await CariKaryawan().run(CariKaryawanArgs(query="EMP-004"), ctx)
    assert len(out["rows"]) == 1
    assert out["rows"][0]["departemen"] == "Keuangan"


async def test_filter_departemen(ctx) -> None:
    out = await CariKaryawan().run(
        CariKaryawanArgs(query="", departemen="Gudang"), ctx
    )
    assert len(out["rows"]) == 3
    assert all(r["departemen"] == "Gudang" for r in out["rows"])


async def test_filter_status(ctx) -> None:
    out = await CariKaryawan().run(CariKaryawanArgs(status="cuti"), ctx)
    assert [r["nama"] for r in out["rows"]] == ["Ahmad Fauzi"]


async def test_not_found(ctx) -> None:
    out = await CariKaryawan().run(CariKaryawanArgs(query="zzz"), ctx)
    assert out["rows"] == [] and "hint" in out


def test_spec() -> None:
    spec = CariKaryawan().spec
    assert spec.name == "cari_karyawan"
    assert "departemen" in spec.input_schema["properties"]
