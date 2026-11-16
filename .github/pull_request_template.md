## What and why
<!-- One or two lines. Link the sprint task id, e.g. S1-19. -->

## Self-review (tick what applies; delete what does not)
- [ ] Tests: happy path, permission denial, validation failure, cross-workspace check
- [ ] `contracts/openapi/*.yaml` updated first if the API changed
- [ ] Migration added if the schema changed (forward-only, expand then contract)
- [ ] New table has `workspace_id`, forced RLS, and is covered by the isolation test
- [ ] No service imports another service; cross-service data goes through a generated client
- [ ] Write path: other services are called only before the write, never after
- [ ] Outbox event written in the same transaction as the change
- [ ] No secrets, tokens or personal data in logs or fixtures
- [ ] `make check` is green locally
