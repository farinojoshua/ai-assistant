from __future__ import annotations

import hashlib
import re
import uuid
from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import CurrentUser
from app.config import get_settings
from app.db.app_db import get_db
from app.reimbursement import service
from app.reimbursement.ocr import OcrError, extract_receipt

router = APIRouter(prefix="/api/reimbursement", tags=["reimbursement"])

_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_FILE_REF_RE = re.compile(r"^[0-9a-f-]{36}\.(jpg|png|webp)$")


def _upload_dir() -> Path:
    d = Path(get_settings().upload_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


class OcrResult(BaseModel):
    file_ref: str
    struk_hash: str
    merchant: str | None
    tanggal: date | None
    nominal: float | None
    kategori: str | None
    mata_uang: str


class SubmitRequest(BaseModel):
    file_ref: str
    struk_hash: str | None = None
    merchant: str
    tanggal: date | None = None
    nominal: float
    kategori: str | None = None
    catatan: str | None = None


@router.post("/ocr", response_model=OcrResult)
async def ocr(
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> OcrResult:
    settings = get_settings()
    if file.content_type not in _EXT:
        raise HTTPException(415, "format harus JPEG, PNG, atau WebP")
    data = await file.read()
    if len(data) > settings.upload_max_bytes:
        raise HTTPException(413, "ukuran file melebihi batas")

    file_ref = f"{uuid.uuid4()}{_EXT[file.content_type]}"
    (_upload_dir() / file_ref).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()

    try:
        receipt = await extract_receipt(data, file.content_type)
    except OcrError as e:
        raise HTTPException(422, str(e)) from None

    return OcrResult(
        file_ref=file_ref,
        struk_hash=digest,
        merchant=receipt.merchant,
        tanggal=receipt.tanggal,
        nominal=receipt.nominal,
        kategori=receipt.kategori,
        mata_uang=receipt.mata_uang,
    )


@router.post("/submit")
async def submit(
    body: SubmitRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    if not _FILE_REF_RE.match(body.file_ref) or not (
        _upload_dir() / body.file_ref
    ).is_file():
        raise HTTPException(400, "file_ref tidak valid")

    dup = await service.find_duplicate(
        db,
        tenant_id=user.tenant_id,
        merchant=body.merchant,
        tanggal=body.tanggal,
        nominal=body.nominal,
    )
    if dup is not None:
        return {
            "status": "ditolak",
            "alasan": "Struk ini sudah pernah diajukan untuk reimbursement.",
            "klaim_lama": {
                "id": str(dup.id),
                "merchant": dup.merchant,
                "tanggal_struk": dup.tanggal_struk.isoformat()
                if dup.tanggal_struk
                else None,
                "nominal": float(dup.nominal),
                "diajukan_oleh": str(dup.user_id),
                "diajukan_pada": dup.created_at.isoformat(),
                "status": dup.status,
            },
        }

    row = await service.create(
        db,
        tenant_id=user.tenant_id,
        user_id=user.id,
        merchant=body.merchant,
        tanggal=body.tanggal,
        nominal=body.nominal,
        mata_uang="IDR",
        kategori=body.kategori,
        catatan=body.catatan,
        struk_file=body.file_ref,
        struk_hash=body.struk_hash,
    )
    await db.commit()
    return {"status": "disetujui", "id": str(row.id)}


@router.get("/mine")
async def mine(
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    rows = await service.list_for_user(db, user_id=user.id)
    return [
        {
            "id": str(r.id),
            "merchant": r.merchant,
            "tanggal_struk": r.tanggal_struk.isoformat() if r.tanggal_struk else None,
            "nominal": float(r.nominal),
            "kategori": r.kategori,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
