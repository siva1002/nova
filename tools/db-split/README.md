# Database split by service

The single-database design in `plan/db/*.sql` split into **one database per service** (`plan/tech/02-data-and-cells.md`). The files here are **generated**: change `plan/db/*.sql` or `tools/`, then re-run.

## Files
| File | What |
|---|---|
| `_prelude.sql` | Loaded first into every service database: shared functions (version bump, partition helpers, `current_workspace()`, append-only guards) and the messaging tables `outbox`, `inbox`, `idempotency_keys` |
| `<service>.sql` | Phase 1 tables of that service |
| `<service>.later.sql` | Parked tables of that service (loads after its phase 1 file) |
| `_epilogue.sql` | Loaded last: version triggers, forced row-level security on every table with `workspace_id`, app roles and grants. Hand-written |
| `_dropped.sql` | Not loaded. What left the design, with the reason |
| `_moved-to-code.sql` | Not loaded. SQL functions whose logic moved into a service (the old permission functions → access permission engine) |
| `SPLIT-REPORT.md` | Every table → service, phase and note; every foreign key turned into a plain id |
| `tools/split.py` | The splitter, including the table → service map |
| `tools/extra/*.sql` | New tables the split needs: cells and routing, user_workspaces, auth tokens, signing keys, the container tree copy, local copies in tasks, time and sprints, task number blocks |
| `tools/check.mjs` | Loads every service into its **own empty** PGlite (PostgreSQL) database |
| `tools/isolation.mjs` | Tenant isolation test on the tasks database |

## Load order for one service
`_prelude.sql` → `<service>.sql` → `<service>.later.sql` (if any) → `_epilogue.sql`

## Result (10 Nov 2026)
- 180 tables: phase 1 114, later 50, dropped 16. **260 foreign keys** that crossed services became plain ids.
- `check.mjs`: all **22** service databases load alone. That covers 15 for phase 1 (with realtime having no database) and 7 later-only services. It proves that no service needs another service's tables.
- `isolation.mjs`: 6 of 6 pass:
  - a workspace sees only its own rows
  - with no workspace set, it sees nothing
  - it cannot insert or update another workspace's rows
  - row security is forced on all 37 tasks tables with `workspace_id`
- The original single-database files still load (`plan/db`, 290 tables with partitions).

## Run
```
python tools/split.py                                  # from plan/db/services/tools
node tools/check.mjs <path to plan/db/services>        # from a folder with @electric-sql/pglite installed
node tools/isolation.mjs <path to plan/db/services>
```
At build time each service's Alembic baseline migration is made from its file here.
