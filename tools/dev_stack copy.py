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
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / ".devdata"
SERVICES = {"identity": 8001, "access": 8002}  # add hierarchy, tasks, time here as they are built

sys.path.insert(0, str(ROOT / "tools"))
from local_db import start as start_db  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="delete .devdata/ (all local data) before starting")
    args = parser.parse_args()

    server, pg_port, signing_key = start_db(reset=args.reset)

    processes: list[subprocess.Popen[bytes]] = []
    try:
        for svc, port in SERVICES.items():
            env = {**os.environ}
            for line in (DATA / f"{svc}.env").read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k] = v

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
        print("DB cleanup")
        server.cleanup()


if __name__ == "__main__":
    main()
