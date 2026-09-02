from __future__ import annotations

import pytest

from app.stock import ocr as ocr_mod
from app.stock.ocr import OcrError, extract_goods


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


async def test_parses_goods(vision) -> None:
    vision('{"produk":"cat tembok","merk":"Dulux","ukuran":"5kg",'
           '"jumlah":10,"satuan":"kaleng"}')
    g = await extract_goods(b"x", "image/jpeg")
    assert g.produk == "cat tembok"
    assert g.jumlah == 10
    assert g.deskripsi == "cat tembok Dulux 5kg"


async def test_jumlah_null_ok(vision) -> None:
    vision('```json\n{"produk":"semen","merk":null,"ukuran":"50kg",'
           '"jumlah":null,"satuan":"sak"}\n```')
    g = await extract_goods(b"x", "image/png")
    assert g.jumlah is None
    assert g.deskripsi == "semen 50kg"


async def test_jumlah_from_text(vision) -> None:
    vision('{"produk":"paku","jumlah":"sekitar 3 dus","satuan":"dus"}')
    g = await extract_goods(b"x", "image/jpeg")
    assert g.jumlah == 3


async def test_unrecognized_raises(vision) -> None:
    vision('{"produk":null,"merk":null,"ukuran":null,"jumlah":null}')
    with pytest.raises(OcrError):
        await extract_goods(b"x", "image/jpeg")
