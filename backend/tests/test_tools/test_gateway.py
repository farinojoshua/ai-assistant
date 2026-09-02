from __future__ import annotations

from sqlalchemy import text

from app.db.company_db import CompanyDbGateway


def test_gateway_exposes_no_write_path() -> None:
    public = {n for n in dir(CompanyDbGateway) if not n.startswith("_")}
    assert public == {"fetch", "from_settings", "dispose"}


async def test_fetch_is_parameterized(company_gateway: CompanyDbGateway) -> None:
    rows = await company_gateway.fetch(
        text("SELECT sku FROM v_stok WHERE sku = :sku"),
        {"sku": "FD-64"},
    )
    assert rows == [{"sku": "FD-64"}]


async def test_fetch_returns_plain_dicts(
    company_gateway: CompanyDbGateway,
) -> None:
    rows = await company_gateway.fetch(text("SELECT nama, qty FROM v_stok LIMIT 1"))
    assert isinstance(rows[0], dict)
    assert set(rows[0]) == {"nama", "qty"}
