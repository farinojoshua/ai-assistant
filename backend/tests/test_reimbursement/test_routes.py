from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import hash_password
from app.db.models import Reimbursement, Tenant, User
from app.reimbursement.ocr import OcrError, ReceiptData


@pytest.fixture
async def auth(client: AsyncClient, db) -> dict[str, str]:
    tenant = Tenant(nama="Acme")
    db.add(tenant)
    await db.flush()
    db.add(
        User(
            tenant_id=tenant.id,
            email="karyawan@acme.co",
            password_hash=hash_password("rahasia123"),
            nama="Karyawan",
            role="user",
        )
    )
    await db.commit()
    r = await client.post(
        "/api/auth/login",
        json={"email": "karyawan@acme.co", "password": "rahasia123"},
    )
    return {"Authorization": f"Bearer {r.json()['access']}"}


@pytest.fixture
def wire(monkeypatch, _engine, tmp_path):
    """Point the route's DB session + upload dir at test resources, and let
    a test install a fake OCR result."""
    maker = async_sessionmaker(_engine, expire_on_commit=False)
    monkeypatch.setattr("app.db.app_db.get_sessionmaker", lambda: maker)
    monkeypatch.setattr(
        "app.reimbursement.routes._upload_dir", lambda: tmp_path
    )

    def set_ocr(result):
        async def _fake(image_bytes, media_type):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(
            "app.reimbursement.routes.extract_receipt", _fake
        )

    return set_ocr


async def _do_ocr(client, auth, wire, receipt):
    wire(receipt)
    return await client.post(
        "/api/reimbursement/ocr",
        headers=auth,
        files={"file": ("struk.jpg", b"fakejpegbytes", "image/jpeg")},
    )


async def test_ocr_returns_extracted_fields(client, auth, wire) -> None:
    resp = await _do_ocr(
        client, auth, wire,
        ReceiptData(merchant="SPBU RTA MILONO", tanggal=date(2023, 6, 24),
                    nominal=30000, kategori="bbm"),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["merchant"] == "SPBU RTA MILONO"
    assert body["nominal"] == 30000
    assert body["file_ref"].endswith(".jpg")
    assert len(body["struk_hash"]) == 64


async def test_ocr_rejects_non_image(client, auth, wire) -> None:
    wire(ReceiptData(merchant="x", nominal=1))
    resp = await client.post(
        "/api/reimbursement/ocr",
        headers=auth,
        files={"file": ("a.pdf", b"%PDF", "application/pdf")},
    )
    assert resp.status_code == 415


async def test_ocr_unreadable_receipt(client, auth, wire) -> None:
    resp = await _do_ocr(client, auth, wire, OcrError("foto tidak jelas"))
    assert resp.status_code == 422
    assert "jelas" in resp.json()["detail"]


async def test_submit_approves_when_no_duplicate(client, auth, wire, db) -> None:
    ocr = await _do_ocr(
        client, auth, wire,
        ReceiptData(merchant="Toko Kopi", tanggal=date(2026, 8, 1), nominal=43000),
    )
    r = await client.post(
        "/api/reimbursement/submit",
        headers=auth,
        json={
            "file_ref": ocr.json()["file_ref"],
            "struk_hash": ocr.json()["struk_hash"],
            "merchant": "Toko Kopi",
            "tanggal": "2026-08-01",
            "nominal": 43000,
            "kategori": "makan",
        },
    )
    assert r.json()["status"] == "disetujui"
    n = (await db.execute(select(func.count()).select_from(Reimbursement))).scalar_one()
    assert n == 1


async def test_submit_rejects_duplicate(client, auth, wire, db) -> None:
    receipt = ReceiptData(merchant="SPBU A", tanggal=date(2026, 7, 5), nominal=50000)
    o1 = await _do_ocr(client, auth, wire, receipt)
    payload = {
        "file_ref": o1.json()["file_ref"],
        "merchant": "SPBU A",
        "tanggal": "2026-07-05",
        "nominal": 50000,
    }
    first = await client.post("/api/reimbursement/submit", headers=auth, json=payload)
    assert first.json()["status"] == "disetujui"

    o2 = await _do_ocr(client, auth, wire, receipt)
    payload["file_ref"] = o2.json()["file_ref"]
    second = await client.post("/api/reimbursement/submit", headers=auth, json=payload)
    body = second.json()
    assert body["status"] == "ditolak"
    assert body["klaim_lama"]["nominal"] == 50000

    n = (await db.execute(select(func.count()).select_from(Reimbursement))).scalar_one()
    assert n == 1  # the duplicate was not stored


async def test_submit_bad_file_ref(client, auth, wire) -> None:
    wire(ReceiptData(merchant="x", nominal=1))
    r = await client.post(
        "/api/reimbursement/submit",
        headers=auth,
        json={"file_ref": "../etc/passwd", "merchant": "x", "nominal": 1},
    )
    assert r.status_code == 400


async def test_requires_auth(client, wire) -> None:
    r = await client.post(
        "/api/reimbursement/ocr",
        files={"file": ("a.jpg", b"x", "image/jpeg")},
    )
    assert r.status_code == 401
