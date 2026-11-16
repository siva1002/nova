# ADR 0005: One database per service

**Status:** accepted (sprint 1)

## Decision
One PostgreSQL **server** for the MVP, with **one database per service**: `identity`, `access`, `hierarchy`, `tasks`, `time`. Each database has two logins:
- `<svc>_migrator` owns the schema and is used by Alembic only.
- `<svc>_app` is what the running service uses. It can connect to its own database only, and belongs to `app_user`, so **forced row-level security** applies.

`deploy/postgres/init.sh` creates all of this when the local container first starts.

## Why
A shared database invites a cross-service join the first time it is convenient, and undoing that later means rewriting queries. Separate databases make the boundary physical on day one, and splitting them across servers (sprint 18: Aurora clusters pg-core, pg-work, pg-support) is then a change of connection string.

## Cross-workspace reads (the two places a request has no workspace in its URL)
Row-level security is never bypassed by the services. Instead:
- **"My workspaces"**: a SELECT-only policy `member_self_read` on `workspace_members` lets a user read their own membership rows; the service sets `app.user_id` per transaction.
- **Accepting an invite**: the workspace id is inside the invite token, so the transaction is scoped to that workspace before the invite is looked up.
- **Global tables** (identity's users, sessions, keys; access's `workspaces`) have no `workspace_id` and are always queried by key.

## Rules
- A service never opens a connection to another service's database (the logins make this impossible).
- Every table has `workspace_id` and forced RLS (policy in `tools/db-split/_epilogue.sql`). Each transaction starts with `set_config('app.workspace_id', ..., true)` (`common.db.scoped_transaction`).
- Schema source: `tools/db-split/` (generated from the design in `plan/db`). `python tools/make_baselines.py` builds each service's `0001_baseline.sql`. After the first real deploy, change the schema only with new forward migrations.
- `tests/integration/test_baselines.py` proves every service's migrations run on a real PostgreSQL and that no table with `workspace_id` lacks forced RLS; `services/access/tests/integration` attacks the isolation with raw SQL as the app login.
