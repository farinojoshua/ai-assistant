"""Inbound WhatsApp message handling."""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import uuid
from collections import deque
from datetime import date
from pathlib import Path

from sqlalchemy import select

from app.chat.service import run_chat_turn
from app.config import get_settings
from app.db.app_db import get_sessionmaker
from app.db.models import User, WaContact, WaLocation
from app.reimbursement import service as reimb_service
from app.reimbursement.ocr import OcrError, extract_receipt
from app.whatsapp.geocode import reverse_geocode
from app.whatsapp.media import MediaError, download_media
from app.whatsapp.send import send_buttons, send_text

logger = logging.getLogger(__name__)

# Draft reimbursement awaiting Kirim/Edit/Batal, keyed by normalized phone.
# In-memory + single-process, same tradeoff as the dedup ring below: a
# restart loses in-flight drafts, user just resends the photo.
_pending_reimb: dict[str, dict] = {}

_REIMB_BUTTONS = [
    ("reimb_confirm", "Kirim"),
    ("reimb_edit", "Edit"),
    ("reimb_cancel", "Batal"),
]

# Free-text ways out of the edit prompt — people type "gajadi deh", not a
# button tap, when they change their mind mid-flow.
_CANCEL_WORDS = (
    "batal", "cancel", "gajadi", "ga jadi", "gak jadi", "tidak jadi",
    "nggak jadi", "udahlah", "skip", "stop",
)

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


def _format_draft(d: dict) -> str:
    nominal = d.get("nominal") or 0
    nominal_str = f"{nominal:,.0f}".replace(",", ".")
    return (
        "📋 Draf reimbursement dari foto struk:\n"
        f"Merchant: {d.get('merchant') or '-'}\n"
        f"Tanggal: {d.get('tanggal') or '-'}\n"
        f"Nominal: Rp{nominal_str}\n"
        f"Kategori: {d.get('kategori') or '-'}\n\n"
        "Kirim untuk diajukan, Edit untuk koreksi, atau Batal."
    )


