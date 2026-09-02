from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.company_db import CompanyDbWriter
from app.db.models import StockMovement

_SEARCH = text(
    """
    SELECT id, nama, sku, qty, satuan, gudang
    FROM stok_barang
    WHERE nama ILIKE :q OR sku ILIKE :q
    ORDER BY nama
    LIMIT :limit
    """
)
_GET = text(
    "SELECT id, nama, sku, qty, satuan, gudang FROM stok_barang WHERE id = :id"
)
_INCREMENT = text(
    """
    UPDATE stok_barang SET qty = qty + :delta
    WHERE id = :id
    RETURNING nama, sku, gudang, qty AS qty_after, qty - :delta AS qty_before
    """
)
_INSERT = text(
    """
    INSERT INTO stok_barang (nama, sku, qty, satuan, gudang)
    VALUES (:nama, :sku, :qty, :satuan, :gudang)
    RETURNING id, nama, sku, gudang, qty AS qty_after
    """
)


async def search_products(
    writer: CompanyDbWriter, query: str, limit: int = 8
) -> list[dict[str, Any]]:
    return await writer.fetch(
        _SEARCH, {"q": f"%{query}%", "limit": limit}
    )


async def get_product(
    writer: CompanyDbWriter, product_id: int
) -> dict[str, Any] | None:
    rows = await writer.fetch(_GET, {"id": product_id})
    return rows[0] if rows else None


async def _log(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    aksi: str,
    sku: str,
    nama: str,
    delta: int,
    before: int,
    after: int,
    gudang: str | None,
    foto: str | None,
    catatan: str | None,
) -> None:
    session.add(
        StockMovement(
            tenant_id=tenant_id,
            user_id=user_id,
            aksi=aksi,
            product_sku=sku,
            product_nama=nama,
            delta_qty=delta,
            qty_before=before,
            qty_after=after,
            gudang=gudang,
            foto_file=foto,
            catatan=catatan,
        )
    )
    await session.flush()


async def receive_existing(
    writer: CompanyDbWriter,
    session: AsyncSession,
    *,
    product_id: int,
    delta: int,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    foto: str | None,
    catatan: str | None,
) -> dict[str, Any]:
    row = await writer.execute_returning(_INCREMENT, {"id": product_id, "delta": delta})
    if row is None:
        raise ValueError("produk tidak ditemukan")
    await _log(
        session,
        user_id=user_id, tenant_id=tenant_id, aksi="masuk",
        sku=row["sku"], nama=row["nama"], delta=delta,
        before=row["qty_before"], after=row["qty_after"],
        gudang=row["gudang"], foto=foto, catatan=catatan,
    )
    return {
        "nama": row["nama"], "sku": row["sku"], "gudang": row["gudang"],
        "qty_before": row["qty_before"], "qty_after": row["qty_after"],
    }


async def receive_new(
    writer: CompanyDbWriter,
    session: AsyncSession,
    *,
    nama: str,
    sku: str,
    satuan: str,
    gudang: str,
    qty: int,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    foto: str | None,
    catatan: str | None,
) -> dict[str, Any]:
    row = await writer.execute_returning(
        _INSERT,
        {"nama": nama, "sku": sku, "qty": qty, "satuan": satuan, "gudang": gudang},
    )
    assert row is not None
    await _log(
        session,
        user_id=user_id, tenant_id=tenant_id, aksi="baru",
        sku=row["sku"], nama=row["nama"], delta=qty, before=0, after=qty,
        gudang=row["gudang"], foto=foto, catatan=catatan,
    )
    return {
        "nama": row["nama"], "sku": row["sku"], "gudang": row["gudang"],
        "qty_before": 0, "qty_after": qty,
    }
