"""Access use cases with in-memory fakes: workspaces, invites, members, permission checks.
Each test is one rule from tasks S1-08 to S1-10, checked in milliseconds."""

from uuid import uuid4

import pytest
from access_fakes import ASHA, BEN, CARA, FakeHierarchy

from access_service.domain.errors import (
    InvalidWorkspace,
    InviteEmailMismatch,
    InviteGone,
    MissingCapability,
    WorkspaceIdTaken,
    WorkspaceNotFound,
    WorkspaceSlugTaken,
)
from access_service.domain.models import InviteRequest, PermissionCheck
from access_service.domain.rules import INVITE_TTL_DAYS, hash_invite_token
from access_service.usecases.invites import list_invites, revoke_invite
from access_service.usecases.members import list_members
from access_service.usecases.permissions import check_permissions
from access_service.usecases.workspaces import (
    finish_provisioning,
    get_workspace,
    list_my_workspaces,
    rename_workspace,
)
from common.errors import NotFound, VersionConflict
from common.ids import new_id


# ------------------------------------------------------------------------------------- create a workspace
async def test_creator_becomes_owner_roles_are_seeded_and_events_written(world):
    ws = await world.create_workspace(name="  Pilot  Team ", slug="Pilot")
    assert (ws.name, ws.slug, ws.status, ws.created_by) == ("Pilot Team", "pilot", "provisioning", ASHA.user_id)
    (owner,) = world.members.rows
    assert (owner.user_id, owner.role_kind, owner.status, owner.email) == (ASHA.user_id, "owner", "active", ASHA.email)
    assert world.workspaces.roles_seeded == [ws.id] and world.workspaces.epochs[ws.id] == 1
    assert world.events.types() == ["access.workspace.created", "access.member.added"]
    member_payload = world.events.added[1][2]["after"]
    assert member_payload["role_kind"] == "owner" and member_payload["workspace_name"] == "Pilot Team"


async def test_same_request_twice_returns_the_first_workspace(world):
    ws_id = new_id()
    first = await world.create_workspace(ws_id=ws_id)
    again = await world.create_workspace(ws_id=ws_id)  # double click / retry after a timeout
    assert again == first
    assert len(world.members.rows) == 1 and len(world.events.added) == 2  # nothing done twice


async def test_someone_elses_id_and_a_taken_slug_are_conflicts(world):
    ws = await world.create_workspace()
    with pytest.raises(WorkspaceIdTaken):
        await world.create_workspace(actor=BEN, ws_id=ws.id, slug="other")
    with pytest.raises(WorkspaceSlugTaken):
        await world.create_workspace(actor=BEN, slug="pilot")
    assert len(world.workspaces.rows) == 1


@pytest.mark.parametrize(("name", "slug"), [("", "pilot"), ("Pilot", "no"), ("Pilot", "Has Space")])
async def test_invalid_name_or_slug_writes_nothing(world, name, slug):
    with pytest.raises(InvalidWorkspace):
        await world.create_workspace(name=name, slug=slug)
    assert world.workspaces.rows == {} and world.events.added == []


# ------------------------------------------------------------------------------------------- provisioning
async def _provision(world, ws, hierarchy):
    async def activate() -> None:
        await world.workspaces.mark_active(ws.id)

    return await finish_provisioning(ws, "token", hierarchy=hierarchy, activate=activate)


async def test_provisioning_seeds_hierarchy_then_activates(world):
    ws = await world.create_workspace()
    hierarchy = FakeHierarchy()
    assert await _provision(world, ws, hierarchy) is True
    assert hierarchy.seeded == [ws.id] and world.workspaces.rows[ws.id].status == "active"


async def test_hierarchy_down_leaves_the_workspace_provisioning_and_a_retry_heals_it(world):
    ws = await world.create_workspace()
    hierarchy = FakeHierarchy(available=False)
    assert await _provision(world, ws, hierarchy) is False  # no exception: the request still succeeds
    assert world.workspaces.rows[ws.id].status == "provisioning"
    hierarchy.available = True
    assert await _provision(world, ws, hierarchy) is True  # the next read tries again
    assert world.workspaces.rows[ws.id].status == "active"


async def test_without_a_hierarchy_service_the_workspace_activates_directly(world):
    ws = await world.create_workspace()
    assert await _provision(world, ws, None) is True
    assert world.workspaces.rows[ws.id].status == "active"


# -------------------------------------------------------------------------------------- read and rename
async def test_only_members_can_read_a_workspace(world):
    ws = await world.create_workspace()
    assert (await get_workspace(ASHA.user_id, ws.id, workspaces=world.workspaces, members=world.members)).id == ws.id
    with pytest.raises(WorkspaceNotFound):  # an outsider gets 404, not 403: the workspace is not confirmed
        await get_workspace(CARA.user_id, ws.id, workspaces=world.workspaces, members=world.members)


async def _rename(world, ws, actor, name, version):
    world.scope.workspace_id = ws.id
    return await rename_workspace(
        actor.user_id,
        ws.id,
        name,
        version,
        workspaces=world.workspaces,
        members=world.members,
        events=world.events,
        cell_id="aps1-c01",
    )


