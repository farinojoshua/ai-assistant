"""Live, browser-watchable chaos-test run.

Runs one scenario against the real ticket_flow (WA sends mocked/captured,
not actually delivered), streaming each turn into an in-memory list with a
short pause between turns so a page polling /state can render it appearing
live, WhatsApp-bubble style — same idea as render_chaos_report.py's static
screenshot, but running in front of you instead of after the fact.

Dev-only tool. Run inside the backend container (needs its deps):
    python scripts/live_chaos_server.py
Then proxy 127.0.0.1:3101 to wherever you're watching from.
"""
from __future__ import annotations

import asyncio
import random
import sys
import traceback
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from chaos_test_ticket_flow import _next_persona_message, _SEEDS

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from app.whatsapp import ticket_flow

app = FastAPI()

_state: dict = {"messages": [], "done": False, "running": False}


class _FakeUser:
    def __init__(self) -> None:
        self.id = uuid.uuid4()
        self.tenant_id = uuid.uuid4()


async def _run_live(seed: str, max_turns: int, delay_s: float) -> None:
    _state["messages"] = []
    _state["done"] = False
    _state["running"] = True

    phone = f"628{random.randint(100000000, 999999999)}"
    user = _FakeUser()
    transcript: list[tuple[str, str]] = []
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
        for _turn in range(max_turns):
            sent.clear()
            transcript.append(("User", user_msg))
            _state["messages"] = list(transcript)
            await asyncio.sleep(delay_s)

            try:
                if ticket_flow.is_active(phone):
                    await ticket_flow.handle_text(phone, user_msg, user=user)
                elif ticket_flow.should_start(user_msg):
                    await ticket_flow.start(phone, user_msg, user=user)
                else:
                    sent.append("(tidak masuk alur tiket sama sekali)")
            except Exception:  # noqa: BLE001
                transcript.append(("Bot", f"[CRASH]\n{traceback.format_exc()}"))
                _state["messages"] = list(transcript)
                break

            bot_reply = "\n---\n".join(sent) if sent else "(TIDAK ADA BALASAN)"
            transcript.append(("Bot", bot_reply))
            _state["messages"] = list(transcript)
            await asyncio.sleep(delay_s)

            if not ticket_flow.is_active(phone):
                break

            user_msg = await _next_persona_message(transcript)
            if not user_msg:
                break

        ticket_flow._pending.pop(phone, None)

    _state["done"] = True
    _state["running"] = False


@app.post("/api/start")
async def start(seed: str | None = None, max_turns: int = 18, delay: float = 1.2):
    if _state["running"]:
        return JSONResponse({"error": "sudah ada run yang jalan"}, status_code=409)
    chosen = seed or random.choice(_SEEDS)
    asyncio.create_task(_run_live(chosen, max_turns, delay))
    return {"started": True, "seed": chosen}


@app.get("/api/state")
async def state():
    return _state


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!doctype html><html><head><meta charset="utf-8">
<base href="/chaos-live/">
<title>Live chaos test</title>
<style>
body { margin:0; background:#e5ddd5; font-family:-apple-system,"Segoe UI",sans-serif; }
#bar { position:sticky; top:0; background:#075e54; color:#fff; padding:10px 14px;
       display:flex; gap:8px; align-items:center; font-size:14px; }
#bar button { padding:6px 12px; border:none; border-radius:6px; cursor:pointer; }
#feed { max-width:480px; margin:0 auto; padding:12px 0 40px; }
.row { display:flex; margin:3px 12px; }
.row.user { justify-content:flex-end; }
.row.bot { justify-content:flex-start; }
.bubble { max-width:78%; padding:6px 9px; border-radius:8px; font-size:13.5px;
          line-height:1.35; white-space:pre-wrap; word-break:break-word;
          box-shadow:0 1px 0.5px rgba(0,0,0,.13); }
.row.user .bubble { background:#d9fdd3; border-top-right-radius:2px; }
.row.bot .bubble { background:#fff; border-top-left-radius:2px; }
#status { color:#cbe6e2; font-size:12px; margin-left:auto; }
</style></head>
<body>
<div id="bar">
  <button onclick="start()">▶ Mulai run baru</button>
  <span id="status">idle</span>
</div>
<div id="feed"></div>
<script>
let shown = 0;
async function start() {
  shown = 0;
  document.getElementById('feed').innerHTML = '';
  await fetch('api/start', {method: 'POST'});
}
function bubble(who, msg) {
  const row = document.createElement('div');
  row.className = 'row ' + (who === 'User' ? 'user' : 'bot');
  const b = document.createElement('div');
  b.className = 'bubble';
  b.textContent = msg;
  row.appendChild(b);
  document.getElementById('feed').appendChild(row);
  window.scrollTo(0, document.body.scrollHeight);
}
async function poll() {
  const r = await fetch('api/state');
  const s = await r.json();
  for (let i = shown; i < s.messages.length; i++) {
    bubble(s.messages[i][0], s.messages[i][1]);
  }
  shown = s.messages.length;
  document.getElementById('status').textContent = s.running ? 'sedang jalan...' : (s.done ? 'selesai' : 'idle');
}
setInterval(poll, 800);
poll();
</script>
</body></html>
"""


if __name__ == "__main__":
    # 0.0.0.0, not 127.0.0.1 — this runs inside the container, and the
    # published port only reaches the container's own loopback if the app
    # binds to all interfaces, not just its internal 127.0.0.1.
    uvicorn.run(app, host="0.0.0.0", port=3101)
