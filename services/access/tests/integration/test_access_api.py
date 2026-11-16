"""Access end to end on a real PostgreSQL: HTTP in, SQL out, row-level security on. Tasks S1-08 to S1-10.

Run:  uv run pytest -m integration services/access
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest
from access_support import SwitchableHierarchy, person
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from access_service.domain.roles import ALL_CAPABILITIES
from common.context import RequestContext
from common.errors import DependencyUnavailable, Forbidden
from common.ids import new_id
from common.permissions import PermissionClient

pytestmark = pytest.mark.integration


def rows(db, sql: str, **params):
    with db.admin_engine().connect() as conn:  # superuser: sees everything, for assertions only
        return conn.execute(text(sql), params).all()


# ------------------------------------------------------------------------------------- create a workspace
async def test_create_workspace_makes_the_caller_owner_and_seeds_roles(access):
    asha = person("Asha")
    r = await access.create_workspace(asha, name="  Pilot  Team ", slug="Pilot-Team")
    assert r.status_code == 202
    ws = r.json()
    assert (ws["name"], ws["slug"], ws["status"]) == ("Pilot Team", "pilot-team", "active")
    # `version` counts every stored change (role seeding and activation each touch the row), so a new
    # workspace does not start at 1. Clients must always send back the version they last READ.
    assert ws["version"] == rows(access.db, "SELECT version FROM workspaces")[0].version

    (member,) = rows(
        access.db, "SELECT user_id, role_kind, status, email, display_name, joined_at FROM workspace_members"
    )
    assert (member.user_id, member.role_kind, member.status) == (asha.user_id, "owner", "active")
    assert (member.email, member.display_name) == (asha.email, asha.name) and member.joined_at is not None

    roles = {r.key for r in rows(access.db, "SELECT key FROM roles WHERE workspace_id = :ws", ws=ws["id"])}
    assert {"boss_admin", "admin", "associate", "guest"} <= roles  # the SQL function seed_default_roles ran
    assert rows(access.db, "SELECT epoch FROM access_epochs")[0].epoch == 1

    events = rows(access.db, "SELECT event_type, workspace_id, actor_user_id, payload FROM outbox ORDER BY id")
    assert [e.event_type for e in events] == ["access.workspace.created", "access.member.added"]
    assert all(str(e.workspace_id) == ws["id"] and e.actor_user_id == asha.user_id for e in events)
    assert events[1].payload["after"]["role_kind"] == "owner"

    mine = await access.client.get("/v1/me/workspaces", headers=access.auth(asha))
    assert mine.json() == [{"workspaceId": ws["id"], "name": "Pilot Team", "roleKind": "owner", "status": "active"}]


async def test_create_is_idempotent_and_reports_conflicts(access):
    asha, ben = person("Asha"), person("Ben")
    ws_id = new_id()
    first = await access.create_workspace(asha, slug="pilot", ws_id=ws_id)
    again = await access.create_workspace(asha, slug="pilot", ws_id=ws_id)  # retry of the same request
    assert again.status_code == 202 and again.json()["id"] == first.json()["id"]
    assert len(rows(access.db, "SELECT 1 FROM workspaces")) == 1
    assert len(rows(access.db, "SELECT 1 FROM workspace_members")) == 1
    assert len(rows(access.db, "SELECT 1 FROM outbox")) == 2

    stolen_id = await access.create_workspace(ben, slug="other", ws_id=ws_id)
    assert stolen_id.status_code == 409 and stolen_id.json()["code"] == "workspace.id_taken"
    taken_slug = await access.create_workspace(ben, slug="PILOT")
    assert taken_slug.status_code == 409 and taken_slug.json()["code"] == "workspace.slug_taken"
    bad = await access.create_workspace(ben, slug="has space")
    assert bad.status_code == 422 and bad.json()["code"] == "workspace.invalid"
    assert (await access.client.post("/v1/workspaces", json={})).status_code == 401  # no token


async def test_simultaneous_creates_of_one_workspace_produce_exactly_one(access):
    asha, ws_id = person("Asha"), new_id()
    results = await asyncio.gather(*(access.create_workspace(asha, slug="race", ws_id=ws_id) for _ in range(5)))
    assert {r.status_code for r in results} == {202}
    assert len(rows(access.db, "SELECT 1 FROM workspaces")) == 1
    assert len(rows(access.db, "SELECT 1 FROM workspace_members")) == 1
    assert len(rows(access.db, "SELECT 1 FROM roles WHERE key = 'admin'")) == 1  # roles seeded once


async def test_workspace_stays_provisioning_while_hierarchy_is_down_and_heals_on_read(access):
    asha = person("Asha")
    hierarchy = SwitchableHierarchy(available=False)
    access.app.state.deps.hierarchy = hierarchy

    created = await access.create_workspace(asha)
    assert created.status_code == 202 and created.json()["status"] == "provisioning"  # the request still succeeds
    ws_id = created.json()["id"]

    still = await access.client.get(f"/v1/w/{ws_id}/workspace", headers=access.auth(asha))
    assert still.json()["status"] == "provisioning"

    hierarchy.available = True  # hierarchy is back: the next read finishes the job
    healed = await access.client.get(f"/v1/w/{ws_id}/workspace", headers=access.auth(asha))
    assert healed.json()["status"] == "active" and [str(w) for w in hierarchy.seeded] == [ws_id]
    await access.client.get(f"/v1/w/{ws_id}/workspace", headers=access.auth(asha))
    assert len(hierarchy.seeded) == 1  # an active workspace is not seeded again


# -------------------------------------------------------------------------- invite, join, roles in action
async def test_invite_by_link_join_and_what_each_role_may_do(access):
    """Steps 1 and 3 of the MVP demo script, plus the 'Member cannot rename' rule."""
    asha, ben = person("Asha"), person("Ben")
    ws = (await access.create_workspace(asha)).json()
    base = f"/v1/w/{ws['id']}"

    invited = await access.invite(ws["id"], asha, "  Ben@Example.com ")
    assert invited.status_code == 207
    (result,) = invited.json()["results"]
    assert result["status"] == 201 and result["email"] == "ben@example.com" and result["inviteToken"]
    stored = rows(access.db, "SELECT token_hash, email, role_kind FROM invites")[0]
    assert result["inviteToken"] not in stored.token_hash and len(stored.token_hash) == 64  # hash only

    pending = await access.client.get(f"{base}/invites", headers=access.auth(asha))
    assert [i["email"] for i in pending.json()] == ["ben@example.com"]

    joined = await access.accept(result["inviteToken"], ben)
    assert joined.status_code == 200
    assert (joined.json()["userId"], joined.json()["roleKind"], joined.json()["status"]) == (
        str(ben.user_id),
        "member",
        "active",
    )
    assert (await access.client.get(f"{base}/invites", headers=access.auth(asha))).json() == []
    assert rows(access.db, "SELECT epoch FROM access_epochs")[0].epoch == 2

    members = await access.client.get(f"{base}/members", headers=access.auth(ben))  # a Member may see the list
    assert [(m["displayName"], m["roleKind"]) for m in members.json()["items"]] == [
        (asha.name, "owner"),
        (ben.name, "member"),
    ]
    mine = await access.client.get("/v1/me/workspaces", headers=access.auth(ben))
    assert [(w["workspaceId"], w["roleKind"]) for w in mine.json()] == [(ws["id"], "member")]

    # A Member cannot rename the workspace, invite people, or see invites.
    version = (await access.client.get(f"{base}/workspace", headers=access.auth(ben))).json()["version"]
    denied = await access.client.patch(
        f"{base}/workspace", json={"name": "Hijacked", "version": version}, headers=access.auth(ben)
    )
    assert denied.status_code == 403 and denied.json()["code"] == "access.missing_capability"
    assert (await access.invite(ws["id"], ben, "x@example.com")).status_code == 403
    assert (await access.client.get(f"{base}/invites", headers=access.auth(ben))).status_code == 403

    # The Owner can; a stale version is a 409 that tells the client the current version.
    renamed = await access.client.patch(
        f"{base}/workspace", json={"name": "Pilot 2", "version": version}, headers=access.auth(asha)
    )
    assert (
        renamed.status_code == 200 and renamed.json()["name"] == "Pilot 2" and renamed.json()["version"] == version + 1
    )
    stale = await access.client.patch(
        f"{base}/workspace", json={"name": "Pilot 3", "version": version}, headers=access.auth(asha)
    )
    assert stale.status_code == 409 and stale.json()["code"] == "common.version_conflict"
    assert stale.json()["current_version"] == version + 1
    assert rows(access.db, "SELECT name FROM workspaces")[0].name == "Pilot 2"


async def test_batch_invite_reports_each_item_separately(access):
    asha, ben = person("Asha"), person("Ben")
    ws = (await access.create_workspace(asha)).json()
    await access.join(ws["id"], asha, ben)
    body = {
        "invites": [
            {"email": "new@example.com", "roleKind": "admin"},
            {"email": "not-an-email", "roleKind": "member"},
            {"email": "boss@example.com", "roleKind": "owner"},
            {"email": ben.email, "roleKind": "member"},
            {"email": "NEW@example.com", "roleKind": "member"},
        ]
    }
    r = await access.client.post(f"/v1/w/{ws['id']}/invites", json=body, headers=access.auth(asha))
    assert r.status_code == 207
    results = r.json()["results"]
    assert [x["status"] for x in results] == [201, 422, 422, 409, 409]
    assert [x["problem"]["code"] for x in results[1:]] == [
        "invite.invalid_email",
        "invite.role_not_invitable",
        "invite.already_member",
        "invite.duplicate",
    ]
    assert results[0]["inviteToken"] and all(x["inviteToken"] is None for x in results[1:])

    again = await access.invite(ws["id"], asha, "new@example.com")  # an open invite already exists
    assert again.json()["results"][0]["problem"]["code"] == "invite.already_pending"
    too_many = {"invites": [{"email": f"u{i}@example.com", "roleKind": "member"} for i in range(101)]}
    assert (
        await access.client.post(f"/v1/w/{ws['id']}/invites", json=too_many, headers=access.auth(asha))
    ).status_code == 422


async def test_dead_links_wrong_person_and_revocation(access):
    asha, ben, cara = person("Asha"), person("Ben"), person("Cara")
    ws = (await access.create_workspace(asha)).json()
    token = (await access.invite(ws["id"], asha, ben.email)).json()["results"][0]["inviteToken"]

    wrong_person = await access.accept(token, cara)  # the link was forwarded
    assert wrong_person.status_code == 403 and wrong_person.json()["code"] == "invite.email_mismatch"
    for dead in ("garbage", "A" * 64, token[:-4] + "AAAA"):
        r = await access.accept(dead, ben)
        assert r.status_code == 410 and r.json()["code"] == "invite.gone"
    assert (await access.client.post("/v1/invites/accept", json={"token": token})).status_code == 401

    assert (await access.accept(token, ben)).status_code == 200
    assert (await access.accept(token, ben)).status_code == 200  # the same person again: harmless
    assert (await access.accept(token, cara)).status_code == 410  # used: dead for everyone else
    assert len(rows(access.db, "SELECT 1 FROM workspace_members")) == 2

    # Revoke, then expire.
    invited = (await access.invite(ws["id"], asha, cara.email)).json()["results"][0]
    revoke_url = f"/v1/w/{ws['id']}/invites/{invited['id']}"
    assert (await access.client.delete(revoke_url, headers=access.auth(ben))).status_code == 403  # Member
    assert (await access.client.delete(revoke_url, headers=access.auth(asha))).status_code == 204
    assert (await access.client.delete(revoke_url, headers=access.auth(asha))).status_code == 204  # idempotent
    assert (
        await access.client.delete(f"/v1/w/{ws['id']}/invites/{uuid4()}", headers=access.auth(asha))
    ).status_code == 404
    assert (await access.accept(invited["inviteToken"], cara)).status_code == 410

    fresh = (await access.invite(ws["id"], asha, cara.email)).json()["results"][0]
    with access.db.admin_engine().begin() as conn:
        conn.execute(
            text("UPDATE invites SET expires_at = now() - interval '1 minute' WHERE id = :id"), {"id": fresh["id"]}
        )
    assert (await access.accept(fresh["inviteToken"], cara)).status_code == 410
    reinvited = await access.invite(ws["id"], asha, cara.email)  # an expired invite does not block a new one
    assert reinvited.json()["results"][0]["status"] == 201


async def test_simultaneous_accepts_create_exactly_one_membership(access):
    asha, ben = person("Asha"), person("Ben")
    ws = (await access.create_workspace(asha)).json()
    token = (await access.invite(ws["id"], asha, ben.email)).json()["results"][0]["inviteToken"]
    results = await asyncio.gather(*(access.accept(token, ben) for _ in range(5)))
    assert {r.status_code for r in results} <= {200, 410} and any(r.status_code == 200 for r in results)
    assert len(rows(access.db, "SELECT 1 FROM workspace_members WHERE user_id = :u", u=ben.user_id)) == 1
    added = rows(access.db, "SELECT 1 FROM outbox WHERE event_type = 'access.member.added'")
    assert len(added) == 2  # the owner + Ben, once


async def test_member_list_pages_with_an_opaque_cursor(access):
    asha = person("Asha")
    ws = (await access.create_workspace(asha)).json()
    for i in range(5):
        await access.join(ws["id"], asha, person(f"User{i}"))

    seen, cursor = [], None
    for _ in range(10):
        params = {"limit": 2, **({"cursor": cursor} if cursor else {})}
        page = (await access.client.get(f"/v1/w/{ws['id']}/members", params=params, headers=access.auth(asha))).json()
        assert len(page["items"]) <= 2
        seen += [m["userId"] for m in page["items"]]
        cursor = page["nextCursor"]
        if cursor is None:
            break
    assert len(seen) == 6 == len(set(seen))  # every member exactly once
    bad = await access.client.get(f"/v1/w/{ws['id']}/members", params={"cursor": "!!"}, headers=access.auth(asha))
    assert bad.status_code == 422
    assert (
        await access.client.get(f"/v1/w/{ws['id']}/members", params={"limit": 500}, headers=access.auth(asha))
    ).status_code == 422


# ----------------------------------------------------------------------------------------- tenant isolation
async def test_another_company_cannot_see_or_touch_this_workspace(access):
    asha, ben, mallory = person("Asha"), person("Ben"), person("Mallory")
    pilot = (await access.create_workspace(asha, name="Pilot")).json()
    await access.join(pilot["id"], asha, ben)
    await access.invite(pilot["id"], asha, "pending@example.com")
    rival = (await access.create_workspace(mallory, name="Rival")).json()  # Mallory owns a DIFFERENT workspace

    base = f"/v1/w/{pilot['id']}"
    m = access.auth(mallory)
    for response in (
        await access.client.get(f"{base}/workspace", headers=m),
        await access.client.get(f"{base}/members", headers=m),
        await access.client.get(f"{base}/invites", headers=m),
        await access.client.patch(f"{base}/workspace", json={"name": "Owned", "version": 2}, headers=m),
        await access.invite(pilot["id"], mallory, "spy@example.com"),
    ):
        # 404, not 403: an outsider cannot even confirm that the workspace exists
        assert response.status_code == 404 and response.json()["code"] == "workspace.not_found", response.text

    mine = (await access.client.get("/v1/me/workspaces", headers=m)).json()
    assert [w["workspaceId"] for w in mine] == [rival["id"]]
    assert rows(access.db, "SELECT name FROM workspaces WHERE id = :id", id=pilot["id"])[0].name == "Pilot"
    assert len(rows(access.db, "SELECT 1 FROM invites")) == 2  # Ben's (accepted) + pending; nothing from Mallory


async def test_row_level_security_holds_at_the_database_even_without_the_application(access):
    """The last line of defence: connect as the service's own database login and try to cheat with SQL."""
    asha, mallory = person("Asha"), person("Mallory")
    pilot = (await access.create_workspace(asha, name="Pilot")).json()
    rival = (await access.create_workspace(mallory, name="Rival")).json()
    await access.invite(pilot["id"], asha, "pending@example.com")
    scoped_tables = ("workspace_members", "invites", "roles", "role_capabilities", "access_epochs")

    engine = access.db.app_sync_engine()  # the APP login, not a superuser
    with engine.connect() as conn:
        for table in scoped_tables:  # 1. no workspace set -> nothing is visible
            assert conn.execute(text(f"SELECT count(*) FROM {table}")).scalar() == 0, table
        conn.rollback()

        # 2. scoped to Pilot -> only Pilot's rows, in every table
        conn.execute(text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": pilot["id"]})
        for table in scoped_tables:
            seen = {str(r[0]) for r in conn.execute(text(f"SELECT workspace_id FROM {table}"))}
            assert seen == {pilot["id"]}, table

        # 3. ... and Rival's rows cannot be changed or deleted from here (0 rows affected)
        assert (
            conn.execute(
                text("UPDATE workspace_members SET role_kind = 'owner' WHERE workspace_id = :ws"), {"ws": rival["id"]}
            ).rowcount
            == 0
        )
        assert conn.execute(text("DELETE FROM roles WHERE workspace_id = :ws"), {"ws": rival["id"]}).rowcount == 0
        conn.rollback()

    with engine.connect() as conn:  # 4. inserting a row INTO another workspace is refused by the policy
        conn.execute(text("SELECT set_config('app.workspace_id', :ws, true)"), {"ws": pilot["id"]})
        with pytest.raises(DBAPIError, match="row-level security"):
            conn.execute(
                text(
                    "INSERT INTO workspace_members (id, workspace_id, user_id, role_kind) "
                    "VALUES (gen_random_uuid(), :ws, gen_random_uuid(), 'owner')"
                ),
                {"ws": rival["id"]},
            )

    with engine.connect() as conn:  # 5. "my own rows" policy: read-only, and only MY memberships
        conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(mallory.user_id)})
        visible = conn.execute(text("SELECT workspace_id, user_id FROM workspace_members")).all()
        assert [(str(r.workspace_id), r.user_id) for r in visible] == [(rival["id"], mallory.user_id)]
        # it grants SELECT only: Mallory cannot promote herself or leave through it
        assert conn.execute(text("UPDATE workspace_members SET role_kind = 'admin'")).rowcount == 0
        assert conn.execute(text("SELECT count(*) FROM invites")).scalar() == 0  # no such policy on other tables
        conn.rollback()

    assert rows(access.db, "SELECT count(*) AS n FROM workspace_members")[0].n == 2  # nothing changed


