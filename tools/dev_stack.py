"""Run identity and access on this machine WITHOUT Docker, for development and manual testing.

    uv run python tools/dev_stack.py            start (Ctrl+C stops everything)
    uv run python tools/dev_stack.py --reset    wipe the local data first

What it does, in order (the same steps `make up` + `make migrate` do with Docker Compose):
  1. starts a real PostgreSQL 16 from the `pgserver` pip package, data in .devdata/ (git-ignored)
  2. creates the databases and logins exactly like deploy/postgres/init.sh
  3. runs each service's Alembic migrations
  4. starts the services with uvicorn:   identity http://127.0.0.1:8001    access http://127.0.0.1:8002
     access verifies tokens against identity's JWKS over real HTTP, as in production

Then follow docs/manual-testing.md. There is no Envoy here, so call each service on its own port.
The signing key is kept in .devdata/signing.key so tokens survive a restart.
"""

from __future__ import annotations

import argparse
import base64
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pgserver
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / ".devdata"
SERVICES = {"identity": 8001, "access": 8002}  # add hierarchy, tasks, time here as they are built
PASSWORD = "dev-only"  # noqa: S105 (local throw-away database)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete .devdata/ (all local data) before starting")
    args = parser.parse_args()
    if args.reset and DATA.exists():
        shutil.rmtree(DATA)
    DATA.mkdir(exist_ok=True)

    print("[dev] starting PostgreSQL (pgserver) ...")
    server = pgserver.get_server(DATA / "pg", cleanup_mode="stop")
    admin = make_url(server.get_uri()).set(drivername="postgresql+psycopg")
    engine = create_engine(admin, isolation_level="AUTOCOMMIT", poolclass=NullPool)

    with engine.connect() as conn:  # same roles and databases as deploy/postgres/init.sh
        for role, attrs in (("app_user", "NOLOGIN"), ("app_worker", "NOLOGIN BYPASSRLS"), ("app_migrator", "NOLOGIN")):
            if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first():
                conn.execute(text(f"CREATE ROLE {role} {attrs}"))
        for svc in SERVICES:
            for login, group in ((f"{svc}_migrator", "app_migrator"), (f"{svc}_app", "app_user")):
                if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": login}).first():
                    conn.execute(text(f"CREATE ROLE {login} LOGIN PASSWORD '{PASSWORD}' IN ROLE {group}"))
            if not conn.execute(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": svc}).first():
                conn.execute(text(f"CREATE DATABASE {svc} OWNER {svc}_migrator"))

    key_file = DATA / "signing.key"
    if not key_file.exists():
        key_file.write_text(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("="))

    processes: list[subprocess.Popen[bytes]] = []
    try:
        for svc, port in SERVICES.items():
            migrator = admin.set(username=f"{svc}_migrator", password=PASSWORD, database=svc)
            app = admin.set(drivername="postgresql+asyncpg", username=f"{svc}_app", password=PASSWORD, database=svc)
            env = {
                **os.environ,
                "SERVICE_NAME": svc,
                "ENVIRONMENT": "local",
                "DATABASE_URL": app.render_as_string(hide_password=False),
                "MIGRATION_DATABASE_URL": migrator.render_as_string(hide_password=False),
                "JWKS_URL": f"http://127.0.0.1:{SERVICES['identity']}/.well-known/jwks.json",
                "SIGNING_PRIVATE_KEY": key_file.read_text().strip(),
                "TRUSTED_PROXY_HOPS": "0",  # no proxy in front: use the socket address for rate limits
                "HIERARCHY_URL": "",  # not built yet: workspaces activate without seeding a first space
                "CORS_ORIGINS": os.environ.get("CORS_ORIGINS", "http://localhost:5173"),
            }
            print(f"[dev] migrating {svc} ...")
            subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "services" / svc, env=env, check=True
            )
            print(f"[dev] starting {svc} on http://127.0.0.1:{port}")
            processes.append(
                subprocess.Popen(  # noqa: S603
                    [sys.executable, "-m", "uvicorn", f"{svc}_service.main:create_app", "--factory",
                     "--host", "127.0.0.1", "--port", str(port)],
                    cwd=ROOT, env=env,
                )
            )  # fmt: skip
        print("[dev] running. Ctrl+C to stop. Next: docs/manual-testing.md")
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        print("[dev] a service exited; stopping the rest")
    except KeyboardInterrupt:
        print("\n[dev] stopping ...")
    finally:
        for p in processes:
            p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
        server.cleanup()


if __name__ == "__main__":
    main()
