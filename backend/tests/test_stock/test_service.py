from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db.models import StockMovement
from app.stock import service


@pytest.fixture
def ids() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()  # tenant, user


async def test_search_products(company_writer) -> None:
    rows = await service.search_products(company_writer, "kabel")
    assert len(rows) == 4
    assert all("kabel" in r["nama"].lower() for r in rows)


async def test_receive_existing_increments_and_logs(
    company_writer, db: AsyncSession, ids
) -> None:
    tenant, user = ids
    # ADP-20W starts at qty 8
    prod = (await company_writer.fetch(
        text("SELECT id, qty FROM stok_barang WHERE sku='ADP-20W'"), {}
    ))[0]

    result = await service.receive_existing(
        company_writer, db,
        product_id=prod["id"], delta=10,
        user_id=user, tenant_id=tenant, foto="f.jpg", catatan=None,
    )
    await db.commit()

    assert result["qty_before"] == 8
    assert result["qty_after"] == 18
    assert result["sku"] == "ADP-20W"

    now = (await company_writer.fetch(
        text("SELECT qty FROM stok_barang WHERE sku='ADP-20W'"), {}
    ))[0]
    assert now["qty"] == 18

    mv = (await db.execute(select(StockMovement))).scalar_one()
    assert mv.aksi == "masuk"
    assert (mv.delta_qty, mv.qty_before, mv.qty_after) == (10, 8, 18)


async def test_receive_new_inserts_and_logs(
    company_writer, db: AsyncSession, ids
) -> None:
    tenant, user = ids
    result = await service.receive_new(
        company_writer, db,
        nama="Cat Tembok Putih 5kg", sku="CAT-PTH-5", satuan="kaleng",
        gudang="Gudang A", qty=10,
        user_id=user, tenant_id=tenant, foto="f.jpg", catatan="stok awal",
    )
    await db.commit()

    assert result["qty_before"] == 0
    assert result["qty_after"] == 10

    row = (await company_writer.fetch(
        text("SELECT nama, qty, satuan FROM stok_barang WHERE sku='CAT-PTH-5'"), {}
    ))[0]
    assert row["nama"] == "Cat Tembok Putih 5kg"
    assert row["qty"] == 10

    mv = (await db.execute(select(StockMovement))).scalar_one()
    assert mv.aksi == "baru"
    assert mv.qty_before == 0 and mv.qty_after == 10


async def test_receive_existing_unknown_id(company_writer, db, ids) -> None:
    tenant, user = ids
    with pytest.raises(ValueError):
        await service.receive_existing(
            company_writer, db,
            product_id=999999, delta=1,
            user_id=user, tenant_id=tenant, foto=None, catatan=None,
        )
