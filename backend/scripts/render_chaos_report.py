"""Render chaos_test_ticket_flow.py's JSON output as a WhatsApp-style chat
transcript and screenshot it. A host-side dev tool (needs Playwright, not a
backend dependency) — not meant to run inside the container.

Usage:
    python scripts/chaos_test_ticket_flow.py --json-out /tmp/chaos.json ...
    (copy /tmp/chaos.json out of the container, then:)
    python scripts/render_chaos_report.py /tmp/chaos.json /tmp/chaos.png
"""
from __future__ import annotations

import html
import json
import sys

from playwright.sync_api import sync_playwright

_CSS = """
body { margin: 0; background: #e5ddd5; font-family: -apple-system, "Segoe UI", sans-serif; }
.scenario { max-width: 480px; margin: 0 auto 24px; background: #e5ddd5; padding: 12px 0; }
.scenario-title {
  text-align: center; color: #54656f; font-size: 12px; font-weight: 600;
  background: #ffffffcc; margin: 0 12px 10px; padding: 6px 10px; border-radius: 8px;
}
.problems {
  max-width: 480px; margin: 0 auto 10px; background: #fdecea; color: #611a15;
  padding: 8px 12px; border-radius: 8px; font-size: 12px; white-space: pre-wrap;
}
.row { display: flex; margin: 3px 12px; }
.row.user { justify-content: flex-end; }
.row.bot { justify-content: flex-start; }
.bubble {
  max-width: 78%; padding: 6px 9px; border-radius: 8px; font-size: 13.5px;
  line-height: 1.35; white-space: pre-wrap; word-break: break-word;
  box-shadow: 0 1px 0.5px rgba(0,0,0,0.13);
}
.row.user .bubble { background: #d9fdd3; border-top-right-radius: 2px; }
.row.bot .bubble { background: #ffffff; border-top-left-radius: 2px; }
.row.bot .bubble.crash { background: #fdecea; color: #611a15; font-family: monospace; font-size: 11px; }
"""


def render_html(results: list[dict]) -> str:
    parts = [f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>"]
    for i, r in enumerate(results, 1):
        parts.append("<div class='scenario'>")
        parts.append(f"<div class='scenario-title'>Skenario {i} — seed: {html.escape(r['seed'])}</div>")
        if r["problems"]:
            probs = "\n".join(f"⚠ {p}" for p in r["problems"])
            parts.append(f"<div class='problems'>{html.escape(probs)}</div>")
        for who, msg in r["transcript"]:
            row_cls = "user" if who == "User" else "bot"
            bubble_cls = "bubble crash" if "[CRASH]" in msg else "bubble"
            parts.append(
                f"<div class='row {row_cls}'><div class='{bubble_cls}'>{html.escape(msg)}</div></div>"
            )
        parts.append("</div>")
    parts.append("</body></html>")
    return "\n".join(parts)


def main() -> None:
    json_path, png_path = sys.argv[1], sys.argv[2]
    with open(json_path, encoding="utf-8") as f:
        results = json.load(f)

    html_str = render_html(results)
    html_path = png_path.rsplit(".", 1)[0] + ".html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_str)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 520, "height": 800})
        page.goto(f"file://{html_path}")
        page.screenshot(path=png_path, full_page=True)
        browser.close()

    print(f"saved {html_path} and {png_path}")


if __name__ == "__main__":
    main()
