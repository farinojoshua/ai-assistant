#!/usr/bin/env sh
set -e

echo "[entrypoint] waiting for databases..."
python - <<'PY'
import time, os, psycopg
for name, url in (("app", os.environ["APP_DATABASE_URL"]),
                  ("company", os.environ["COMPANY_DATABASE_URL"])):
    dsn = url.replace("postgresql+psycopg://", "postgresql://")
    for _ in range(60):
        try:
            psycopg.connect(dsn, connect_timeout=2).close()
            print(f"[entrypoint] {name} db up")
            break
        except Exception:
            time.sleep(1)
    else:
        raise SystemExit(f"[entrypoint] {name} db never came up")
PY

echo "[entrypoint] running migrations..."
alembic upgrade head

echo "[entrypoint] seeding (idempotent)..."
python scripts/seed_prod.py

echo "[entrypoint] starting uvicorn..."
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --loop asyncio