async def test_owner_and_admin_can_rename_a_member_cannot(world):
    ws = await world.create_workspace()
    await world.join(ws, BEN, role="member")
    await world.join(ws, CARA, role="admin")

    renamed = await _rename(world, ws, ASHA, "Pilot 2", 1)
    assert (renamed.name, renamed.version) == ("Pilot 2", 2)
    assert world.events.types()[-1] == "access.workspace.updated"
    assert (await _rename(world, ws, CARA, "Pilot 3", 2)).version == 3  # admin
    with pytest.raises(MissingCapability) as err:  # the demo-script rule: a Member cannot rename
        await _rename(world, ws, BEN, "Hijacked", 3)
    assert err.value.status == 403 and world.workspaces.rows[ws.id].name == "Pilot 3"


async def test_rename_with_a_stale_version_is_a_conflict_carrying_the_current_version(world):
    ws = await world.create_workspace()
    await _rename(world, ws, ASHA, "First", 1)
    with pytest.raises(VersionConflict) as err:
        await _rename(world, ws, ASHA, "Second", 1)  # still sends version 1
    assert err.value.extra["current_version"] == 2 and world.workspaces.rows[ws.id].name == "First"


async def test_my_workspaces_lists_only_mine(world):
    pilot = await world.create_workspace(name="Pilot", slug="pilot")
    other = await world.create_workspace(actor=CARA, name="Other", slug="other")
    await world.join(pilot, BEN)
    mine = await list_my_workspaces(BEN.user_id, members=world.members)
    assert [(w.workspace_id, w.name, w.role_kind) for w in mine] == [(pilot.id, "Pilot", "member")]
    assert other.id not in {w.workspace_id for w in mine}


# ------------------------------------------------------------------------------------------------- invites
async def test_invite_returns_a_token_once_and_stores_only_its_hash(world):
    ws = await world.create_workspace()
    (result,) = await world.invite(ws, ASHA, InviteRequest(" Ben@Example.com ", "member"))
    assert result.status == 201 and result.token and result.invite is not None
    invite = result.invite
    assert invite.email == "ben@example.com" and invite.token_hash == hash_invite_token(result.token)
    assert result.token not in invite.token_hash
    assert (invite.expires_at - world.clock.now()).days == INVITE_TTL_DAYS


async def test_one_bad_item_does_not_fail_the_batch(world):
    ws = await world.create_workspace()
    await world.join(ws, BEN)
    results = await world.invite(
        ws,
        ASHA,
        InviteRequest("new@example.com", "member"),
        InviteRequest("not-an-email", "member"),
        InviteRequest("boss@example.com", "owner"),  # owners cannot be invited
        InviteRequest("guest@example.com", "guest"),  # not in the MVP
        InviteRequest(BEN.email, "member"),  # already a member
        InviteRequest("NEW@example.com", "admin"),  # same address twice in one request
    )
    assert [r.status for r in results] == [201, 422, 422, 422, 409, 409]
    assert [r.code for r in results[1:]] == [
        "invite.invalid_email",
        "invite.role_not_invitable",
        "invite.role_not_invitable",
        "invite.already_member",
        "invite.duplicate",
    ]
    assert len(world.invites.rows) == 2  # Ben's accepted invite + the one new invite


async def test_second_invite_to_the_same_email_is_refused_until_the_first_is_revoked_or_expires(world):
    ws = await world.create_workspace()
    (first,) = await world.invite(ws, ASHA, InviteRequest(BEN.email, "member"))
    (dup,) = await world.invite(ws, ASHA, InviteRequest(BEN.email, "admin"))
    assert (dup.status, dup.code) == (409, "invite.already_pending")

    await revoke_invite(ASHA.user_id, first.invite.id, members=world.members, invites=world.invites, clock=world.clock)
    (after_revoke,) = await world.invite(ws, ASHA, InviteRequest(BEN.email, "member"))
    assert after_revoke.status == 201

    world.clock.advance(days=INVITE_TTL_DAYS + 1)  # that one expires
    (after_expiry,) = await world.invite(ws, ASHA, InviteRequest(BEN.email, "member"))
    assert after_expiry.status == 201


async def test_only_those_who_manage_users_can_invite_list_and_revoke(world):
    ws = await world.create_workspace()
    await world.join(ws, BEN, role="member")
    with pytest.raises(MissingCapability):
        await world.invite(ws, BEN, InviteRequest("x@example.com", "member"))
    with pytest.raises(MissingCapability):
        await list_invites(BEN.user_id, members=world.members, invites=world.invites, clock=world.clock)
    with pytest.raises(WorkspaceNotFound):  # an outsider does not even learn the workspace exists
        await world.invite(ws, CARA, InviteRequest("x@example.com", "member"))


async def test_accept_makes_the_invited_user_a_member(world):
    ws = await world.create_workspace()
    member = await world.join(ws, BEN, role="admin")
    assert (member.user_id, member.role_kind, member.status) == (BEN.user_id, "admin", "active")
    assert (member.email, member.display_name, member.invited_by) == (BEN.email, BEN.display_name, ASHA.user_id)
    assert world.workspaces.epochs[ws.id] == 2  # a new member changes permission answers
    assert world.events.types()[-1] == "access.member.added"
    assert await list_invites(ASHA.user_id, members=world.members, invites=world.invites, clock=world.clock) == []


