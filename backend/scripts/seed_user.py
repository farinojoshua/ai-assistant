"""Create a tenant + user. Usage:

    python scripts/seed_user.py --email a@b.com --password secret --nama "Budi"
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.auth.security import hash_password
from app.db.app_db import get_sessionmaker
from app.db.models import Tenant, User


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--nama", default="Admin")
    parser.add_argument("--tenant", default="Default")
    args = parser.parse_args()

    async with get_sessionmaker()() as session:
        tenant = (
            await session.execute(
                select(Tenant).where(Tenant.nama == args.tenant)
            )
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(nama=args.tenant)
            session.add(tenant)
            await session.flush()

        existing = (
            await session.execute(
                select(User).where(User.email == args.email)
            )
        ).scalar_one_or_none()
        if existing is not None:
            print(f"User {args.email} already exists.")
            return

        session.add(
            User(
                tenant_id=tenant.id,
                email=args.email,
                password_hash=hash_password(args.password),
                nama=args.nama,
                role="admin",
            )
        )
        await session.commit()
        print(f"Created user {args.email} in tenant {args.tenant!r}.")


if __name__ == "__main__":
    asyncio.run(main())
