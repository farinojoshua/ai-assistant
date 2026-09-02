from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.db.models import User
from app.tools.cek_stok import CekStok, CekStokArgs
from app.tools.base import ToolContext


@pytest.fixture
def ctx(company_gateway) -> ToolContext:
    tenant_id = uuid.uuid4()
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        email="u@test",
        password_hash="x",
        nama="U",
        role="user",
    )
    return ToolContext(user=user, tenant_id=tenant_id, db=company_gateway)


async def test_by_name(ctx: ToolContext) -> None:
    out = await CekStok().run(CekStokArgs(query="kabel"), ctx)
    names = [r["nama"] for r in out["rows"]]
    assert any("Kabel" in n for n in names)
    assert all("Kabel" in r["nama"] for r in out["rows"])
    assert out["truncated"] is False
    # view must not leak the sensitive column
    assert "harga_beli" not in out["rows"][0]


async def test_by_sku(ctx: ToolContext) -> None:
    out = await CekStok().run(CekStokArgs(query="KBL-USBC-1M"), ctx)
    assert len(out["rows"]) == 1
    assert out["rows"][0]["sku"] == "KBL-USBC-1M"
    assert out["rows"][0]["qty"] == 40


async def test_gudang_filter(ctx: ToolContext) -> None:
    out = await CekStok().run(
        CekStokArgs(query="kabel", gudang="Gudang B"), ctx
    )
    assert out["rows"]
    assert all(r["gudang"] == "Gudang B" for r in out["rows"])


async def test_not_found(ctx: ToolContext) -> None:
    out = await CekStok().run(CekStokArgs(query="pesawat terbang"), ctx)
    assert out["rows"] == []
    assert "hint" in out


async def test_limit_enforced_and_truncated_flag(ctx: ToolContext) -> None:
    out = await CekStok().run(CekStokArgs(query="a", limit=3), ctx)
    assert len(out["rows"]) == 3
    assert out["truncated"] is True


def test_limit_validation() -> None:
    with pytest.raises(ValidationError):
        CekStokArgs(query="x", limit=999)
    with pytest.raises(ValidationError):
        CekStokArgs(query="x", limit=0)


def test_spec_shape() -> None:
    spec = CekStok().spec
    assert spec.name == "cek_stok"
    assert spec.input_schema["properties"]["query"]["type"] == "string"
    assert "limit" in spec.input_schema["properties"]


async def test_empty_query_returns_all(ctx: ToolContext) -> None:
    out = await CekStok().run(CekStokArgs(query=""), ctx)
    assert len(out["rows"]) == 15
