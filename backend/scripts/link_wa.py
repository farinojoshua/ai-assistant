"""Link a WhatsApp number to an app user (whitelist for the inbound bot).

    python scripts/link_wa.py --phone 6281385226502 --email admin@demo.test
    python scripts/link_wa.py --phone 6281385226502 --disable
    python scripts/link_wa.py --list
"""
from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.db.app_db import get_sessionmaker
from app.db.models import User, WaContact


def _norm(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--phone")
    p.add_argument("--email")
    p.add_argument("--disable", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()

    async with get_sessionmaker()() as session:
        if args.list:
            rows = (await session.execute(select(WaContact))).scalars().all()
            for c in rows:
                print(
                    f"{c.phone}  user={c.user_id}  enabled={c.enabled}"
                )
            if not rows:
                print("(no wa_contacts)")
            return

        if not args.phone:
            p.error("--phone is required")
        phone = _norm(args.phone)
        contact = (
            await session.execute(
                select(WaContact).where(WaContact.phone == phone)
            )
        ).scalar_one_or_none()

        if args.disable:
            if contact is None:
                print(f"No contact for {phone}.")
                return
            contact.enabled = False
            await session.commit()
            print(f"Disabled {phone}.")
            return

        if not args.email:
            p.error("--email is required to link")
        user = (
            await session.execute(
                select(User).where(User.email == args.email)
            )
        ).scalar_one_or_none()
        if user is None:
            print(f"No user {args.email!r}.")
            return

        if contact is None:
            session.add(
                WaContact(
                    phone=phone,
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    enabled=True,
                )
            )
            action = "Linked"
        else:
            contact.user_id = user.id
            contact.tenant_id = user.tenant_id
            contact.enabled = True
            contact.conversation_id = None
            action = "Re-linked"
        await session.commit()
        print(f"{action} {phone} -> {args.email}")


if __name__ == "__main__":
    asyncio.run(main())
