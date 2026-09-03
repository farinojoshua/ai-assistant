"""Inbound WhatsApp message handling."""
from __future__ import annotations

import hashlib
import hmac
import logging
from collections import deque

from sqlalchemy import select

from app.chat.service import run_chat_turn
from app.config import get_settings
from app.db.app_db import get_sessionmaker
from app.db.models import User, WaContact
from app.whatsapp.send import send_text

logger = logging.getLogger(__name__)

# WhatsApp re-delivers webhooks on any non-2xx / timeout. Keep a small ring
# of message ids we've already handled so retries don't double-answer.
# Single-process only; a restart forgets them (harmless — worst case one echo).
_seen: deque[str] = deque(maxlen=512)
_seen_set: set[str] = set()


def already_processed(message_id: str) -> bool:
    if message_id in _seen_set:
        return True
    if len(_seen) == _seen.maxlen:
        _seen_set.discard(_seen[0])
    _seen.append(message_id)
    _seen_set.add(message_id)
    return False


def normalize_phone(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def verify_signature(raw_body: bytes, header: str | None) -> bool:
    """Validate Meta's ``X-Hub-Signature-256``.

    Returns True when no app secret is configured (dev), so local testing
    without the secret still works — set WHATSAPP_APP_SECRET in production.
    """
    secret = get_settings().whatsapp_app_secret
    if not secret:
        logger.warning("whatsapp: no app secret set, skipping signature check")
        return True
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(
        secret.encode(), raw_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))


async def _resolve_contact(phone: str) -> tuple[User, WaContact] | None:
    async with get_sessionmaker()() as session:
        contact = (
            await session.execute(
                select(WaContact).where(WaContact.phone == phone)
            )
        ).scalar_one_or_none()
        if contact is None or not contact.enabled:
            return None
        user = (
            await session.execute(
                select(User).where(User.id == contact.user_id)
            )
        ).scalar_one_or_none()
        if user is None:
            return None
        return user, contact


async def _remember_conversation(contact_id, conversation_id) -> None:
    async with get_sessionmaker()() as session:
        contact = await session.get(WaContact, contact_id)
        if contact is not None:
            contact.conversation_id = conversation_id
            await session.commit()


async def handle_incoming_text(*, from_phone: str, text: str) -> None:
    """Resolve the sender, run the agent, send the reply back. Best-effort."""
    phone = normalize_phone(from_phone)
    resolved = await _resolve_contact(phone)

    if resolved is None:
        logger.info("whatsapp: unregistered number %s", phone)
        if get_settings().whatsapp_reply_unregistered:
            await send_text(
                "Nomor ini belum terdaftar untuk memakai asisten. "
                "Hubungi admin untuk didaftarkan.",
                to=phone,
            )
        return

    user, contact = resolved
    try:
        reply, conv_id = await run_chat_turn(
            user=user,
            message=text,
            conversation_id=contact.conversation_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("whatsapp: agent turn failed for %s", phone)
        await send_text(
            "Maaf, terjadi kesalahan saat memproses pesan kamu.", to=phone
        )
        return

    if conv_id != contact.conversation_id:
        await _remember_conversation(contact.id, conv_id)
    await send_text(reply, to=phone)
