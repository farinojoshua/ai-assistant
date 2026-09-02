from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Reimbursement


async def find_duplicate(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    merchant: str,
    tanggal: date | None,
    nominal: float,
) -> Reimbursement | None:
    q = select(Reimbursement).where(
        Reimbursement.tenant_id == tenant_id,
        func.lower(func.trim(Reimbursement.merchant)) == merchant.strip().lower(),
        Reimbursement.nominal == nominal,
        Reimbursement.status != "ditolak",
    )
    q = q.where(
        Reimbursement.tanggal_struk == tanggal
        if tanggal is not None
        else Reimbursement.tanggal_struk.is_(None)
    )
    return (await session.execute(q.limit(1))).scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    merchant: str,
    tanggal: date | None,
    nominal: float,
    mata_uang: str,
    kategori: str | None,
    catatan: str | None,
    struk_file: str | None,
    struk_hash: str | None,
) -> Reimbursement:
    row = Reimbursement(
        tenant_id=tenant_id,
        user_id=user_id,
        merchant=merchant.strip(),
        tanggal_struk=tanggal,
        nominal=nominal,
        mata_uang=mata_uang or "IDR",
        kategori=kategori,
        catatan=catatan,
        struk_file=struk_file,
        struk_hash=struk_hash,
        # approval belum aktif — auto setuju bila lolos cek duplikat
        status="disetujui",
        decided_at=datetime.now(timezone.utc),
    )
    session.add(row)
    await session.flush()
    return row


async def list_for_user(
    session: AsyncSession, *, user_id: uuid.UUID, limit: int = 50
) -> list[Reimbursement]:
    q = (
        select(Reimbursement)
        .where(Reimbursement.user_id == user_id)
        .order_by(Reimbursement.created_at.desc())
        .limit(limit)
    )
    return list((await session.execute(q)).scalars().all())
