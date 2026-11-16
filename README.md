# work-platform

Backend for a multi-tenant work-management product. One repository, independent Python services.
Planning documents live in `../plan` (start with `plan/tech/tech-plan.md`, the sprint plan is `plan/tech/15-sprint-plan.md`).

## Where things go

```
platform/
├─ pyproject.toml          uv workspace + ruff, mypy, pytest and import-linter (independence rules) config. Owns no code
├─ uv.lock                 one lockfile: pinned versions for everything
├─ Makefile                make setup | up | down | reset | logs | lint | types | imports | test | check
├─ .github/                CI workflow (path-filtered) and the PR template
├─ .pre-commit-config.yaml ruff, gitleaks, hygiene hooks on every commit
│
├─ services/               ONE FOLDER PER SERVICE. Each is independent: own package, DB, migrations, tests, image
│   ├─ identity/           sign up/in/out, tokens, JWKS                     (S1-05..07)
│   ├─ access/             workspaces, members, invites, permission check  (S1-08..10)
│   ├─ hierarchy/          spaces, folders, lists, status sets             (S1-11..12)
│   ├─ tasks/              tasks, move, order, query                       (S1-14..18)
│   └─ time/               manual time entries, totals  <- WORKED EXAMPLE  (S1-19..20)
│        ├─ src/time_service/{api,usecases,domain,repo,clients,events}/   see each __init__.py
│        ├─ migrations/    Alembic; sql/0001_baseline.sql is generated
│        ├─ tests/{unit,integration}/
│        ├─ Dockerfile  alembic.ini  pyproject.toml  README.md
│
├─ libs/common/            thin shared plumbing: errors, config, db session, outbox, auth, permissions client, web wiring
├─ contracts/              API source of truth: openapi/*.yaml and events/*.schema.json, validated by validate.py
├─ tools/
│   ├─ db-split/           the database design as SQL, per service (generated from plan/db)
│   ├─ make_baselines.py   builds each service's 0001_baseline.sql from db-split
│   ├─ dev_stack.py        runs identity + access locally WITHOUT Docker (PostgreSQL from a pip package)
│   └─ gen_signing_key.py  prints a new SIGNING_PRIVATE_KEY for identity
├─ deploy/
│   ├─ compose/            docker-compose.yml (PostgreSQL, Envoy, Mailpit, 5 services) and .env.example
│   ├─ envoy/              path routing to the services (the MVP front door)
│   ├─ caddy/              HTTPS for the single EC2 server (task S1-13)
│   └─ postgres/init.sh    creates the 5 databases and their logins
├─ conftest.py             shared test fixtures: a real PostgreSQL per test (no Docker), token signing
├─ tests/                  integration/ (migrations + RLS, identity with access) and contract/ (events, routes vs OpenAPI)
└─ docs/adr/               decisions: 0001..0005. Read these before changing structure
```

## The pattern in one picture
```
request ─> api/ ──────────> usecases/ ─────> domain/        (pure rules)
           (thin: parse,     (service layer:  
            open ONE         permission, load,
            transaction)     rules, write,    repo/  ──> own database only (RLS forced)
                             outbox event)    clients/ ─> other services, via contracts (2 s, fail closed)
```
Import rules are checked by `lint-imports`: services never import each other; `domain` is pure; `usecases` know no FastAPI or SQLAlchemy.

## Build status
| Service | Sprint tasks | State |
|---|---|---|
| identity | S1-05 to S1-07 | **Built and tested** (see `services/identity/README.md`) |
| access | S1-08 to S1-10 | **Built and tested** (see `services/access/README.md`) |
| hierarchy | S1-11, S1-12 | Skeleton. Next. Must provide `POST /internal/v1/w/{ws}/seed` (contract: `seedWorkspace`) |
| tasks | S1-14 to S1-18 | Skeleton |
| time | S1-19, S1-20 | Worked example (create and edit an entry, unit-tested); the rest is listed in its `routes.py` |

Run identity and access without Docker: `uv run python tools/dev_stack.py`, then `docs/manual-testing.md`.

## Everyday commands
```
make setup      # uv sync --all-packages, local env file, git hooks
make up         # whole stack: http://localhost:8080 (Envoy), http://localhost:8025 (Mailpit)
make check      # lint + types + import rules + unit tests + contracts   (what CI runs)
make test-int   # integration tests on a real PostgreSQL (bundled, no Docker needed)
make migrate    # run every service's migrations (Compose)
```
No `make` on Windows? Run the underlying commands from the Makefile, e.g. `uv run pytest -m "not integration"`.

## Adding a service-level feature (checklist)
1. Edit `contracts/openapi/<service>.yaml` first.
2. Rule in `domain/`, the story in `usecases/`, SQL in `repo/`, the route in `api/`.
3. Unit test with fakes; integration test for anything SQL.
4. New table or column: a forward Alembic migration, with `workspace_id` and forced RLS.
5. `make check`.

See `CONTRIBUTING.md` for the working agreement.
