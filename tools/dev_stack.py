"""Run identity and access on this machine WITHOUT Docker services, for development and manual testing.

Requires the Docker postgres container to be running:
    cd deploy/compose && docker compose up postgres -d

    uv run python tools/dev_stack.py            start (Ctrl+C stops everything)
    uv run python tools/dev_stack.py --reset    wipe and recreate databases first

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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reset", action="store_true", help="drop and recreate databases before starting")
    args = parser.parse_args()


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


if __name__ == "__main__":
    main()
