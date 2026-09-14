"""Live, browser-watchable chaos-test run.

Runs scenarios against the real ticket_flow (WA sends mocked/captured, not
actually delivered) using the exact same run_scenario() as
chaos_test_ticket_flow.py — so the live viewer gets the same coherence
heuristics as the batch script instead of a second, drifting copy of the
loop (which is what the first version of this file did).

Workflow: click "Mulai run baru" as many times as you want — each finished
run is appended to an in-memory history (not overwritten). When ready to
hand a batch off for fixing, click "Download" to get one JSON file with
every accumulated run, then "Hapus" to clear the server-side history and
start the next batch fresh.

Dev-only tool. Run inside the backend container (needs its deps):
    python scripts/live_chaos_server.py
Then proxy 127.0.0.1:3101 to wherever you're watching from.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from chaos_test_ticket_flow import _SEEDS, run_scenario

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI()

_state: dict = {"messages": [], "problems": [], "done": False, "running": False}
_history: list[dict] = []


@app.post("/api/start")
async def start(seed: str | None = None, max_turns: int = 18, delay: float = 1.2):
    if _state["running"]:
        return JSONResponse({"error": "sudah ada run yang jalan"}, status_code=409)
    chosen = seed or random.choice(_SEEDS)

    _state["messages"] = []
    _state["problems"] = []
    _state["done"] = False
    _state["running"] = True

    async def on_update(transcript, problems):
        _state["messages"] = list(transcript)
        _state["problems"] = list(problems)

    async def _run() -> None:
        result = await run_scenario(chosen, max_turns, on_update=on_update, delay_s=delay)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        _history.append(result)
        _state["done"] = True
        _state["running"] = False

    asyncio.create_task(_run())
    return {"started": True, "seed": chosen}


@app.get("/api/state")
async def state():
    return {**_state, "history_count": len(_history)}


@app.get("/api/download")
async def download():
    payload = json.dumps(_history, ensure_ascii=False, indent=2)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="chaos-results-{ts}.json"'},
    )


@app.post("/api/clear")
async def clear():
    _history.clear()
    return {"cleared": True}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!doctype html><html><head><meta charset="utf-8">
<base href="/chaos-live/">
<title>Live chaos test</title>
<style>
body { margin:0; background:#e5ddd5; font-family:-apple-system,"Segoe UI",sans-serif; }
#bar { position:sticky; top:0; background:#075e54; color:#fff; padding:10px 14px;
       display:flex; gap:8px; align-items:center; font-size:14px; flex-wrap:wrap; }
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
#status { color:#cbe6e2; font-size:12px; }
#count { color:#fff; font-size:13px; margin-left:auto; background:#0a7a6c;
         padding:4px 10px; border-radius:12px; }
</style></head>
<body>
<div id="bar">
  <button onclick="start()">▶ Mulai run baru</button>
  <button onclick="downloadHistory()">⬇ Download</button>
  <button onclick="clearHistory()">🗑 Hapus</button>
  <span id="status">idle</span>
  <span id="count">0 run tersimpan</span>
</div>
<div id="feed"></div>
<script>
let shown = 0;
async function start() {
  shown = 0;
  document.getElementById('feed').innerHTML = '';
  await fetch('api/start', {method: 'POST'});
}
async function downloadHistory() {
  const r = await fetch('api/download');
  const blob = await r.blob();
  const disposition = r.headers.get('Content-Disposition') || '';
  const match = disposition.match(/filename="(.+)"/);
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = match ? match[1] : 'chaos-results.json';
  document.body.appendChild(a);
  a.click();
  a.remove();
}
async function clearHistory() {
  if (!confirm('Hapus semua hasil run yang tersimpan di server?')) return;
  await fetch('api/clear', {method: 'POST'});
  poll();
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
  document.getElementById('count').textContent = s.history_count + ' run tersimpan';
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