async def handle_incoming_image(
    *, from_phone: str, media_id: str, caption: str | None = None
) -> None:
    """Photo-in -> OCR -> draft awaiting Kirim/Edit/Batal. Best-effort."""
    phone = normalize_phone(from_phone)
    resolved = await _resolve_contact(phone)
    if resolved is None:
        logger.info("whatsapp: unregistered number %s sent an image", phone)
        if get_settings().whatsapp_reply_unregistered:
            await send_text(
                "Nomor ini belum terdaftar untuk memakai asisten. "
                "Hubungi admin untuk didaftarkan.",
                to=phone,
            )
        return

    user, _contact = resolved

    try:
        data, mime_type = await download_media(media_id)
    except MediaError:
        logger.exception("whatsapp: gagal download media dari %s", phone)
        await send_text(
            "Maaf, gagal mengambil foto dari WhatsApp. Coba kirim ulang.", to=phone
        )
        return

    try:
        receipt = await extract_receipt(data, mime_type)
    except OcrError as e:
        await send_text(f"Gagal membaca struk: {e}", to=phone)
        return

    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}.get(
        mime_type, ".jpg"
    )
    upload_dir = Path(get_settings().upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    file_ref = f"{uuid.uuid4()}{ext}"
    (upload_dir / file_ref).write_bytes(data)

    draft = {
        "merchant": receipt.merchant or "",
        "tanggal": receipt.tanggal.isoformat() if receipt.tanggal else None,
        "nominal": receipt.nominal or 0,
        "kategori": receipt.kategori,
        "mata_uang": receipt.mata_uang,
        "struk_file": file_ref,
        "struk_hash": hashlib.sha256(data).hexdigest(),
        "user_id": str(user.id),
        "tenant_id": str(user.tenant_id),
    }
    _pending_reimb[phone] = draft
    await send_buttons(_format_draft(draft), _REIMB_BUTTONS, to=phone)


async def handle_incoming_location(
    *,
    from_phone: str,
    latitude: float,
    longitude: float,
    name: str | None = None,
    address: str | None = None,
    message_id: str | None = None,
) -> None:
    """Save a shared location as-is. One row per share, no live tracking."""
    phone = normalize_phone(from_phone)
    resolved = await _resolve_contact(phone)
    if resolved is None:
        logger.info("whatsapp: unregistered number %s shared a location", phone)
        if get_settings().whatsapp_reply_unregistered:
            await send_text(
                "Nomor ini belum terdaftar untuk memakai asisten. "
                "Hubungi admin untuk didaftarkan.",
                to=phone,
            )
        return

    user, _contact = resolved

    # WA only gives a name/address when the sender picked a place from
    # search; a raw dropped-pin share has neither, so fall back to
    # reverse-geocoding the coordinate ourselves.
    resolved_address = address or await reverse_geocode(latitude, longitude)

    async with get_sessionmaker()() as session:
        session.add(
            WaLocation(
                tenant_id=user.tenant_id,
                user_id=user.id,
                phone=phone,
                latitude=latitude,
                longitude=longitude,
                name=name,
                address=resolved_address,
                message_id=message_id,
            )
        )
        await session.commit()

    maps_url = f"https://maps.google.com/?q={latitude},{longitude}"
    label = name or resolved_address or "Lokasi"
    await send_text(f"📍 {label} tersimpan.\n{maps_url}", to=phone)


async def handle_interactive_reply(*, from_phone: str, button_id: str) -> None:
    phone = normalize_phone(from_phone)
    draft = _pending_reimb.get(phone)
    if draft is None:
        await send_text(
            "Tidak ada draf reimbursement aktif. Kirim foto struk dulu ya.",
            to=phone,
        )
        return

    if button_id == "reimb_cancel":
        _pending_reimb.pop(phone, None)
        await send_text("Oke, dibatalkan.", to=phone)
        return

    if button_id == "reimb_edit":
        await send_text(
            "Ketik koreksinya, format field=nilai dipisah titik-koma.\n"
            "Field: merchant, tanggal (YYYY-MM-DD), nominal, kategori\n"
            "Contoh: nominal=85000; tanggal=2026-09-03\n"
            "Atau ketik 'batal' kalau gajadi.",
            to=phone,
        )
        return

    if button_id == "reimb_confirm":
        await _submit_draft(phone, draft)
        return

    logger.info("whatsapp: unknown button_id %r from %s", button_id, phone)


async def _apply_draft_correction(phone: str, text: str) -> None:
    draft = _pending_reimb[phone]
    normalized = text.strip().lower()
    if any(w in normalized for w in _CANCEL_WORDS):
        _pending_reimb.pop(phone, None)
        await send_text("Oke, dibatalkan.", to=phone)
        return

    parts = [p.strip() for p in text.split(";") if "=" in p]
    if not parts:
        await send_text(
            "Format tidak dikenali. Contoh: nominal=85000; tanggal=2026-09-03\n"
            "Atau ketik 'batal' untuk membatalkan.",
            to=phone,
        )
        return
    for part in parts:
        key, _, val = part.partition("=")
        key = key.strip().lower()
        val = val.strip()
        if not val:
            continue
        if key == "nominal":
            digits = re.sub(r"[^\d.]", "", val)
            if digits:
                draft["nominal"] = float(digits)
        elif key == "tanggal":
            draft["tanggal"] = val
        elif key == "merchant":
            draft["merchant"] = val
        elif key == "kategori":
            draft["kategori"] = val
    await send_buttons(_format_draft(draft), _REIMB_BUTTONS, to=phone)


async def _submit_draft(phone: str, draft: dict) -> None:
    async with get_sessionmaker()() as session:
        tanggal = date.fromisoformat(draft["tanggal"]) if draft["tanggal"] else None
        dup = await reimb_service.find_duplicate(
            session,
            tenant_id=uuid.UUID(draft["tenant_id"]),
            merchant=draft["merchant"] or "-",
            tanggal=tanggal,
            nominal=draft["nominal"],
        )
        if dup is not None:
            _pending_reimb.pop(phone, None)
            await send_text(
                "Struk ini sudah pernah diajukan sebelumnya, tidak diajukan ulang.",
                to=phone,
            )
            return

        row = await reimb_service.create(
            session,
            tenant_id=uuid.UUID(draft["tenant_id"]),
            user_id=uuid.UUID(draft["user_id"]),
            merchant=draft["merchant"] or "-",
            tanggal=tanggal,
            nominal=draft["nominal"],
            mata_uang=draft["mata_uang"],
            kategori=draft["kategori"],
            catatan=None,
            struk_file=draft["struk_file"],
            struk_hash=draft["struk_hash"],
        )
        await session.commit()
        row_id = str(row.id)

    _pending_reimb.pop(phone, None)
    await send_text(
        f"✅ Reimbursement diajukan & disetujui otomatis. ID: {row_id[:8]}",
        to=phone,
    )


async def handle_incoming_text(*, from_phone: str, text: str) -> None:
    """Resolve the sender, run the agent, send the reply back. Best-effort."""
    phone = normalize_phone(from_phone)

    if phone in _pending_reimb:
        await _apply_draft_correction(phone, text)
        return

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
