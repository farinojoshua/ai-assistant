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
    handle_incoming_image,
    handle_incoming_location,
    handle_incoming_text,
    handle_interactive_reply,
    verify_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wa", tags=["whatsapp"])


def _dispatch_value(value: dict[str, Any], bg: BackgroundTasks) -> None:
    """Pull messages out of one Meta "value" object and queue them.

    Shared by the signed Meta webhook and the n8n relay, since n8n forwards
    the same value shape (messaging_product/contacts/messages) it received
    from Meta. Text drives the chat agent; images feed the reimbursement OCR
    flow; interactive replies (button clicks) drive that flow's Kirim/Edit/
    Batal step. Other types (documents, audio, ...) are skipped for now.
    """
    for msg in value.get("messages", []):
        mid = msg.get("id", "")
        if mid and already_processed(mid):
            continue
        from_phone = msg.get("from", "")
        if not from_phone:
            continue

        mtype = msg.get("type")
        if mtype == "text":
            body = (msg.get("text") or {}).get("body", "").strip()
            if body:
                bg.add_task(handle_incoming_text, from_phone=from_phone, text=body)
        elif mtype == "image":
            image = msg.get("image") or {}
            media_id = image.get("id")
            if media_id:
                bg.add_task(
                    handle_incoming_image,
                    from_phone=from_phone,
                    media_id=media_id,
                    caption=image.get("caption"),
                )
        elif mtype == "interactive":
            button = (msg.get("interactive") or {}).get("button_reply") or {}
            button_id = button.get("id")
            if button_id:
                bg.add_task(
                    handle_interactive_reply,
                    from_phone=from_phone,
                    button_id=button_id,
                )
        elif mtype == "location":
            loc = msg.get("location") or {}
            lat, lng = loc.get("latitude"), loc.get("longitude")
            if lat is not None and lng is not None:
                bg.add_task(
                    handle_incoming_location,
                    from_phone=from_phone,
                    latitude=lat,
                    longitude=lng,
                    name=loc.get("name"),
                    address=loc.get("address"),
                    message_id=mid or None,
                )
        else:
            logger.info(
                "whatsapp: skipping unsupported message type %r from %s",
                mtype,
                from_phone,
            )


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
