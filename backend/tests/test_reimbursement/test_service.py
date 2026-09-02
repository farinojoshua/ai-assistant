from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.reimbursement import service


@pytest.fixture
def tenant() -> uuid.UUID:
    return uuid.uuid4()


async def _mk(db, tenant, **over):
    kw = dict(
        tenant_id=tenant,
        user_id=uuid.uuid4(),
        merchant="SPBU RTA Milono",
        tanggal=date(2023, 6, 24),
        nominal=30000.0,
        mata_uang="IDR",
        kategori="bbm",
        catatan=None,
        struk_file="a.jpg",
        struk_hash="h",
    )
    kw.update(over)
    row = await service.create(db, **kw)
    await db.commit()
    return row


async def test_duplicate_matches_ignoring_case_and_space(db: AsyncSession, tenant) -> None:
    await _mk(db, tenant)
    dup = await service.find_duplicate(
        db,
        tenant_id=tenant,
        merchant="  spbu rta milono ",
        tanggal=date(2023, 6, 24),
        nominal=30000.0,
    )
    assert dup is not None


async def test_no_duplicate_when_amount_differs(db: AsyncSession, tenant) -> None:
    await _mk(db, tenant)
    dup = await service.find_duplicate(
        db, tenant_id=tenant, merchant="SPBU RTA Milono",
        tanggal=date(2023, 6, 24), nominal=31000.0,
    )
    assert dup is None


async def test_other_tenant_not_a_duplicate(db: AsyncSession, tenant) -> None:
    await _mk(db, tenant)
    dup = await service.find_duplicate(
        db, tenant_id=uuid.uuid4(), merchant="SPBU RTA Milono",
        tanggal=date(2023, 6, 24), nominal=30000.0,
    )
    assert dup is None


async def test_rejected_claim_is_not_a_duplicate(db: AsyncSession, tenant) -> None:
    row = await _mk(db, tenant)
    row.status = "ditolak"
    await db.commit()
    dup = await service.find_duplicate(
        db, tenant_id=tenant, merchant="SPBU RTA Milono",
        tanggal=date(2023, 6, 24), nominal=30000.0,
    )
    assert dup is None


async def test_create_auto_approves(db: AsyncSession, tenant) -> None:
    row = await _mk(db, tenant)
    assert row.status == "disetujui"
    assert row.decided_at is not None


async def test_list_for_user_newest_first(db: AsyncSession, tenant) -> None:
    uid = uuid.uuid4()
    await _mk(db, tenant, user_id=uid, merchant="A", nominal=1000.0)
    await _mk(db, tenant, user_id=uid, merchant="B", nominal=2000.0)
    rows = await service.list_for_user(db, user_id=uid)
    assert [r.merchant for r in rows] == ["B", "A"]
