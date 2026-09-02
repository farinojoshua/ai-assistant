from __future__ import annotations

import uuid
from datetime import date

import pytest
from pydantic import ValidationError

from app.db.models import User
from app.tools.base import ToolContext
from app.tools.cari_transaksi import CariTransaksi, CariTransaksiArgs

AGT = date(2026, 8, 1)
AKH = date(2026, 8, 31)


@pytest.fixture
def ctx(company_gateway) -> ToolContext:
    tid = uuid.uuid4()
    user = User(
        id=uuid.uuid4(), tenant_id=tid, email="u@t", password_hash="x",
        nama="U", role="user",
    )
    return ToolContext(user=user, tenant_id=tid, db=company_gateway)


async def test_full_month(ctx) -> None:
    out = await CariTransaksi().run(CariTransaksiArgs(dari=AGT, sampai=AKH), ctx)
    assert len(out["rows"]) == 10
    tipes = {r["tipe"]: r for r in out["ringkasan"]}
    assert int(tipes["masuk"]["jumlah"]) == 6
    assert int(tipes["keluar"]["jumlah"]) == 4


async def test_filter_tipe_keluar(ctx) -> None:
    out = await CariTransaksi().run(
        CariTransaksiArgs(dari=AGT, sampai=AKH, tipe="keluar"), ctx
    )
    assert all(r["tipe"] == "keluar" for r in out["rows"])
    assert len(out["rows"]) == 4


async def test_min_nominal(ctx) -> None:
    out = await CariTransaksi().run(
        CariTransaksiArgs(dari=AGT, sampai=AKH, min_nominal=15_000_000), ctx
    )
    assert all(float(r["nominal"]) >= 15_000_000 for r in out["rows"])
    assert len(out["rows"]) == 2  # TRX-0001 (15jt) + TRX-0006 (21jt)


async def test_narrow_range_empty(ctx) -> None:
    out = await CariTransaksi().run(
        CariTransaksiArgs(dari=date(2026, 1, 1), sampai=date(2026, 1, 2)), ctx
    )
    assert out["rows"] == [] and "hint" in out


def test_bad_range_rejected() -> None:
    with pytest.raises(ValidationError):
        CariTransaksiArgs(dari=AKH, sampai=AGT)


def test_spec_has_date_format() -> None:
    spec = CariTransaksi().spec
    assert spec.input_schema["properties"]["dari"]["format"] == "date"
