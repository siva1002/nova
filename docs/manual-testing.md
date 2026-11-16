# Manual testing: identity and access

How to run the two finished services on any machine and walk through them by hand.

## 1. Start

**Without Docker** (works where images cannot be pulled; needs only Python packages):
```
uv sync --all-packages
uv run python tools/dev_stack.py          # add --reset to wipe local data
```
identity is on `http://127.0.0.1:8001`, access on `http://127.0.0.1:8002`. Interactive API pages: `/docs` on each.

**With Docker Compose** (everything behind Envoy on `http://localhost:8080`):
```
make setup && make up && make migrate
```
With Compose use `http://localhost:8080` for both `$I` and `$A` below.

## 2. Walk-through (bash; steps 1 and 3 of the MVP demo script)
```bash
I=http://127.0.0.1:8001; A=http://127.0.0.1:8002; J='content-type: application/json'

# Person A signs up (always 202) and signs in
curl -i -X POST $I/v1/auth/sign-up -H "$J" -d '{"email":"asha@example.com","password":"correct horse battery","displayName":"Asha Rao"}'
TA=$(curl -s -c a.cookies -X POST $I/v1/auth/sign-in -H "$J" -d '{"email":"asha@example.com","password":"correct horse battery"}' | python -c "import sys,json;print(json.load(sys.stdin)['accessToken'])")
curl -s $I/v1/me -H "authorization: Bearer $TA"

# A creates the workspace "Pilot" (the client chooses the id)
WS=$(python -c "import uuid;print(uuid.uuid4())")
curl -s -X POST $A/v1/workspaces -H "authorization: Bearer $TA" -H "$J" -d "{\"id\":\"$WS\",\"name\":\"Pilot\",\"slug\":\"pilot\"}"
curl -s $A/v1/me/workspaces -H "authorization: Bearer $TA"

# A invites B by link: copy "inviteToken" from the answer
curl -s -X POST $A/v1/w/$WS/invites -H "authorization: Bearer $TA" -H "$J" -d '{"invites":[{"email":"ben@example.com","roleKind":"member"}]}'
INVITE=<paste inviteToken>

# Person B signs up, signs in, accepts
curl -s -X POST $I/v1/auth/sign-up -H "$J" -d '{"email":"ben@example.com","password":"correct horse battery","displayName":"Ben Okoro"}'
TB=$(curl -s -c b.cookies -X POST $I/v1/auth/sign-in -H "$J" -d '{"email":"ben@example.com","password":"correct horse battery"}' | python -c "import sys,json;print(json.load(sys.stdin)['accessToken'])")
curl -s -X POST $A/v1/invites/accept -H "authorization: Bearer $TB" -H "$J" -d "{\"token\":\"$INVITE\"}"
curl -s $A/v1/w/$WS/members -H "authorization: Bearer $TB"

# B is a Member: renaming is refused (403). A may (use the version from GET).
curl -s $A/v1/w/$WS/workspace -H "authorization: Bearer $TB"
curl -i -X PATCH $A/v1/w/$WS/workspace -H "authorization: Bearer $TB" -H "$J" -d '{"name":"Hijacked","version":3}'
curl -i -X PATCH $A/v1/w/$WS/workspace -H "authorization: Bearer $TA" -H "$J" -d '{"name":"Pilot 2","version":3}'
```

## 3. Things worth trying by hand
| Try | Expect |
|---|---|
| Sign up twice with one email | 202 both times; the first password keeps working |
| Wrong password 10 times | 401 nine times, then 429 `auth.account_locked` with `Retry-After`; the right password is refused for 15 minutes |
| `curl -b a.cookies -c a.cookies -X POST $I/v1/auth/refresh` | 200 and a new cookie each time |
| Save `a.cookies`, refresh once, then refresh with the saved copy | 401, and the newest cookie is dead too (reuse ends the session) |
| `POST $I/v1/auth/sign-out` with the bearer token, then refresh | 204, then 401 |
| A token with one character changed | 401 from both services |
| The same `PATCH` rename again with the old version | 409 `common.version_conflict` with `current_version` |
| Any `/v1/w/$WS/...` as a user who is not a member | 404 `workspace.not_found` |
| The invite link a second time as another user, or after `DELETE /v1/w/$WS/invites/{id}` | 410 `invite.gone` |
| `POST $A/internal/v1/w/$WS/authz/check` with `{"userId":"<B's id>","checks":[{"permission":"track_time"},{"permission":"manage_users"}]}` | `[true,false]` |

## 4. Looking inside the database
`tools/dev_stack.py` keeps its PostgreSQL in `.devdata/pg`. Tables to look at: identity `users`, `user_credentials` (Argon2 hashes), `user_sessions`, `refresh_tokens` (hashes only), `signing_keys`, `outbox`; access `workspaces`, `workspace_members`, `invites` (token hashes only), `roles`, `outbox`.

## 5. Automated tests
```
uv run pytest -m "not integration"     # unit + contract tests, about 5 seconds, nothing needed
uv run pytest -m integration           # real PostgreSQL (bundled pgserver, or set PG_TEST_URL), about 90 seconds
```
