"""Chaos-test the WA ticket_flow with an LLM playing an unstructured,
non-technical human — typos, jumbled order, multiple facts crammed into one
message, changing their mind, going off-topic — instead of the clean
one-fact-per-turn messages a developer tends to type when testing by hand.

Runs entirely in-process against the real SAMS API (whatever
SAMS_BASE_URL/SAMS_ALLOW_MUTATIONS currently point at — check .env before
running so a chaos run can't accidentally book/pay for real). WhatsApp
sends are mocked (captured into the transcript, nothing actually goes out).

Usage (inside the backend container, where SAMS_* env vars are set):
    python scripts/chaos_test_ticket_flow.py
    python scripts/chaos_test_ticket_flow.py --scenarios 5 --max-turns 20
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import random
import traceback
import uuid
from unittest.mock import patch

from app.llm.base import Message
from app.llm.registry import get_provider
from app.whatsapp import ticket_flow

logging.getLogger("app").setLevel(logging.CRITICAL)  # keep chaos-run output readable

_PERSONA_PROMPT = """\
Kamu berperan sebagai ORANG AWAM (bukan orang IT) yang lagi chat WhatsApp \
mau pesan tiket bioskop. Gaya bicaramu:
- Santai, sering typo, pakai singkatan (gak/ga, yg, tp, blm, dst)
- Kadang gabung beberapa info sekaligus dalam satu pesan ("mau nonton di \
gombong besok deh 2 orang"), kadang sebaliknya jawab sepotong-sepotong
- Kadang jawab agak muter/gak langsung ke inti sebelum akhirnya jawab
- Sesekali ganti pikiran di tengah jalan (ganti kota/bioskop/tanggal)
- Sesekali pakai emoji
- Jangan pernah ngaku kamu AI, kamu BENERAN pengguna asli yang mau nonton
- JAWAB CUMA dengan SATU pesan WhatsApp berikutnya yang mau kamu kirim ke \
bot, tanpa tanda kutip, tanpa penjelasan tambahan, tanpa awalan "User:"

Riwayat chat sejauh ini (kamu = User, lawan bicara = Bot):
{history}

Tujuanmu: sampai berhasil pesan tiket bioskop (sampai tahap "Kirim" \
kursi), lalu ketik 'batal' untuk keluar (JANGAN tekan Bayar — cukup \
sampai draft booking, lalu batalkan). Kalau udah kejebak/bingung lebih \
dari 2x di step yang sama, coba ketik 'batal' dan berhenti. Balas pesan \
WhatsApp berikutnya:
"""

_SEEDS = [
    "halo mau nonton dong",
    "eh bisa pesen tiket ga",
    "mau nnton pilm hri ini ada apa aja",
    "gan ada bioskop dmn aja",
    "pesan tiket ya",
]


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()


async def _next_persona_message(history: list[tuple[str, str]]) -> str:
    provider = get_provider()
    history_text = "\n".join(f"{who}: {msg}" for who, msg in history)
    resp = await provider.chat(
        [Message(role="user", content=_PERSONA_PROMPT.format(history=history_text))],
        [],
    )
    return (resp.text or "").strip().strip('"').strip()


async def run_scenario(seed: str, max_turns: int) -> dict:
    phone = f"628{random.randint(100000000, 999999999)}"
    user = _FakeUser()
    transcript: list[tuple[str, str]] = []
    problems: list[str] = []
    sent: list[str] = []

    async def fake_send_text(msg, to=None):
        sent.append(msg)

    async def fake_send_buttons(msg, buttons, to=None):
        labels = " / ".join(f"[{title}]" for _, title in buttons)
        sent.append(f"{msg}\n(tombol: {labels})")

    async def fake_send_image(image_bytes, caption, to=None):
        sent.append(f"(gambar {len(image_bytes)} bytes) {caption}")

    with patch("app.whatsapp.ticket_flow.send_text", fake_send_text), patch(
        "app.whatsapp.ticket_flow.send_buttons", fake_send_buttons
    ), patch("app.whatsapp.ticket_flow.send_image", fake_send_image):
        user_msg = seed
        for turn in range(max_turns):
            sent.clear()
            transcript.append(("User", user_msg))

            try:
                if ticket_flow.is_active(phone):
                    await ticket_flow.handle_text(phone, user_msg, user=user)
                elif ticket_flow.should_start(user_msg):
                    await ticket_flow.start(phone, user_msg, user=user)
                else:
                    sent.append("(tidak masuk alur tiket sama sekali)")
            except Exception:  # noqa: BLE001 - this is exactly what we're hunting for
                tb = traceback.format_exc()
                problems.append(f"turn {turn}: UNCAUGHT EXCEPTION\n{tb}")
                transcript.append(("Bot", f"[CRASH]\n{tb}"))
                break

            if not sent:
                problems.append(f"turn {turn}: bot gave NO reply at all (silent failure)")
                bot_reply = "(TIDAK ADA BALASAN)"
            else:
                bot_reply = "\n---\n".join(sent)
            transcript.append(("Bot", bot_reply))

            if not ticket_flow.is_active(phone):
                break

            user_msg = await _next_persona_message(transcript)
            if not user_msg:
                problems.append(f"turn {turn}: persona LLM produced an empty message, stopping")
                break

        ticket_flow._pending.pop(phone, None)

    return {"seed": seed, "transcript": transcript, "problems": problems}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenarios", type=int, default=len(_SEEDS))
    ap.add_argument("--max-turns", type=int, default=20)
    args = ap.parse_args()

    seeds = (_SEEDS * ((args.scenarios // len(_SEEDS)) + 1))[: args.scenarios]
    all_problems: list[str] = []

    for i, seed in enumerate(seeds, 1):
        print(f"\n{'=' * 70}\nSKENARIO {i}/{len(seeds)} — seed: {seed!r}\n{'=' * 70}")
        result = await run_scenario(seed, args.max_turns)
        for who, msg in result["transcript"]:
            print(f"\n[{who}] {msg}")
        if result["problems"]:
            print(f"\n!!! MASALAH di skenario {i}:")
            for p in result["problems"]:
                print(f"  - {p}")
            all_problems.extend(f"skenario {i} ({seed!r}): {p}" for p in result["problems"])
        else:
            print(f"\n(skenario {i} selesai tanpa masalah terdeteksi)")

    print(f"\n\n{'#' * 70}\nRINGKASAN: {len(all_problems)} masalah ditemukan di {len(seeds)} skenario\n{'#' * 70}")
    for p in all_problems:
        print(f"  - {p}")


if __name__ == "__main__":
    asyncio.run(main())
