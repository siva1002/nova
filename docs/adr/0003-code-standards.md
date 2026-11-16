# ADR 0003: Code pattern and standards

**Status:** accepted (sprint 1)

## The pattern: service layer + repository, inside every service
```
src/<name>_service/
  api/        HTTP only: routes, schemas. Opens ONE transaction, calls ONE use case.
  usecases/   the SERVICE LAYER: one function per user action. Owns the story of the action.
  domain/     pure rules and types. No web, no database, no clock reads.
  repo/       SQL only. Never commits, never checks permissions.
  clients/    clients for OTHER services (generated from contracts)
  events/     outbox event builders (later: consumers)
```
- Dependencies point inward: `api -> usecases -> domain`; `repo` returns domain types.
- Use cases receive collaborators as **parameters** (repo, clients, clock, events). No globals, no `datetime.now()` inside logic. That is what makes unit tests possible with fakes.
- **One transaction per request**, opened in `api/` via `common.web.transaction`. The change and its outbox event commit together or not at all.
- Domain errors (`NotFound`, `Forbidden`, `VersionConflict`...) are **raised** by use cases and turned into RFC 9457 responses in **one** place (`common.problems`).
- Enforced by `import-linter`: domain is pure, usecases know no FastAPI and no SQLAlchemy, repo never reaches up.
- Worked example: `services/time/` (`create_entry`, `update_entry`).

## Additions made while building identity and access
- **`adapters/` (optional layer):** implementations of use-case ports that are neither SQL nor another service, e.g. identity's Argon2 hasher, Ed25519 signer and rate limiter. No FastAPI, no SQLAlchemy.
- **Result, not exception, when a refusal must still write.** A failed sign-in counts the failure; a reused refresh token revokes the session. Raising would roll that back, so those use cases return `Denied(error)` and the route raises it **after** the commit.
- **Concurrency goes to the database, in one statement:** `INSERT ... ON CONFLICT DO NOTHING`, `UPDATE ... WHERE <still valid> RETURNING`. Never "select, then decide, then write".
- **Blocking or CPU-heavy work leaves the event loop:** `asyncio.to_thread` plus a semaphore (password hashing), so one slow call never stalls the others.
- **Long-lived resources are created once per process:** the database pool, one pooled HTTP client for peer calls, the key cache (`common/web.py`).
- **Idempotency by client-chosen ids** where a retry is likely (`createWorkspace`).

## Tooling
Python 3.12 + **uv** workspace. **Ruff** (lint and format), **mypy strict**, **pytest** (+ pytest-asyncio), **pgserver** (PostgreSQL 16 as a pip package; CI uses a service container via `PG_TEST_URL`) for real-database tests without Docker, **pre-commit** (ruff, gitleaks). GitHub Actions, path-filtered. Trunk-based Git: short branches, squash merge, Conventional Commits with the service as scope (`feat(time): ...`).

## Conventions (expensive to change later)
| Area | Rule |
|---|---|
| IDs | UUIDv7 everywhere (`common.ids.new_id`). Task numbers are separate and human-facing |
| Time | UTC in database and API (`timestamptz`, ISO 8601) |
| JSON | **camelCase** on the wire (matches `contracts/openapi`); snake_case in Python and the database |
| Errors | RFC 9457 problem responses, stable `type` URLs |
| Events | `<service>.<aggregate>.<verb>` e.g. `time.entry.created`; payloads match `contracts/events` |
| Pagination | Cursor only |
| Concurrency | `version` column; `409` on a stale write |
| Tenancy | `workspace_id` on every table, forced RLS, set per transaction |
| Migrations | Forward-only; expand then contract |
| Config | Environment variables only, validated at startup |
| Logging | JSON lines with `request_id`, `workspace_id`, `user_id`. Never tokens or passwords |
| Contracts | Contract first: edit the YAML, then the code |

## Tests
| Layer | Tests | Mocks |
|---|---|---|
| Unit (`tests/unit`) | `domain` and `usecases` | in-memory fakes, no DB, no HTTP |
| Integration (`tests/integration`) | `repo`, migrations, RLS, endpoints | real PostgreSQL; other services stubbed |
| Journey | the 8-step demo script through Envoy | nothing |

Per endpoint: a happy path, a permission denial, a validation failure, and a cross-workspace check.

## Definition of done
Code and tests pass, contract updated if the API changed, migration added if the schema changed, isolation test passes, `make check` green.

## Not doing
Per-service repositories or versioning, a shared "models" package, full DDD/CQRS ceremony, premature abstraction (duplicate until the third use, then move to `libs/common`).
