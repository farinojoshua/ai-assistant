"""Idempotent production seed, run on every backend start.

- creates one admin user if the users table is empty
  (SEED_ADMIN_EMAIL / SEED_ADMIN_PASSWORD, defaults admin@demo.test / rahasia123)
- loads the sample company data if v_stok does not exist yet
  (skip entirely with SEED_COMPANY_DATA=0 once the real company DB is wired in)
"""
from __future__ import annotations

import os
import pathlib
import uuid

import psycopg

from app.auth.security import hash_password
from app.config import get_settings

_SQL = (pathlib.Path(__file__).parent / "seed_company_db.sql").read_text("utf-8")


def _dsn(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def seed_admin() -> None:
    s = get_settings()
    with psycopg.connect(_dsn(s.app_database_url), autocommit=True) as conn:
        n = conn.execute("SELECT count(*) FROM users").fetchone()[0]
        if n:
            print(f"[seed] users already present ({n}), skipping admin")
            return
        email = os.environ.get("SEED_ADMIN_EMAIL", "admin@demo.test")
        password = os.environ.get("SEED_ADMIN_PASSWORD", "rahasia123")
        tid = uuid.uuid4()
        conn.execute(
            "INSERT INTO tenants (id, nama) VALUES (%s, %s)", (tid, "Default")
        )
        conn.execute(
            "INSERT INTO users (id, tenant_id, email, password_hash, nama, role)"
            " VALUES (%s, %s, %s, %s, %s, 'admin')",
            (uuid.uuid4(), tid, email, hash_password(password), "Admin"),
        )
        print(f"[seed] created admin user {email}")


def seed_company() -> None:
    if os.environ.get("SEED_COMPANY_DATA", "1") == "0":
        print("[seed] SEED_COMPANY_DATA=0, skipping company sample data")
        return
    s = get_settings()
    with psycopg.connect(
        _dsn(s.company_database_write_url), autocommit=True
    ) as conn:
        exists = conn.execute(
            "SELECT to_regclass('public.v_stok')"
        ).fetchone()[0]
        if exists:
            print("[seed] company data already present, skipping")
            return
        conn.execute(_SQL)
        print("[seed] loaded sample company data")


if __name__ == "__main__":
    seed_admin()
    seed_company()
