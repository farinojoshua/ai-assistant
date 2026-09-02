"""Goods photo -> product description + best-guess quantity, via vision."""
from __future__ import annotations

import base64
import json
import re

from pydantic import BaseModel, field_validator

from app.llm.registry import get_vision_provider

_PROMPT = (
    "Ini foto barang stok gudang. Ekstrak dan jawab HANYA satu objek JSON "
    "valid, tanpa penjelasan:\n"
    '{"produk": string|null, "merk": string|null, "ukuran": string|null, '
    '"jumlah": integer|null, "satuan": string|null}\n'
    "produk = jenis barang (mis. 'cat tembok', 'kaleng cat', 'semen'). "
    "jumlah = perkiraan berapa unit/kaleng/dus yang terlihat di foto; kalau "
    "tidak yakin, null. satuan = pcs/kaleng/dus/sak/kg dst. Kalau sebuah "
    "field tidak terbaca, pakai null."
)


class OcrError(Exception):
    pass


class GoodsData(BaseModel):
    produk: str | None = None
    merk: str | None = None
    ukuran: str | None = None
    jumlah: int | None = None
    satuan: str | None = None

    @field_validator("jumlah", mode="before")
    @classmethod
    def _clean_jumlah(cls, v):
        if v in (None, "", "null"):
            return None
        if isinstance(v, str):
            m = re.search(r"\d+", v)
            return int(m.group()) if m else None
        return int(v)

    @property
    def deskripsi(self) -> str:
        return " ".join(
            p for p in (self.produk, self.merk, self.ukuran) if p
        ).strip()


def _extract_json(raw: str) -> dict:
    m = re.search(r"\{.*\}", raw.strip(), re.DOTALL)
    if not m:
        raise OcrError("model tidak mengembalikan JSON")
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise OcrError(f"JSON dari model tidak valid: {e}") from None


async def extract_goods(image_bytes: bytes, media_type: str) -> GoodsData:
    provider = get_vision_provider()
    b64 = base64.b64encode(image_bytes).decode()
    raw = await provider.chat_vision(_PROMPT, b64, media_type)
    data = GoodsData.model_validate(_extract_json(raw))
    if not data.deskripsi:
        raise OcrError(
            "tidak bisa mengenali barang di foto — pastikan label terlihat jelas"
        )
    return data
