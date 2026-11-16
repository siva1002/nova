# Contracts

| Folder | What | Checked by |
|---|---|---|
| `openapi/` | OpenAPI 3.1 for identity, access, hierarchy, tasks (80 operations) + `common.yaml` | `validate.py` (openapi-spec-validator, cross-file refs, unique operation ids) |
| `events/` | Envelope + 5 topic schemas (tasks.task, tasks.field_value, hierarchy.container, access.member, time.entry) | `validate.py` (JSON Schema 2020-12, plus sample events that must pass and must fail) |

Run: `python validate.py` (needs `openapi-spec-validator jsonschema pyyaml`). Result on 10 Nov 2026: all OK.

**Rule:** each remaining service's full OpenAPI file and event schemas are written in the **first week of its build step**, before code (definition of done in `plan/tech/11-delivery-plan.md`). The endpoint inventory below fixes their scope now, so nothing is left undecided.

## Gateway route table (cell gateway, by path prefix after `/v1/w/{ws}/`)
| Prefix | Service |
|---|---|
| `workspace`, `members`, `invites`, `capabilities`, `roles`, `groups`, `nodes/*/access`, `nodes/*/grants`, `tasks/*/shares`, `me/permissions`, `people-fields` | access |
| `tree`, `spaces`, `folders`, `lists`, `nodes`, `statuses`, `status-templates`, `task-types` | hierarchy |
| `tasks`, `fields`, `templates` (except the routes below) | tasks |
| `tasks/*/history`, `audit`, `activity` | audit |
| `tasks/*/comments`, `comments` | collab |
| `files` | files |
| `views`, `exports`, `favorites`, `recents` | views |
| `time`, `timesheets`, `capacity`, `calendars` | time |
| `sprints`, `sprint-settings` | sprints |
| `automations` | automation |
| `inbox`, `notification-settings` | notifications |
| `imports` | import |
| `search` | search |
| `realtime` | realtime |

Global (no workspace): `/v1/auth/*`, `/v1/me*`, `/v1/privacy/*`, `/.well-known/jwks.json` → identity; `/v1/workspaces` (create), `/v1/invites/accept`, `/v1/resolve/{slug}` → routing.

## Endpoint inventory, remaining phase 1 services
Permission in brackets. All follow `plan/tech/06-api-conventions.md`.

**collab**
- `GET /tasks/{id}/comments` (view), `POST /tasks/{id}/comments` (comment), `PATCH /comments/{id}` (own comment, or edit), `DELETE /comments/{id}` (own or delete)
- `POST /comments/{id}/replies` (comment), `PUT /comments/{id}/reactions/{emoji}`, `DELETE` same (comment)
- `POST /comments/{id}/resolve` (comment); `PUT /comments/{id}/assignee` (comment)
- `POST /comments/read` (mark read up to a time per task)
- `POST /tasks/{id}/attachments` (edit; body: fileId), `DELETE /attachments/{id}` (edit)

**files**
- `POST /files/uploads`: returns a signed upload URL (max 100 MB phase 1) and a file id
- `POST /files/{id}/complete`: starts the scan
- `GET /files/{id}`: metadata and status (pending, clean, infected)
- `GET /files/{id}/download`: signed URL for 5 min, checked against the parent object's view permission

**views**
- `GET /nodes/{id}/views`, `POST /views` (manage_views; personal views need view only), `PATCH /views/{id}`, `DELETE /views/{id}`
- `POST /views/{id}/run`: runs the saved query through `tasks/query` as the viewer (R12)
- `PUT /views/{id}/shares`
- `POST /exports` (export_data; body: view id or query, format xlsx or csv), `GET /exports/{id}`: status and download URL
- `GET/PUT/DELETE /favorites`, `GET /recents`

**time**
- `POST /time/timer/start` (track_time; body: taskId), `POST /time/timer/stop`, `GET /time/timer` (my running timer)
- `GET /time/entries?user&from&to&task`, `POST /time/entries` (track_time; overlap warning per flow 4.1), `PATCH /time/entries/{id}`, `DELETE /time/entries/{id}`: locked entries need manage_timesheets
- `GET /timesheets/{user}/{periodStart}`, `POST /timesheets/{user}/{periodStart}/submit`
- `POST /timesheets/{user}/{periodStart}/approve|reject|reopen` (manage_timesheets or approve on the person's work)
- `GET /timesheets/approvals?status`: the approval queue
- `GET/PUT /capacity/{user}`, `GET/PUT /calendars/work-schedule`, `GET/POST/DELETE /calendars/holidays` (manage_workspace_settings)

**sprints**
- `GET/PUT /sprint-settings/{folderId}` (manage_fields on the folder)
- `POST /sprints` (create_container on the sprint folder), `PATCH /sprints/{id}`, `POST /sprints/{id}/start`
- `POST /sprints/{id}/close`: body says where unfinished tasks go (next sprint, backlog, stay). Runs as a workflow (flow 3.3)
- `GET /sprints/{id}/burndown`, `GET /sprints/{id}/capacity`

**automation**
- `GET /nodes/{id}/automations` (view), `POST /automations` (manage_automations), `PATCH /automations/{id}`, `DELETE /automations/{id}`
- `POST /automations/{id}/test` (dry run on one task, flow 7.1), `POST /automations/{id}/enable|disable`
- `GET /automations/{id}/runs?status` (view on the node), `GET /automation-catalog`: triggers, conditions and actions

**notifications**
- `GET /inbox?tab=primary|other|later|cleared&cursor`, `POST /inbox/read`, `POST /inbox/clear`, `POST /inbox/snooze`
- `GET/PUT /notification-settings`: per type and channel (in-app, email)

**import**
- `POST /imports` (manage_workspace_settings; body: fileId), `GET /imports/{id}`: status, detected format
- `PUT /imports/{id}/mapping`: columns, people, statuses, types, fields (flows 8.1 and 8.2)
- `POST /imports/{id}/dry-run`, `POST /imports/{id}/run`, `GET /imports/{id}/errors` (CSV download), `POST /imports/{id}/retry-failed`

**search**
- `POST /search`: body has q, types, nodeIds, filters and a cursor. The permission filter is always applied
- `GET/POST/DELETE /saved-searches`

**audit**
- `GET /audit?actor&action&from&to` (view_audit), `GET /activity?object` (view_activity), `GET /tasks/{id}/history` (view_activity on the task)
- `POST /audit/exports` (view_audit + export_data)

**routing (global)**
- `POST /v1/workspaces`, `GET /v1/resolve/{slug}`, `POST /v1/invites/accept`
- Internal operator API (admin network only, never public): `POST /ops/v1/cells`, `POST /ops/v1/workspaces/{id}/move`, `GET /ops/v1/moves/{id}`

**realtime**
- `POST /realtime/ticket`, then `wss .../v1/w/{ws}/realtime?ticket=` (`06-api-conventions.md` section 9)
