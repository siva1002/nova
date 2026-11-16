# ADR 0002: MVP shortcuts (sprint 1)

**Status:** accepted · **Source of truth for details:** `plan/tech/15-sprint-plan.md`, sprint 1

The MVP is a thin slice through the **real** architecture. These shortcuts are deliberate, and each has a sprint that replaces it. Nothing is rewritten, only extended.

| Shortcut | Replaced in |
|---|---|
| One cell, no routing service (Envoy routes by path) | Sprints 8 and 9 |
| Synchronous calls between services instead of events. The outbox is written from day one | Sprint 3 |
| Time totals computed on request | Sprint 29 |
| Permission check = role check (Owner/Admin/Member) behind the final `checkPermissions` shape | Sprint 13 |
| No Temporal. Creating a workspace is one call | Sprint 10 |
| One PostgreSQL server (still one database per service) | Sprint 18 |
| Single EC2 server with Docker Compose, Caddy and nightly `pg_dump` | Sprints 17 and 18 |
| Polling every 15 s instead of WebSocket | Sprint 25 |
| In-process sign-in rate limit | Sprint 2 (Redis) |

## Never shortcut (even in the MVP)
Forced row-level security per workspace, version conflicts (409), the outbox, one database per service, and manual time entry.
