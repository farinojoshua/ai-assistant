from __future__ import annotations

from datetime import date

import pytest

from app.reimbursement import ocr as ocr_mod
from app.reimbursement.ocr import OcrError, extract_receipt


class _FakeVision:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def chat_vision(self, prompt, image_b64, media_type):
        return self.reply


@pytest.fixture
def vision(monkeypatch):
    def _set(reply: str):
        monkeypatch.setattr(
            ocr_mod, "get_vision_provider", lambda *a, **k: _FakeVision(reply)
        )

    return _set


async def test_parses_clean_json(vision) -> None:
    vision('{"merchant":"SPBU RTA MILONO","tanggal":"2023-06-24",'
           '"nominal":30000,"kategori":"bbm","mata_uang":"IDR"}')
    r = await extract_receipt(b"x", "image/jpeg")
    assert r.merchant == "SPBU RTA MILONO"
    assert r.tanggal == date(2023, 6, 24)
    assert r.nominal == 30000.0
    assert r.kategori == "bbm"


async def test_strips_code_fences_and_formatting(vision) -> None:
    vision('```json\n{"merchant":"Toko A","tanggal":null,'
           '"nominal":"Rp 43.000","kategori":"makan"}\n```')
    r = await extract_receipt(b"x", "image/png")
    assert r.nominal == 43000.0
    assert r.tanggal is None


async def test_not_a_receipt_raises(vision) -> None:
    vision('{"merchant":null,"tanggal":null,"nominal":null,"kategori":null}')
    with pytest.raises(OcrError):
        await extract_receipt(b"x", "image/jpeg")


async def test_non_json_raises(vision) -> None:
    vision("maaf saya tidak bisa membaca gambar ini")
    with pytest.raises(OcrError):
        await extract_receipt(b"x", "image/jpeg")
