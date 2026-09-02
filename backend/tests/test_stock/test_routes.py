from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import hash_password
from app.db.models import StockMovement, Tenant, User
from app.stock.ocr import GoodsData, OcrError

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF"


@pytest.fixture
async def auth(client: AsyncClient, db) -> dict[str, str]:
    tenant = Tenant(nama="Acme")
    db.add(tenant)
    await db.flush()
    db.add(
        User(
            tenant_id=tenant.id, email="gudang@acme.co",
            password_hash=hash_password("rahasia123"), nama="Petugas", role="user",
        )
    )
    await db.commit()
    r = await client.post(
        "/api/auth/login",
        json={"email": "gudang@acme.co", "password": "rahasia123"},
    )
    return {"Authorization": f"Bearer {r.json()['access']}"}


@pytest.fixture
def wire(monkeypatch, _engine, tmp_path, company_writer):
    maker = async_sessionmaker(_engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.app_db.get_sessionmaker", lambda: maker)
    monkeypatch.setattr("app.stock.routes._upload_dir", lambda: tmp_path)
    monkeypatch.setattr(
        "app.stock.routes.get_company_writer", lambda: company_writer
    )

    def set_ocr(result):
        async def _fake(image_bytes, media_type):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr("app.stock.routes.extract_goods", _fake)

    return set_ocr


async def _ocr(client, auth, wire, goods):
    wire(goods)
    return await client.post(
        "/api/stock/ocr", headers=auth,
        files={"file": ("barang.jpg", JPEG + b"x", "image/jpeg")},
    )


async def test_ocr_returns_goods_and_candidates(client, auth, wire) -> None:
    resp = await _ocr(
        client, auth, wire,
        GoodsData(produk="kabel", merk=None, ukuran="usb", jumlah=5, satuan="pcs"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["produk"] == "kabel"
    assert body["jumlah"] == 5
    # "kabel usb" matches seeded products
    assert any("Kabel" in k["nama"] for k in body["kandidat"])
    assert body["foto_ref"].endswith(".jpg")


async def test_ocr_unrecognized(client, auth, wire) -> None:
    resp = await _ocr(client, auth, wire, OcrError("label tidak jelas"))
    assert resp.status_code == 422


async def test_receive_existing_updates_stock(client, auth, wire, db, company_writer) -> None:
    o = await _ocr(
        client, auth, wire,
        GoodsData(produk="adaptor", merk=None, ukuran="20W", jumlah=10, satuan="pcs"),
    )
    prod = (await company_writer.fetch(
        text("SELECT id FROM stok_barang WHERE sku='ADP-20W'"), {}
    ))[0]

    r = await client.post(
        "/api/stock/receive", headers=auth,
        json={
            "mode": "existing", "foto_ref": o.json()["foto_ref"],
            "product_id": prod["id"], "jumlah": 10,
        },
    )
    body = r.json()
    assert body["status"] == "ok"
    assert body["qty_before"] == 8 and body["qty_after"] == 18

    n = (await db.execute(select(func.count()).select_from(StockMovement))).scalar_one()
    assert n == 1


async def test_receive_new_creates_product(client, auth, wire, db, company_writer) -> None:
    o = await _ocr(
        client, auth, wire,
        GoodsData(produk="cat tembok", merk="Dulux", ukuran="5kg", jumlah=12, satuan="kaleng"),
    )
    r = await client.post(
        "/api/stock/receive", headers=auth,
        json={
            "mode": "new", "foto_ref": o.json()["foto_ref"], "jumlah": 12,
            "nama": "Cat Tembok Dulux 5kg", "sku": "CAT-DLX-5",
            "satuan": "kaleng", "gudang": "Gudang A",
        },
    )
    assert r.json()["qty_after"] == 12
    row = (await company_writer.fetch(
        text("SELECT qty FROM stok_barang WHERE sku='CAT-DLX-5'"), {}
    ))[0]
    assert row["qty"] == 12


async def test_receive_new_missing_fields(client, auth, wire) -> None:
    o = await _ocr(client, auth, wire, GoodsData(produk="x", jumlah=1))
    r = await client.post(
        "/api/stock/receive", headers=auth,
        json={"mode": "new", "foto_ref": o.json()["foto_ref"], "jumlah": 1,
              "nama": "X"},
    )
    assert r.status_code == 422


async def test_receive_bad_foto_ref(client, auth, wire) -> None:
    wire(GoodsData(produk="x", jumlah=1))
    r = await client.post(
        "/api/stock/receive", headers=auth,
        json={"mode": "existing", "foto_ref": "../x", "product_id": 1, "jumlah": 1},
    )
    assert r.status_code == 400


async def test_requires_auth(client, wire) -> None:
    r = await client.post(
        "/api/stock/ocr",
        files={"file": ("a.jpg", JPEG, "image/jpeg")},
    )
    assert r.status_code == 401
