# Working agreement

Short on purpose. The reasons are in `docs/adr/`.

## Git
- `main` is protected and always deployable. Work in short branches (`feat/time-create-entry`), squash-merge, delete the branch.
- Conventional Commits with the service as scope: `feat(time): manual entries`, `fix(access): expired invite returns 410`, `chore(ci): ...`. Cross-cutting: `libs`, `contracts`, `deploy`, `docs`.
- One PR = one sprint task where possible. Put the task id (e.g. `S1-19`) in the PR title.

## Before you push
`make check` must be green. Pre-commit runs ruff and gitleaks; CI runs everything again.

## Definition of done
- [ ] Code and tests pass (happy path, permission denial, validation failure, cross-workspace check)
- [ ] `contracts/openapi/*.yaml` updated first if the API changed
- [ ] Migration added if the schema changed (forward-only, expand then contract)
- [ ] New table has `workspace_id` and forced RLS
- [ ] No service imports another service; cross-service data goes through a client
- [ ] Other services are called only before your own write, never after
- [ ] No secrets, tokens or personal data in logs, fixtures or commits

## Hard rules
1. A service never imports another service, and never touches another service's database.
2. `libs/common` is plumbing only. If one service uses it, it stays in that service. Move to `common` at the third use.
3. `domain/` stays pure. `usecases/` never imports FastAPI or SQLAlchemy.
4. Repo functions never commit. The `api/` layer owns the transaction.
5. Fail closed. A timeout talking to access is a 503, never an "allow".
6. No secrets in Git. Real env files stay on the server.
7. Never `--no-verify` and never skip a failing check. Fix it or discuss it.

## ADRs
A decision someone may later ask you to defend gets a short file in `docs/adr/` (10 lines is fine).
