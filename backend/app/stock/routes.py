from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.config import get_settings
from app.db.app_db import get_db
from app.db.company_db import get_company_writer
from app.db.models import StockMovement
from app.stock import service
from app.stock.ocr import OcrError, extract_goods

router = APIRouter(prefix="/api/stock", tags=["stock"])

_FILE_REF_RE = re.compile(r"^[0-9a-f-]{36}\.(jpg|png|webp)$")


def _upload_dir() -> Path:
    d = Path(get_settings().upload_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _sniff(data: bytes) -> tuple[str, str] | None:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


class OcrResult(BaseModel):
    foto_ref: str
    produk: str | None
    merk: str | None
    ukuran: str | None
    jumlah: int | None
    satuan: str | None
    kandidat: list[dict]


class ReceiveRequest(BaseModel):
    mode: Literal["existing", "new"]
    foto_ref: str
    jumlah: int = Field(gt=0)
    catatan: str | None = None
    # mode=existing
    product_id: int | None = None
    # mode=new
    nama: str | None = None
    sku: str | None = None
    satuan: str | None = None
    gudang: str | None = None


@router.post("/ocr", response_model=OcrResult)
async def ocr(user: CurrentUser, file: Annotated[UploadFile, File()]) -> OcrResult:
    data = await file.read()
    if len(data) > get_settings().upload_max_bytes:
        raise HTTPException(413, "ukuran file melebihi batas")
    sniffed = _sniff(data)
    if sniffed is None:
        raise HTTPException(415, "format harus JPEG, PNG, atau WebP")
    media_type, ext = sniffed

    foto_ref = f"{uuid.uuid4()}{ext}"
    (_upload_dir() / foto_ref).write_bytes(data)

    try:
        goods = await extract_goods(data, media_type)
    except OcrError as e:
        raise HTTPException(422, str(e)) from None

    writer = get_company_writer()
    kandidat = (
        await service.search_products(writer, goods.deskripsi)
        if goods.deskripsi
        else []
    )
    return OcrResult(
        foto_ref=foto_ref,
        produk=goods.produk,
        merk=goods.merk,
        ukuran=goods.ukuran,
        jumlah=goods.jumlah,
        satuan=goods.satuan,
        kandidat=[dict(k) for k in kandidat],
    )


@router.post("/receive")
async def receive(
    body: ReceiveRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    if not _FILE_REF_RE.match(body.foto_ref) or not (
        _upload_dir() / body.foto_ref
    ).is_file():
        raise HTTPException(400, "foto_ref tidak valid")

    writer = get_company_writer()

    if body.mode == "existing":
        if body.product_id is None:
            raise HTTPException(422, "product_id wajib untuk mode existing")
        result = await service.receive_existing(
            writer, db,
            product_id=body.product_id, delta=body.jumlah,
            user_id=user.id, tenant_id=user.tenant_id,
            foto=body.foto_ref, catatan=body.catatan,
        )
    else:
        missing = [
            f for f in ("nama", "sku", "satuan", "gudang")
            if not getattr(body, f)
        ]
        if missing:
            raise HTTPException(422, f"field wajib untuk barang baru: {missing}")
        try:
            result = await service.receive_new(
                writer, db,
                nama=body.nama, sku=body.sku, satuan=body.satuan,
                gudang=body.gudang, qty=body.jumlah,
                user_id=user.id, tenant_id=user.tenant_id,
                foto=body.foto_ref, catatan=body.catatan,
            )
        except Exception as e:  # noqa: BLE001 - e.g. duplicate SKU
            raise HTTPException(409, f"gagal membuat barang: {e}") from None

    await db.commit()
    return {"status": "ok", **result}


@router.get("/movements")
async def movements(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    rows = (
        await db.execute(
            select(StockMovement)
            .where(StockMovement.tenant_id == user.tenant_id)
            .order_by(StockMovement.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "aksi": r.aksi,
            "produk": r.product_nama,
            "sku": r.product_sku,
            "delta": r.delta_qty,
            "qty_before": r.qty_before,
            "qty_after": r.qty_after,
            "gudang": r.gudang,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
