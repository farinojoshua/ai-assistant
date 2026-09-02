from __future__ import annotations

import json

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.auth.security import hash_password
from app.db.models import AuditLog, Conversation, Message, Tenant, User
from app.llm.base import LLMResponse, ToolCall
from app.llm.fake import FakeProvider


def _parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        ev = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        events.append((ev, data))
    return events


@pytest.fixture
async def auth(client: AsyncClient, db) -> dict[str, str]:
    tenant = Tenant(nama="Acme")
    db.add(tenant)
    await db.flush()
    db.add(
        User(
            tenant_id=tenant.id,
            email="budi@acme.co",
            password_hash=hash_password("rahasia123"),
            nama="Budi",
            role="user",
        )
    )
    await db.commit()
    resp = await client.post(
        "/api/auth/login",
        json={"email": "budi@acme.co", "password": "rahasia123"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access']}"}


@pytest.fixture
def wire(monkeypatch, _engine, company_gateway):
    """Point the chat route at the test app DB + company gateway, and let a
    test install its own FakeProvider script."""
    maker = async_sessionmaker(_engine, expire_on_commit=False)
    monkeypatch.setattr("app.chat.routes.get_sessionmaker", lambda: maker)
    monkeypatch.setattr(
        "app.chat.routes.get_company_gateway", lambda: company_gateway
    )
    holder: dict[str, FakeProvider] = {}

    def set_script(script) -> FakeProvider:
        fake = FakeProvider(script=script)
        holder["fake"] = fake
        monkeypatch.setattr("app.chat.routes.get_provider", lambda: fake)
        return fake

    return set_script


async def test_new_conversation(client, auth, wire, db) -> None:
    wire(
        [
            LLMResponse(
                stop_reason="tool_use",
                tool_calls=[
                    ToolCall(
                        id="c1",
                        name="ambil_data",
                        arguments={
                            "view": "v_stok",
                            "filter": [
                                {"kolom": "nama", "operator": "contains", "nilai": "kabel"}
                            ],
                        },
                    )
                ],
            ),
            LLMResponse(text="Ada 4 jenis kabel.", stop_reason="end_turn"),
        ]
    )
    resp = await client.post(
        "/api/chat", json={"message": "stok kabel?"}, headers=auth
    )
    assert resp.status_code == 200
    events = _parse_sse(resp.text)
    kinds = [e[0] for e in events]
    assert kinds == ["tool", "token", "done"]
    assert events[0][1]["name"] == "ambil_data"
    assert events[1][1]["text"] == "Ada 4 jenis kabel."
    conv_id = events[2][1]["conversation_id"]

    assert (await db.execute(select(func.count()).select_from(Conversation))).scalar_one() == 1
    msgs = (
        await db.execute(
            select(Message).where(Message.conversation_id == conv_id).order_by(Message.created_at)
        )
    ).scalars().all()
    assert [m.role for m in msgs] == ["user", "assistant"]
    assert (await db.execute(select(func.count()).select_from(AuditLog))).scalar_one() == 1


async def test_existing_conversation_passes_history(client, auth, wire, db) -> None:
    fake_first = wire(
        [LLMResponse(text="Halo Budi.", stop_reason="end_turn")]
    )
    r1 = await client.post(
        "/api/chat", json={"message": "halo"}, headers=auth
    )
    conv_id = _parse_sse(r1.text)[-1][1]["conversation_id"]

    fake_second = wire([LLMResponse(text="Tadi kamu bilang halo.", stop_reason="end_turn")])
    r2 = await client.post(
        "/api/chat",
        json={"message": "aku bilang apa tadi?", "conversation_id": conv_id},
        headers=auth,
    )
    assert r2.status_code == 200
    sent_msgs = fake_second.calls[0][0]
    roles_contents = [(m.role, m.content) for m in sent_msgs]
    assert ("user", "halo") in roles_contents
    assert ("assistant", "Halo Budi.") in roles_contents


async def test_requires_auth(client, wire) -> None:
    wire([LLMResponse(text="x", stop_reason="end_turn")])
    resp = await client.post("/api/chat", json={"message": "hi"})
    assert resp.status_code == 401


async def test_unknown_conversation_id(client, auth, wire) -> None:
    wire([LLMResponse(text="x", stop_reason="end_turn")])
    resp = await client.post(
        "/api/chat",
        json={
            "message": "hi",
            "conversation_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=auth,
    )
    events = _parse_sse(resp.text)
    assert events[0][0] == "error"


async def test_provider_error_keeps_user_message(client, auth, wire, db) -> None:
    wire([RuntimeError("llm down")])
    resp = await client.post(
        "/api/chat", json={"message": "stok kabel?"}, headers=auth
    )
    events = _parse_sse(resp.text)
    assert ("error", {"message": "LLM error: llm down"}) in [
        (e[0], e[1]) for e in events
    ]
    # user message still saved
    rows = (await db.execute(select(Message).where(Message.role == "user"))).scalars().all()
    assert any(m.content == "stok kabel?" for m in rows)
