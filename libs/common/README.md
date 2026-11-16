# libs/common

Thin shared plumbing. Every service imports it. **It must stay small.**

## The rule
If only one service uses something, it lives in that service. Move code here only when the **third** service needs
the same thing. `common` holds *plumbing*, never *business rules* and never *domain models*.
`common` must never import a service (enforced by import-linter).

## What is here (task S1-03 unless noted)

| Module | Purpose | Pure? (usable from `domain/` and `usecases/`) |
|---|---|---|
| `errors.py` | `DomainError` and its subclasses (`NotFound`, `Forbidden`, `VersionConflict`, `Unprocessable`...), each with an HTTP status and a stable machine `code`. Use cases raise these. | yes |
| `problems.py` | Turns any `DomainError` into an RFC 9457 problem response; installs the handlers on a FastAPI app | no (FastAPI) |
| `context.py` | `RequestContext`: user id, workspace id, request id, role. Built once per request in the `api/` layer and passed down | yes |
| `ports.py` | Protocols (`EventSink`, `Clock`) that use cases depend on, so tests can pass fakes | yes |
| `clock.py` | `SystemClock`: the only place that calls `datetime.now()` | yes |
| `ids.py` | `new_id()` returns a UUIDv7 | yes |
| `config.py` | `ServiceSettings` (pydantic-settings). Every service extends it. Env vars only | no |
| `logging.py` | JSON log formatter; request id, workspace id and user id on every line | yes |
| `db.py` | The connection pool (one per process, sizing notes inside) and `scoped_transaction`, which sets `app.workspace_id` / `app.user_id` so forced RLS applies | no (SQLAlchemy) |
| `outbox.py` | `SqlOutbox.add(...)`: writes an event row in the same transaction as the change | no |
| `auth.py` | Token verification, EdDSA only: `RemoteJwksVerifier` (identity's JWKS, cached) and `KeySetVerifier` (keys from a loader: identity itself, tests) | no |
| `web.py` | `create_service_app` (request ids, access log, CORS, error handlers, health, pooled HTTP client), `get_claims` / `get_ctx`, `transaction` / `global_transaction`, `client_ip` | no (FastAPI) |
| `permissions.py` | `PermissionClient`: calls access `checkPermissions` with a 2 s timeout; fails closed | no |

## Tests
`tests/` here are unit tests. The database pieces (`db.py`, `outbox.py`, `web.py` transactions) are exercised by the
identity and access integration tests on a real PostgreSQL.
