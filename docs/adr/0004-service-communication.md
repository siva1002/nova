# ADR 0004: How services talk to each other

**Status:** accepted (sprint 1)

## Decision
Services communicate through **APIs and events, never through each other's databases.**

| Need | Mechanism |
|---|---|
| Check something right now before writing (permission, existence) | Sync API call (sprint 3 onward: a local copy kept from events) |
| Show data owned by another service (names, totals) | Batch API call, merged in code. Never a loop of single calls |
| Something happened that others may care about | Outbox event (written from day one; Debezium and Kafka from sprint 3) |
| Long multi-step job | Temporal (later) |

## Rules for every call
- Use the **generated client** from `contracts/openapi/` in the service's `clients/` folder. Never hand-write HTTP to a peer; never import its package.
- **2 s timeout. Fail closed:** on timeout or error raise `DependencyUnavailable` (503). Never "allow" on failure.
- Forward `Authorization` and `X-Request-Id`.
- **Retry reads only.** Writes are retried only with an `Idempotency-Key`.
- `/internal/*` endpoints are reachable on the private network only; Envoy does not route them.
- Store the **id**, not the data. No foreign keys across databases; integrity comes from these rules and, later, events.

## The write rule
A use case calls other services **only to read or check before its own write, never to write after it.** The write to its own database and its outbox event are one local transaction, so a failure leaves nothing half-done.
One exception: access calls hierarchy's `seedWorkspace`, which is idempotent, so a retry is safe.

## MVP call map
| Caller | Callee | For |
|---|---|---|
| every service | access | `checkPermissions` |
| tasks | hierarchy | list and status validation |
| tasks | access | assignees are members |
| time | tasks | `getTask` (exists and visible) |
| access | hierarchy | seed the first space |
| (everyone) | identity | none: tokens are verified locally against the cached JWKS |

## Consequences
Sync calls couple availability (hierarchy down means task creation fails). Accepted for the pilot; sprint 3 removes it with local copies, behind the same client interfaces, so use cases do not change.
