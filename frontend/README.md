# AI Assistant — Frontend

Minimal Next.js chat UI for the backend.

## Setup

```bash
npm install
cp .env.local.example .env.local     # NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev                          # http://localhost:3000
```

The backend must be running (`../backend` → `python run.py`) and its
`cors_origins` must include `http://localhost:3000` (default).

## What it does

- Login screen (dev credentials prefilled: `admin@demo.test` / `rahasia123`),
  JWT stored in `localStorage`.
- One chat page. Sends `POST /api/chat`, reads the SSE stream, renders
  `tool` notes inline and `token` answers as bubbles. Keeps `conversation_id`
  so follow-up questions have context.

## Notes

- `next dev` regenerates `AGENTS.md` / `CLAUDE.md` in this folder each run;
  they are gitignored.
- Pinned to `next@15.5.25` (patched for CVE-2025-66478). `next@latest` pulls
  Next 16 which has breaking changes.
