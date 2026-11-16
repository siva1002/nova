# Identity service  (`services/identity`)

Who you are: accounts, passwords, sessions, tokens and the public signing keys. Global (not per workspace).

| | |
|---|---|
| Database | `identity` (own login `identity_app`, migrations as `identity_migrator`) |
| Main tables | users, user_credentials, sessions, auth_tokens, signing_keys |
| Public routes | /v1/auth/{sign-up,sign-in,refresh,sign-out}, /v1/me, /.well-known/jwks.json |
| Calls | nobody. Other services verify tokens locally against its JWKS. |
| Package | `identity_service` (under `src/`) |

## Sprint 1 tasks that fill this service
- S1-05 signUp (Argon2id)
- S1-06 signing keys, JWKS, signIn
- S1-07 refresh rotation, signOut, getMe, rate limit

## Status: S1-05, S1-06, S1-07 built and tested
| Built | Notes |
|---|---|
| `POST /v1/auth/sign-up` | 202 always (no account probing, as the contract says). Argon2id in a worker thread |
| `POST /v1/auth/sign-in` | Access token (EdDSA, 15 min) in the body; refresh token only in an HttpOnly cookie on `/v1/auth` |
| `GET /.well-known/jwks.json` | Public keys from `signing_keys`; old keys stay published while retiring |
| `POST /v1/auth/refresh` | Single-use rotation; reuse of an old token ends the whole session |
| `POST /v1/auth/sign-out` (`?all=true`) | Ends the session(s); access tokens run out within 15 min |
| `GET /v1/me` | Profile |
| Brute force | Account lockout in PostgreSQL (10 failures, 15 min); per-IP limit in process (Redis in sprint 2) |

Not built (sprint 7): verify email, forgot/reset password, `PATCH /v1/me`, change password, session list.

Extra layer in this service: `adapters/` (Argon2 hasher, Ed25519 signer, rate limiter) behind ports from `usecases/ports.py`.
Migration `0002` adds `refresh_tokens`. Set `SIGNING_PRIVATE_KEY` (`python tools/gen_signing_key.py`) outside local runs.

## Where things go
```
src/identity_service/
  main.py        create_app(): wires settings, logging, error handlers, routers. No logic.
  settings.py    this service's extra settings (extends common.config.ServiceSettings)
  api/           HTTP only: routes.py, schemas.py            (see api/__init__.py)
  usecases/      the service layer: sign_up.py, sign_in.py, refresh_session.py, sign_out.py, get_me.py
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
