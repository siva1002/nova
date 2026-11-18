"""Create roles and databases for local development.

Reads credentials from .devdata/pg.env if present; all values can be overridden
by environment variables.

Usage:
    uv run python tools/create_dbs.py           # create (idempotent)
    uv run python tools/create_dbs.py --reset   # drop and recreate
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".devdata" / "pg.env"

if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

PG_HOST = os.environ.get("PG_HOST", "127.0.0.1")
PG_PORT = os.environ.get("PG_PORT", "5432")
PG_SUPERUSER = os.environ.get("PG_SUPERUSER", "postgres")
PG_SUPERUSER_PASSWORD = os.environ.get("PG_SUPERUSER_PASSWORD", "password")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "password")
MIGRATOR_PASSWORD = os.environ.get("MIGRATOR_PASSWORD", "password")

SERVICES = ["identity", "access", "hierarchy", "tasks", "time"]


def engine():
    url = f"postgresql+psycopg://{PG_SUPERUSER}:{PG_SUPERUSER_PASSWORD}@{PG_HOST}:{PG_PORT}/postgres"
    return create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)


def reset(conn) -> None:
    for svc in SERVICES:
        conn.execute(text(f"DROP DATABASE IF EXISTS {svc}"))
        conn.execute(text(f"DROP ROLE IF EXISTS {svc}_app"))
        conn.execute(text(f"DROP ROLE IF EXISTS {svc}_migrator"))
        print(f"[db] dropped {svc}")


def provision(conn) -> None:
    for role, attrs in (
        ("app_user", "NOLOGIN"),
        ("app_worker", "NOLOGIN BYPASSRLS"),
        ("app_migrator", "NOLOGIN"),
    ):
        if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first():
            conn.execute(text(f"CREATE ROLE {role} {attrs}"))

    for svc in SERVICES:
        for login, group, pwd in (
            (f"{svc}_migrator", "app_migrator", MIGRATOR_PASSWORD),
            (f"{svc}_app", "app_user", APP_PASSWORD),
        ):
            if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": login}).first():
                conn.execute(text(f"CREATE ROLE {login} LOGIN PASSWORD '{pwd}' IN ROLE {group}"))

        if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": svc}).first():
            conn.execute(text(f"CREATE DATABASE {svc} OWNER {svc}_migrator"))
            conn.execute(text(f"REVOKE ALL ON DATABASE {svc} FROM PUBLIC"))
            conn.execute(text(f"GRANT CONNECT ON DATABASE {svc} TO {svc}_app, {svc}_migrator"))
            print(f"[db] created {svc}")
        else:
            print(f"[db] {svc} already exists, skipping")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop and recreate roles/databases")
    args = parser.parse_args()

    with engine().connect() as conn:
        if args.reset:
            reset(conn)
        provision(conn)


if __name__ == "__main__":
    main()
