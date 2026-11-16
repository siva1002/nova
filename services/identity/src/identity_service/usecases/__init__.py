"""The SERVICE LAYER. One function (or small module) per action a user can take: create_entry, move_task...

A use case tells the story of one action: check permission -> load -> apply domain rules -> write via repo
-> add the outbox event. It receives everything it needs as PARAMETERS (ctx, repo, clients, clock, events),
so unit tests pass in-memory fakes. It never opens a transaction or commits: the api/ layer does that.
May import: domain, common (pure modules only). NEVER fastapi or sqlalchemy (import-linter enforces this).
Rule: call other services only to READ or CHECK before your own write; never write to another service after it."""
