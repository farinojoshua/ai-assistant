"""Receipt OCR: image bytes -> structured fields, via the vision model."""
from __future__ import annotations

import base64
import json
import re
from datetime import date

from pydantic import BaseModel, field_validator

from app.llm.registry import get_vision_provider

_PROMPT = (
    "Ini foto struk / bukti pembayaran. Ekstrak dan jawab HANYA satu objek "
    "JSON valid, tanpa penjelasan:\n"
    '{"merchant": string|null, "tanggal": "YYYY-MM-DD"|null, '
    '"nominal": number|null, "kategori": string|null, "mata_uang": "IDR"}\n'
    "nominal = total akhir yang dibayar, angka saja tanpa titik/koma/simbol. "
    "kategori = satu kata singkat (mis. bbm, makan, parkir, transport, "
    "atk, lainnya). Kalau sebuah field tidak terbaca, pakai null."
)


class OcrError(Exception):
    pass


class ReceiptData(BaseModel):
    merchant: str | None = None
    tanggal: date | None = None
    nominal: float | None = None
    kategori: str | None = None
    mata_uang: str = "IDR"

    @field_validator("tanggal", mode="before")
    @classmethod
    def _empty_date(cls, v):
        return v or None

    @field_validator("nominal", mode="before")
    @classmethod
    def _clean_nominal(cls, v):
        if v in (None, "", "null"):
            return None
        if isinstance(v, (int, float)):
            return float(v)
        # strings from the model: "Rp 43.000", "30,000", "43.000,50"
        s = re.sub(r"[^\d.,]", "", str(v))
        if not s:
            return None
        m = re.search(r"[.,](\d+)$", s)
        # trailing group of 1-2 digits after the last separator = decimal
        if m and 1 <= len(m.group(1)) <= 2 and re.search(r"\d", s[: m.start()]):
            whole = re.sub(r"\D", "", s[: m.start()])
            return float(f"{whole}.{m.group(1)}")
        return float(re.sub(r"\D", "", s))


def _extract_json(raw: str) -> dict:
    raw = raw.strip()
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        raise OcrError("model tidak mengembalikan JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise OcrError(f"JSON dari model tidak valid: {e}") from None


async def extract_receipt(image_bytes: bytes, media_type: str) -> ReceiptData:
    provider = get_vision_provider()
    b64 = base64.b64encode(image_bytes).decode()
    raw = await provider.chat_vision(_PROMPT, b64, media_type)
    data = ReceiptData.model_validate(_extract_json(raw))
    if data.merchant is None and data.nominal is None:
        raise OcrError(
            "tidak bisa membaca struk — pastikan foto jelas dan tegak"
        )
    return data
