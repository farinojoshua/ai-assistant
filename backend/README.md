# AI Assistant — Backend

FastAPI backend. See `../docs/specs/` and `../docs/plans/`.

## Setup (Windows, Python 3.14, Podman)

```bash
python -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
cp .env.example .env            # edit secrets

podman compose up -d            # app_db :5432, company_db :5433
# one-time: create the test databases
podman exec backend-app_db-1 psql -U app -c "CREATE DATABASE app_test;"
podman exec backend-company_db-1 psql -U company -c "CREATE DATABASE company_test;"

./.venv/Scripts/alembic.exe upgrade head
./.venv/Scripts/python.exe scripts/seed_user.py --email admin@demo.test --password rahasia123
cat scripts/seed_company_db.sql | podman exec -i backend-company_db-1 psql -U company -q
```

## Run

```bash
./.venv/Scripts/python.exe run.py            # http://127.0.0.1:8000
./.venv/Scripts/python.exe run.py --reload   # autoreload
curl http://localhost:8000/health
```

Use `run.py`, not `uvicorn` directly: uvicorn hardcodes the ProactorEventLoop
on Windows and `run.py` swaps in the selector loop that psycopg3 needs.

### Auth quick check

```bash
curl -X POST localhost:8000/api/auth/login \
  -H 'content-type: application/json' \
  -d '{"email":"admin@demo.test","password":"rahasia123"}'
# -> {"access": "...", "refresh": "...", "token_type": "bearer"}
curl localhost:8000/api/me -H "Authorization: Bearer <access>"
```

## Test

```bash
./.venv/Scripts/python.exe -m pytest
```

Tests need `app_db` (Podman) up and an `app_test` database. Override the URL
with `TEST_APP_DATABASE_URL`.

## Notes

- psycopg3 async requires the selector event loop on Windows. `app/__init__.py`
  sets the policy (covers alembic, scripts, pytest); `run.py` overrides
  uvicorn's hardcoded ProactorEventLoop factory. The `set_event_loop_policy`
  deprecation warning (removed in Python 3.16) is known tech debt — revisit
  when moving to a Linux deploy or Python 3.15.
