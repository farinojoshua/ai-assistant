"""WhatsApp Cloud API webhook.

GET  /api/wa/webhook  — Meta's subscription verification handshake
POST /api/wa/webhook  — inbound messages; acked immediately, handled in the
                        background so the agent's latency never trips Meta's
                        retry timeout.
"""
from __future__ import annotations

import hmac
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.whatsapp.service import (
    already_processed,
    handle_incoming_text,
    verify_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wa", tags=["whatsapp"])


def _dispatch_value(value: dict[str, Any], bg: BackgroundTasks) -> None:
    """Pull text messages out of one Meta "value" object and queue them.

    Shared by the signed Meta webhook and the n8n relay, since n8n forwards
    the same value shape (messaging_product/contacts/messages) it received
    from Meta. Non-text types (image, document, ...) are skipped for now —
    WhatsApp media intake isn't wired into the agent yet.
    """
    for msg in value.get("messages", []):
        if msg.get("type") != "text":
            logger.info(
                "whatsapp: skipping unsupported message type %r from %s",
                msg.get("type"),
                msg.get("from"),
            )
            continue
        mid = msg.get("id", "")
        if mid and already_processed(mid):
            continue
        from_phone = msg.get("from", "")
        body = (msg.get("text") or {}).get("body", "").strip()
        if from_phone and body:
            bg.add_task(handle_incoming_text, from_phone=from_phone, text=body)


@router.get("/webhook")
async def verify(request: Request) -> Response:
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")
    expected = get_settings().whatsapp_verify_token

    if mode == "subscribe" and expected and token == expected:
        return PlainTextResponse(challenge)
    return PlainTextResponse("verification failed", status_code=status.HTTP_403_FORBIDDEN)


@router.post("/webhook")
async def receive(request: Request, bg: BackgroundTasks) -> Response:
    raw = await request.body()
    if not verify_signature(raw, request.headers.get("X-Hub-Signature-256")):
        return PlainTextResponse("bad signature", status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return Response(status_code=status.HTTP_200_OK)

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            _dispatch_value(change.get("value", {}), bg)

    # Always 200 fast — anything else makes Meta retry the whole batch.
    return Response(status_code=status.HTTP_200_OK)


@router.post("/relay")
async def relay(
    request: Request,
    bg: BackgroundTasks,
    x_relay_token: str = Header(default=""),
) -> Response:
    """Accept messages from a trusted forwarder (e.g. n8n) that can't sign
    like Meta. Auth is a single shared secret header, not a Meta signature.

    Body is whatever n8n forwards from the Meta trigger node: either a single
    "value" object or a JSON array of them (``messaging_product``/``contacts``/
    ``messages``) — the same shape ``/webhook`` unwraps from
    ``entry[].changes[].value``. A flat ``{"from", "text", "message_id"}``
    shape is also accepted for simpler callers.
    """
    expected = get_settings().whatsapp_relay_token
    if not expected or not hmac.compare_digest(x_relay_token, expected):
        return PlainTextResponse(
            "unauthorized", status_code=status.HTTP_401_UNAUTHORIZED
        )

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return PlainTextResponse("invalid json", status_code=status.HTTP_400_BAD_REQUEST)

    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        if not isinstance(item, dict):
            continue
        if "messages" in item:
            _dispatch_value(item, bg)
            continue
        # legacy flat shape: {"from": "...", "text": "...", "message_id": "..."}
        from_phone = str(item.get("from", "")).strip()
        body = str(item.get("text", "")).strip()
        mid = item.get("message_id", "")
        if mid and already_processed(mid):
            continue
        if from_phone and body:
            bg.add_task(handle_incoming_text, from_phone=from_phone, text=body)

    return Response(status_code=status.HTTP_200_OK)
