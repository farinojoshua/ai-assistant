# AI Assistant — Backend

FastAPI backend. See `../docs/specs/` and `../docs/plans/`.

## Setup (Windows, Python 3.14, Podman)

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
cp .env.example .env            # edit secrets

podman compose up -d            # app_db :5432, company_db :5433
# one-time: create the test database
podman exec backend-app_db-1 psql -U app -c "CREATE DATABASE app_test;"

./.venv/Scripts/alembic.exe upgrade head
./.venv/Scripts/python.exe scripts/seed_user.py --email admin@demo.test --password rahasia123
```

## Run

```bash
./.venv/Scripts/python.exe -m uvicorn app.main:app --reload --port 8000
curl http://localhost:8000/health
```

## Test

```bash
./.venv/Scripts/python.exe -m pytest
```

Tests need `app_db` (Podman) up and an `app_test` database. Override the URL
with `TEST_APP_DATABASE_URL`.

## Notes

- psycopg3 async requires the selector event loop on Windows; `app/__init__.py`
  installs it. The `set_event_loop_policy` deprecation warning (removed in
  Python 3.16) is known tech debt — revisit when moving to a Linux deploy or
  Python 3.15.
