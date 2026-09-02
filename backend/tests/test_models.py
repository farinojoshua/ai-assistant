from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, Message, Tenant, User


async def test_user_tenant_relationship(db: AsyncSession) -> None:
    tenant = Tenant(nama="Acme")
    db.add(tenant)
    await db.flush()

    user = User(
        tenant_id=tenant.id,
        email="budi@acme.test",
        password_hash="x",
        nama="Budi",
    )
    db.add(user)
    await db.commit()

    fetched = (
        await db.execute(select(User).where(User.email == "budi@acme.test"))
    ).scalar_one()
    assert fetched.tenant_id == tenant.id
    assert fetched.role == "user"
    assert fetched.created_at is not None


async def test_conversation_message_cascade(db: AsyncSession) -> None:
    tenant = Tenant(nama="Acme")
    db.add(tenant)
    await db.flush()
    user = User(
        tenant_id=tenant.id, email="a@a.test", password_hash="x", nama="A"
    )
    db.add(user)
    await db.flush()

    conv = Conversation(tenant_id=tenant.id, user_id=user.id, title="Hi")
    conv.messages.append(Message(role="user", content="halo"))
    db.add(conv)
    await db.commit()

    msgs = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv.id)
        )
    ).scalars().all()
    assert len(msgs) == 1
    assert msgs[0].role == "user"