async def test_accepting_twice_is_harmless_for_the_same_person(world):
    ws = await world.create_workspace()
    (result,) = await world.invite(ws, ASHA, InviteRequest(BEN.email, "member"))
    first = await world.accept(result.token, BEN, ws)
    again = await world.accept(result.token, BEN, ws)  # clicked the link twice
    assert again.id == first.id and len(world.members.rows) == 2


async def test_wrong_email_expired_revoked_used_and_unknown_links(world):
    ws = await world.create_workspace()
    (result,) = await world.invite(ws, ASHA, InviteRequest(BEN.email, "member"))

    with pytest.raises(InviteEmailMismatch):  # the link was forwarded to someone else
        await world.accept(result.token, CARA, ws)
    with pytest.raises(InviteGone):
        await world.accept("A" * 64, BEN, ws)  # never issued

    await world.accept(result.token, BEN, ws)
    with pytest.raises(InviteGone):  # used by Ben; Cara cannot reuse it
        await world.accept(result.token, CARA, ws)

    (revoked,) = await world.invite(ws, ASHA, InviteRequest(CARA.email, "member"))
    await revoke_invite(
        ASHA.user_id, revoked.invite.id, members=world.members, invites=world.invites, clock=world.clock
    )
    with pytest.raises(InviteGone):
        await world.accept(revoked.token, CARA, ws)

    (stale,) = await world.invite(ws, ASHA, InviteRequest(CARA.email, "member"))
    world.clock.advance(days=INVITE_TTL_DAYS, seconds=1)
    with pytest.raises(InviteGone):
        await world.accept(stale.token, CARA, ws)
    assert {m.user_id for m in world.members.rows} == {ASHA.user_id, BEN.user_id}


async def test_a_token_for_one_workspace_does_not_work_in_another(world):
    pilot = await world.create_workspace(name="Pilot", slug="pilot")
    other = await world.create_workspace(actor=CARA, name="Other", slug="other")
    (result,) = await world.invite(pilot, ASHA, InviteRequest(BEN.email, "member"))
    with pytest.raises(InviteGone):
        await world.accept(result.token, BEN, other)


async def test_revoke_is_idempotent_and_unknown_is_404(world):
    ws = await world.create_workspace()
    (result,) = await world.invite(ws, ASHA, InviteRequest(BEN.email, "member"))
    for _ in range(2):
        await revoke_invite(
            ASHA.user_id, result.invite.id, members=world.members, invites=world.invites, clock=world.clock
        )
    with pytest.raises(NotFound):
        await revoke_invite(ASHA.user_id, uuid4(), members=world.members, invites=world.invites, clock=world.clock)


# ------------------------------------------------------------------------------------------------- members
async def test_member_list_pages_by_keyset_without_gaps_or_repeats(world):
    ws = await world.create_workspace()
    for i in range(6):
        actor = type(BEN)(new_id(), f"user{i}@example.com", f"User {i}")
        await world.join(ws, actor)
    world.scope.workspace_id = ws.id

    seen, after = [], None
    for _ in range(10):
        page = await list_members(ASHA.user_id, members=world.members, limit=3, after_id=after)
        seen += [m.id for m in page.items]
        after = page.next_after
        if after is None:
            break
    assert len(seen) == 7 == len(set(seen)) and seen == sorted(seen)

    with pytest.raises(WorkspaceNotFound):
        await list_members(CARA.user_id, members=world.members)


# --------------------------------------------------------------------------------------- checkPermissions
async def _check(world, ws, user_id, *permissions):
    world.scope.workspace_id = ws.id
    return await check_permissions(user_id, [PermissionCheck(p) for p in permissions], members=world.members)


async def test_check_permissions_answers_per_role_in_order(world):
    ws = await world.create_workspace()
    await world.join(ws, BEN, role="member")
    asked = ("track_time", "manage_users", "manage_workspace_settings", "edit", "manage_timesheets")
    assert await _check(world, ws, ASHA.user_id, *asked) == [True, True, True, True, True]
    assert await _check(world, ws, BEN.user_id, *asked) == [True, False, False, True, False]


async def test_check_permissions_fails_closed(world):
    ws = await world.create_workspace()
    await world.join(ws, BEN)
    assert await _check(world, ws, CARA.user_id, "view", "edit") == [False, False]  # not a member
    assert await _check(world, ws, BEN.user_id, "no_such_permission", "") == [False, False]  # unknown names
    world.members.set_status(BEN.user_id, "deactivated")
    assert await _check(world, ws, BEN.user_id, "view") == [False]  # deactivated
    assert await _check(world, ws, ASHA.user_id) == []  # no checks, no answers

    other = await world.create_workspace(actor=CARA, name="Other", slug="other")
    assert await _check(world, other, ASHA.user_id, "view") == [False]  # Owner elsewhere means nothing here
