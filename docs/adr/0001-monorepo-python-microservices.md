# ADR 0001: One repository, independent Python services

**Status:** accepted (sprint 1) · **Decided by:** the backend developer

## Decision
- **One Git repository** (monorepo) holding every service, the shared library, the contracts and the deployment files.
- **Independent services inside it.** Each service has its own package, database, migrations, tests, Dockerfile and `/healthz`, and can be built and deployed alone.
- **Python 3.12**, FastAPI, async SQLAlchemy 2, Alembic, Pydantic v2, managed with **uv** (one workspace, one lockfile).

## Why
- One developer today, 1 or 2 helpers later: one place to branch, review, version and run CI.
- Contract changes and the code that uses them land in **one commit**.
- Splitting a service into its own repository later is easy; merging many repositories is not.

## What keeps "independent" true (enforced, not hoped for)
- A service never imports another service. `import-linter` fails CI on a violation (root `pyproject.toml`).
- A service never reads another service's database (ADR 0005).
- Services talk through generated clients from `contracts/openapi/` (ADR 0004).
- `libs/common` stays thin: plumbing only, no business logic, no domain models.

## Consequences
- CI is path-filtered, so a change in one service runs only that service's tests (plus the shared checks).
- A change to `libs/common` or `contracts/` runs everything. That is the intended cost of shared code.
