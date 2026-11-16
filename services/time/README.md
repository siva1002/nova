# Time service  (`services/time`)

Time tracking. MVP: manual entries, totals per task, 'my time'. Timer and timesheets come in sprints 36-37.

| | |
|---|---|
| Database | `time` (own login `time_app`, migrations as `time_migrator`) |
| Main tables | time_entries (hash-partitioned by workspace), later: timers, timesheets, approvals |
| Public routes | /v1/w/{ws}/time-entries, /v1/w/{ws}/time-entries/totals, /v1/w/{ws}/time/mine |
| Calls | tasks (getTask: does the task exist and can this user see it), access (permissions). Sprint 3 uses a local task copy. |
| Package | `time_service` (under `src/`) |

## Sprint 1 tasks that fill this service
- S1-19 service + manual entries
- S1-20 totals per task + 'my time' date range

## Where things go
```
src/time_service/
  main.py        create_app(): wires settings, logging, error handlers, routers. No logic.
  settings.py    this service's extra settings (extends common.config.ServiceSettings)
  api/           HTTP only: routes.py, schemas.py            (see api/__init__.py)
  usecases/      the service layer: create_entry.py (worked example included), update_entry.py, delete_entry.py, task_totals.py, my_time.py
  domain/        pure rules and types                        (see domain/__init__.py)
  repo/          SQL only                                    (see repo/__init__.py)
  clients/       clients for OTHER services                  (see clients/__init__.py)
  events/        outbox event builders                       (see events/__init__.py)
migrations/      Alembic. 0001 = baseline built from tools/db-split (run `python tools/make_baselines.py`)
tests/unit/      domain + usecases with fakes, no Docker
tests/integration/   real PostgreSQL (Testcontainers), RLS, endpoints
```

## Rules for this service
- Never import another service's package. Use `clients/` and `contracts/openapi/`.
- Change the contract first, then the code.
- A new table needs `workspace_id`, a migration, and forced RLS (the baseline epilogue does this for tables created in `tools/db-split`).
- Run `make check` before pushing.
