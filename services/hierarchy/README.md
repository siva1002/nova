# Hierarchy service  (`services/hierarchy`)

The container tree: spaces, folders, lists, and their status sets.

| | |
|---|---|
| Database | `hierarchy` (own login `hierarchy_app`, migrations as `hierarchy_migrator`) |
| Main tables | nodes (space/folder/list tree), statuses, status_sets, node_members |
| Public routes | /v1/w/{ws}/{tree,spaces,folders,lists,nodes,...}, /internal/v1/w/{ws}/seed |
| Calls | access (permission checks). |
| Package | `hierarchy_service` (under `src/`) |

## Sprint 1 tasks that fill this service
- S1-11 seed first space + default statuses
- S1-12 tree, spaces, folders, lists, rename, archive, private spaces

## Where things go
```
src/hierarchy_service/
  main.py        create_app(): wires settings, logging, error handlers, routers. No logic.
  settings.py    this service's extra settings (extends common.config.ServiceSettings)
  api/           HTTP only: routes.py, schemas.py            (see api/__init__.py)
  usecases/      the service layer: seed_workspace.py, get_tree.py, create_space.py, create_list.py, archive_node.py
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