# --------------------------------------------------------------------------------------- checkPermissions
async def test_check_permissions_endpoint_and_the_shared_permission_client(access):
    asha, ben, cara = person("Asha"), person("Ben"), person("Cara")
    ws = (await access.create_workspace(asha)).json()
    await access.join(ws["id"], asha, ben)
    url = f"/internal/v1/w/{ws['id']}/authz/check"
    asked = ["track_time", "manage_users", "edit", "manage_timesheets", "no_such_permission"]

    async def check(user, caller=asha):
        body = {"userId": str(user.user_id), "checks": [{"permission": p} for p in asked]}
        return await access.client.post(url, json=body, headers=access.auth(caller))

    assert (await check(asha)).json() == [True, True, True, True, False]
    assert (await check(ben)).json() == [True, False, True, False, False]
    assert (await check(cara)).json() == [False] * 5  # not a member: everything is denied
    assert (await access.client.post(url, json={"userId": str(ben.user_id), "checks": []})).status_code == 401
    too_many = {"userId": str(ben.user_id), "checks": [{"permission": "view"}] * 501}
    assert (await access.client.post(url, json=too_many, headers=access.auth(asha))).status_code == 422

    # The client every OTHER service uses (libs/common) speaks this endpoint's contract.
    perms = PermissionClient("http://access", access.client)
    token = access.tokens.issue(ben.user_id, ben.email, ben.name)
    ctx = RequestContext(ben.user_id, ws["id"], "req-test", bearer_token=token)
    assert await perms.check(ctx, "track_time", task_id=uuid4()) is True
    assert await perms.check(ctx, "manage_users") is False
    await perms.require(ctx, "edit")
    with pytest.raises(Forbidden):
        await perms.require(ctx, "manage_timesheets")

    # FAIL CLOSED: if access cannot be reached, the answer is an error, never "allowed".
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("access is down")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unreachable)) as dead:
        with pytest.raises(DependencyUnavailable):
            await PermissionClient("http://access", dead).check(ctx, "track_time")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))) as broken:
        with pytest.raises(DependencyUnavailable):
            await PermissionClient("http://access", broken).check(ctx, "track_time")


async def test_role_table_in_code_matches_the_capabilities_in_the_database(access):
    in_database = {r.key for r in rows(access.db, "SELECT key FROM capabilities")}
    assert in_database == set(ALL_CAPABILITIES)  # a capability added in SQL must be added in domain/roles.py
