"""WhatsApp Cloud API webhook.

GET  /api/wa/webhook  — Meta's subscription verification handshake
POST /api/wa/webhook  — inbound messages; acked immediately, handled in the
                        background so the agent's latency never trips Meta's
                        retry timeout.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.config import get_settings
from app.whatsapp.service import (
    already_processed,
    handle_incoming_text,
    verify_signature,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wa", tags=["whatsapp"])


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
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                mid = msg.get("id", "")
                if mid and already_processed(mid):
                    continue
                from_phone = msg.get("from", "")
                body = (msg.get("text") or {}).get("body", "").strip()
                if from_phone and body:
                    bg.add_task(
                        handle_incoming_text,
                        from_phone=from_phone,
                        text=body,
                    )

    # Always 200 fast — anything else makes Meta retry the whole batch.
    return Response(status_code=status.HTTP_200_OK)
