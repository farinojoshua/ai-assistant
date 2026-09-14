"""Live, browser-watchable chaos-test run — grid mode.

Runs N scenarios CONCURRENTLY against the real ticket_flow (WA sends
mocked/captured, not actually delivered), using the exact same
run_scenario() as chaos_test_ticket_flow.py so the live viewer gets the
same coherence heuristics as the batch script instead of a second,
drifting copy of the loop.

Each concurrent run gets its own panel in a grid on the page, like N
WhatsApp chats side by side. Completed runs accumulate into a
server-side history (not overwritten by the next batch) — click
"Download" to get one JSON file with everything accumulated so far, then
"Hapus" to clear it and start the next batch fresh.

Dev-only tool. Run inside the backend container (needs its deps):
    python scripts/live_chaos_server.py
Then proxy 127.0.0.1:3101 to wherever you're watching from.
"""
from __future__ import annotations

import asyncio
import json
import random
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from chaos_test_ticket_flow import _SEEDS, run_scenario

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI()

# One "batch" is however many runs were most recently started together —
# _active is replaced wholesale on each /api/start call so the grid shows
# exactly that batch. Finished runs (from any batch) pile up in _history
# regardless, independent of what's currently shown on screen.
_active: dict[str, dict] = {}
_history: list[dict] = []


@app.post("/api/start")
async def start(n: int = 10, max_turns: int = 18, delay: float = 1.2):
    n = max(1, min(n, 30))  # sane upper bound — this is N concurrent LLM personas
    _active.clear()

    runs = []
    for _ in range(n):
        run_id = uuid.uuid4().hex[:8]
        seed = random.choice(_SEEDS)
        _active[run_id] = {"seed": seed, "messages": [], "problems": [], "done": False}
        runs.append({"run_id": run_id, "seed": seed})

        async def on_update(transcript, problems, _run_id=run_id):
            _active[_run_id]["messages"] = list(transcript)
            _active[_run_id]["problems"] = list(problems)

        # on_update must be captured as a default arg too, not a free
        # variable — a free variable resolves at CALL time against
        # whatever the loop last rebound the name to, so every concurrent
        # _run() ended up calling the LAST iteration's on_update and every
        # run's transcript landed in one run_id's panel (found by actually
        # running a batch of 10 and seeing 9 empty panels + one garbled one).
        async def _run(_run_id=run_id, _seed=seed, _on_update=on_update) -> None:
            result = await run_scenario(_seed, max_turns, on_update=_on_update, delay_s=delay)
            result["run_id"] = _run_id
            result["finished_at"] = datetime.now(timezone.utc).isoformat()
            _history.append(result)
            if _run_id in _active:
                _active[_run_id]["done"] = True

        asyncio.create_task(_run())

    return {"started": True, "runs": runs}


@app.get("/api/state")
async def state():
    return {"active": _active, "history_count": len(_history)}


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
#bar { position:sticky; top:0; z-index:10; background:#075e54; color:#fff; padding:10px 14px;
       display:flex; gap:8px; align-items:center; font-size:14px; flex-wrap:wrap; }
#bar button { padding:6px 12px; border:none; border-radius:6px; cursor:pointer; }
#bar input { width:52px; padding:5px 6px; border-radius:6px; border:none; }
#status { color:#cbe6e2; font-size:12px; }
#count { color:#fff; font-size:13px; margin-left:auto; background:#0a7a6c;
         padding:4px 10px; border-radius:12px; }
#grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(280px, 1fr));
        gap:10px; padding:10px; }
.panel { background:#e5ddd5; border-radius:8px; overflow:hidden; display:flex;
         flex-direction:column; max-height:70vh; box-shadow:0 1px 3px rgba(0,0,0,.2); }
.panel .head { background:#128c7e; color:#fff; font-size:12px; padding:6px 8px;
               display:flex; justify-content:space-between; gap:6px; }
.panel .head .seed { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.panel .head .st { opacity:.85; flex-shrink:0; }
.panel .feed { padding:8px; overflow-y:auto; flex:1; }
.row { display:flex; margin:3px 0; }
.row.user { justify-content:flex-end; }
.row.bot { justify-content:flex-start; }
.bubble { max-width:85%; padding:5px 8px; border-radius:8px; font-size:12px;
          line-height:1.3; white-space:pre-wrap; word-break:break-word;
          box-shadow:0 1px 0.5px rgba(0,0,0,.13); }
.row.user .bubble { background:#d9fdd3; border-top-right-radius:2px; }
.row.bot .bubble { background:#fff; border-top-left-radius:2px; }
.panel.hasproblem .head { background:#b23c3c; }
</style></head>
<body>
<div id="bar">
  <button onclick="startBatch()">▶ Mulai</button>
  <input id="n" type="number" value="10" min="1" max="30">
  <span>run bareng</span>
  <button onclick="downloadHistory()">⬇ Download</button>
  <button onclick="clearHistory()">🗑 Hapus</button>
  <span id="status">idle</span>
  <span id="count">0 run tersimpan</span>
</div>
<div id="grid"></div>
<script>
let shown = {};  // run_id -> messages rendered so far
async function startBatch() {
  shown = {};
  document.getElementById('grid').innerHTML = '';
  const n = parseInt(document.getElementById('n').value, 10) || 10;
  const r = await fetch('api/start?n=' + n, {method: 'POST'});
  const data = await r.json();
  for (const run of data.runs) {
    shown[run.run_id] = 0;
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.id = 'panel-' + run.run_id;
    panel.innerHTML = '<div class="head"><span class="seed">' + escapeHtml(run.seed) +
      '</span><span class="st">jalan...</span></div><div class="feed"></div>';
    document.getElementById('grid').appendChild(panel);
  }
}
function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
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
function bubble(feed, who, msg) {
  const row = document.createElement('div');
  row.className = 'row ' + (who === 'User' ? 'user' : 'bot');
  const b = document.createElement('div');
  b.className = 'bubble';
  b.textContent = msg;
  row.appendChild(b);
  feed.appendChild(row);
  feed.scrollTop = feed.scrollHeight;
}
async function poll() {
  const r = await fetch('api/state');
  const s = await r.json();
  let anyRunning = false;
  for (const [runId, run] of Object.entries(s.active)) {
    const panel = document.getElementById('panel-' + runId);
    if (!panel) continue;
    const feed = panel.querySelector('.feed');
    const already = shown[runId] || 0;
    for (let i = already; i < run.messages.length; i++) {
      bubble(feed, run.messages[i][0], run.messages[i][1]);
    }
    shown[runId] = run.messages.length;
    panel.querySelector('.st').textContent = run.done ? 'selesai' : 'jalan...';
    panel.classList.toggle('hasproblem', run.problems.length > 0);
    if (!run.done) anyRunning = true;
  }
  document.getElementById('status').textContent = anyRunning ? 'sedang jalan...' :
    (Object.keys(s.active).length ? 'semua selesai' : 'idle');
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
