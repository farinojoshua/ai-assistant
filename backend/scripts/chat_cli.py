"""Interactive terminal chat against a running backend.

    python scripts/chat_cli.py
    python scripts/chat_cli.py --url http://localhost:8000 --email admin@demo.test

Type your question, Enter to send, Ctrl-C to quit.
"""
from __future__ import annotations

import argparse
import json
import sys

import httpx


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--email", default="admin@demo.test")
    ap.add_argument("--password", default="rahasia123")
    args = ap.parse_args()

    with httpx.Client(base_url=args.url, timeout=120) as c:
        r = c.post(
            "/api/auth/login",
            json={"email": args.email, "password": args.password},
        )
        if r.status_code != 200:
            sys.exit(f"login gagal: {r.status_code} {r.text}")
        token = r.json()["access"]
        headers = {"Authorization": f"Bearer {token}"}
        conv_id: str | None = None
        print(f"Terhubung ke {args.url} sebagai {args.email}. Ctrl-C untuk keluar.\n")

        while True:
            try:
                msg = input("anda> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return
            if not msg:
                continue

            body = {"message": msg}
            if conv_id:
                body["conversation_id"] = conv_id

            with c.stream(
                "POST", "/api/chat", json=body, headers=headers
            ) as resp:
                event = None
                for line in resp.iter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        if event == "tool":
                            print(f"  [tool: {data['name']} {data['arguments']}]")
                        elif event == "token":
                            print(f"ai> {data['text']}\n")
                        elif event == "error":
                            print(f"  [error: {data['message']}]\n")
                        elif event == "done":
                            conv_id = data["conversation_id"]


if __name__ == "__main__":
    main()
