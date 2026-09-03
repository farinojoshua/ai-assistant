from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    s = get_settings()
    return bool(s.whatsapp_token and s.whatsapp_phone_number_id and s.whatsapp_to)


async def send_text(body: str, to: str | None = None) -> None:
    """Best-effort outbound WhatsApp text message.

    Silently no-ops when WhatsApp is not configured; logs and swallows any
    delivery error so it never breaks the web chat response.
    """
    s = get_settings()
    if not is_configured():
        return

    to = to or s.whatsapp_to
    url = (
        f"https://graph.facebook.com/{s.whatsapp_api_version}"
        f"/{s.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": body[:4096]},
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {s.whatsapp_token}"},
                json=payload,
            )
        if resp.status_code >= 400:
            logger.warning("whatsapp send failed %s: %s", resp.status_code, resp.text)
    except Exception:  # noqa: BLE001 - delivery is best-effort
        logger.exception("whatsapp send error")


async def send_buttons(body: str, buttons: list[tuple[str, str]], to: str) -> None:
    """Send an interactive reply-button message.

    ``buttons`` is a list of (id, title) pairs, max 3 — a WhatsApp Cloud API
    limit. Falls back to nothing (best-effort) when not configured.
    """
    s = get_settings()
    if not is_configured():
        return
    url = (
        f"https://graph.facebook.com/{s.whatsapp_api_version}"
        f"/{s.whatsapp_phone_number_id}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": bid, "title": title[:20]}}
                    for bid, title in buttons[:3]
                ]
            },
        },
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {s.whatsapp_token}"},
                json=payload,
            )
        if resp.status_code >= 400:
            logger.warning(
                "whatsapp send_buttons failed %s: %s", resp.status_code, resp.text
            )
    except Exception:  # noqa: BLE001 - delivery is best-effort
        logger.exception("whatsapp send_buttons error")
