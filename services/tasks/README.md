# Tasks service  (`services/tasks`)

Tasks: create, edit with version checks, move, order, and query.

| | |
|---|---|
| Database | `tasks` (own login `tasks_app`, migrations as `tasks_migrator`) |
| Main tables | tasks, task_assignees, task_number_blocks (+ local copies of lists/statuses/members in sprint 3) |
| Public routes | /v1/w/{ws}/tasks, /v1/w/{ws}/tasks/{id}, /tasks/{id}/move, /tasks/{id}/position, /tasks/query |
| Calls | hierarchy (list and status validation), access (members, permissions). Sprint 3 replaces both with local copies. |
| Package | `tasks_service` (under `src/`) |

## Sprint 1 tasks that fill this service
- S1-14 createTask + number blocks
- S1-15 get/update(409)/delete
- S1-16 validate via hierarchy and access
- S1-17 move + position
- S1-18 queryTasks (filters, cursor, updated_since)

## Where things go
```
src/tasks_service/
  main.py        create_app(): wires settings, logging, error handlers, routers. No logic.
  settings.py    this service's extra settings (extends common.config.ServiceSettings)
  api/           HTTP only: routes.py, schemas.py            (see api/__init__.py)
  usecases/      the service layer: create_task.py, update_task.py, move_task.py, query_tasks.py
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
