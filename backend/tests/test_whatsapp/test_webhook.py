from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient

from app.config import get_settings
from app.whatsapp import service as wa_service


@pytest.fixture(autouse=True)
def _wa_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "whatsapp_verify_token", "verify-me", raising=False)
    monkeypatch.setattr(s, "whatsapp_app_secret", "", raising=False)
    # each test starts with a clean dedup ring
    wa_service._seen.clear()
    wa_service._seen_set.clear()
    yield


@pytest.fixture
def captured(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    async def _fake(*, from_phone: str, text: str) -> None:
        calls.append({"from_phone": from_phone, "text": text})

    monkeypatch.setattr(
        "app.whatsapp.routes.handle_incoming_text", _fake
    )
    return calls


def _text_payload(mid: str, body: str, frm: str = "628111") -> dict:
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "field": "messages",
                        "value": {
                            "messages": [
                                {
                                    "from": frm,
                                    "id": mid,
                                    "type": "text",
                                    "text": {"body": body},
                                }
                            ]
                        },
                    }
                ]
            }
        ],
    }


async def test_verify_handshake_ok(client: AsyncClient):
    r = await client.get(
        "/api/wa/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "verify-me",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 200
    assert r.text == "12345"


async def test_verify_handshake_bad_token(client: AsyncClient):
    r = await client.get(
        "/api/wa/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong",
            "hub.challenge": "12345",
        },
    )
    assert r.status_code == 403


async def test_inbound_text_dispatched(client: AsyncClient, captured):
    r = await client.post("/api/wa/webhook", json=_text_payload("m1", "halo"))
    assert r.status_code == 200
    assert captured == [{"from_phone": "628111", "text": "halo"}]


async def test_duplicate_message_id_ignored(client: AsyncClient, captured):
    p = _text_payload("m1", "halo")
    await client.post("/api/wa/webhook", json=p)
    await client.post("/api/wa/webhook", json=p)
    assert len(captured) == 1


async def test_status_events_ignored(client: AsyncClient, captured):
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {"changes": [{"value": {"statuses": [{"status": "delivered"}]}}]}
        ],
    }
    r = await client.post("/api/wa/webhook", json=payload)
    assert r.status_code == 200
    assert captured == []


async def test_bad_signature_rejected(client: AsyncClient, captured, monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "s3cret")
    r = await client.post(
        "/api/wa/webhook",
        content=json.dumps(_text_payload("m1", "halo")),
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": "sha256=deadbeef",
        },
    )
    assert r.status_code == 403
    assert captured == []


async def test_good_signature_accepted(client: AsyncClient, captured, monkeypatch):
    monkeypatch.setattr(get_settings(), "whatsapp_app_secret", "s3cret")
    body = json.dumps(_text_payload("m1", "halo")).encode()
    sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = await client.post(
        "/api/wa/webhook",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Hub-Signature-256": f"sha256={sig}",
        },
    )
    assert r.status_code == 200
    assert len(captured) == 1
