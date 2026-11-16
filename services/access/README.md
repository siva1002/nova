# Access service  (`services/access`)

Workspaces, members, invites, roles and the permission check every other service calls.

| | |
|---|---|
| Database | `access` (own login `access_app`, migrations as `access_migrator`) |
| Main tables | workspaces, workspace_members, roles, invites (+ permission tables later) |
| Public routes | /v1/workspaces, /v1/me/workspaces, /v1/invites/accept, /v1/w/{ws}/{workspace,members,invites,roles}, /internal/v1/w/{ws}/authz/check |
| Calls | hierarchy (seed the first space after createWorkspace). |
| Package | `access_service` (under `src/`) |

## Sprint 1 tasks that fill this service
- S1-08 createWorkspace + seeded roles + my workspaces
- S1-09 invites by link
- S1-10 checkPermissions (role check)

## Status: S1-08, S1-09, S1-10 built and tested
| Built | Notes |
|---|---|
| `POST /v1/workspaces` | Caller becomes Owner; role templates seeded; idempotent on the client-chosen id |
| `GET /v1/me/workspaces` | The caller's own memberships (policy `member_self_read`) |
| `GET` / `PATCH /v1/w/{ws}/workspace` | Members read; rename needs `manage_workspace_settings`; stale version is 409 |
| `GET /v1/w/{ws}/members` | Keyset paging with an opaque cursor |
| `POST` / `GET` / `DELETE /v1/w/{ws}/invites` | Invite by link (207 per item), list, revoke. Needs `manage_users` |
| `POST /v1/invites/accept` | Email must match; link works once, 7 days; the workspace id travels inside the token |
| `POST /internal/v1/w/{ws}/authz/check` | checkPermissions: the role check in `domain/roles.py`, final request and response shape |

Not built (sprints 12 to 14): member role changes and deactivation, roles, groups, grants, `me/permissions`.

Migration `0002` adds `workspaces.provision_status`, the member profile snapshot and the self-read policy.
A new workspace is `provisioning` until hierarchy's `seedWorkspace` answers (task S1-11); until that exists, leave
`HIERARCHY_URL` empty to activate at once, or set it and the workspace stays `provisioning` but fully usable.
Private spaces are decided by hierarchy (S1-12), not here.

## Where things go
```
src/access_service/
  main.py        create_app(): wires settings, logging, error handlers, routers. No logic.
  settings.py    this service's extra settings (extends common.config.ServiceSettings)
  api/           HTTP only: routes.py, schemas.py            (see api/__init__.py)
  usecases/      the service layer: create_workspace.py, create_invite.py, accept_invite.py, check_permissions.py
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
