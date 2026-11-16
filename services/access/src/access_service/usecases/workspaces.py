"""USE CASES: create, read and rename a workspace; list my workspaces (S1-08).

CREATING A WORKSPACE (one local transaction, opened by the route)
  1. the workspace row                         status 'provisioning'
  2. its role templates                        SQL function seed_default_roles()
  3. the creator as Owner
  4. the permission epoch row
  5. two outbox events                         access.workspace.created, access.member.added
Then, AFTER the commit, `finish_provisioning` asks hierarchy for the first space and flips the status to
'active'. That call is the one allowed "write to another service" (docs/adr/0004): it is idempotent, and
if it fails the workspace simply stays 'provisioning' and the next GET tries again. Nothing is ever
half-written, and no background worker is needed.

IDEMPOTENT: the client chooses the workspace id. Sending the same request twice (double click, retry
after a timeout) returns the workspace created the first time instead of an error.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from uuid import UUID

from access_service.domain.errors import WorkspaceIdTaken, WorkspaceNotFound, WorkspaceSlugTaken
from access_service.domain.models import Actor, Member, MyWorkspace, NewWorkspace, Workspace
from access_service.domain.roles import require_capability
from access_service.domain.rules import clean_slug, clean_workspace_name
from access_service.events.builders import member_event, workspace_event
from access_service.usecases.membership import require_member
from access_service.usecases.ports import HierarchyClient, MemberRepo, WorkspaceRepo
from common.errors import DependencyUnavailable, VersionConflict
from common.ids import new_id
from common.ports import Clock, EventSink

log = logging.getLogger(__name__)


async def create_workspace(
    cmd: NewWorkspace,
    actor: Actor,
    *,
    workspaces: WorkspaceRepo,
    members: MemberRepo,
    events: EventSink,
    clock: Clock,
    cell_id: str,
) -> Workspace:
    name = clean_workspace_name(cmd.name)  # pure validation first
    slug = clean_slug(cmd.slug)
    now = clock.now()
    workspace = Workspace(
        id=cmd.id,
        name=name,
        slug=slug,
        status="provisioning",
        created_by=actor.user_id,
        version=1,
        created_at=now,
        updated_at=now,
    )
    if not await workspaces.insert(workspace):
        # Nothing was written. Find out why: our own retry, someone else's id, or a taken slug.
        existing = await workspaces.get(cmd.id)
        if existing is None:
            raise WorkspaceSlugTaken()
        if existing.created_by == actor.user_id:
            return existing  # the same request again: answer with the first result
        raise WorkspaceIdTaken()

    await workspaces.seed_default_roles(workspace.id)
    owner = Member(
        id=new_id(),
        workspace_id=workspace.id,
        user_id=actor.user_id,
        role_kind="owner",
        status="active",
        email=actor.email,
        display_name=actor.display_name,
        invited_by=None,
        joined_at=now,
        version=1,
        created_at=now,
        updated_at=now,
    )
    await members.insert(owner)
    await workspaces.bump_epoch(workspace.id)
    events.add(
        "access.workspace.created", "workspace", workspace.id, workspace.version, workspace_event(workspace, cell_id)
    )
    events.add("access.member.added", "member", owner.id, owner.version, member_event(owner, name, cell_id))
    return workspace


async def finish_provisioning(
    workspace: Workspace,
    bearer_token: str | None,
    *,
    hierarchy: HierarchyClient | None,
    activate: Callable[[], Awaitable[None]],
) -> bool:
    """Seed the first space in hierarchy, then mark the workspace active. Runs OUTSIDE any transaction.

    `activate` is supplied by the route: it opens a short transaction and calls WorkspaceRepo.mark_active.
    Returns True when the workspace is active afterwards. Safe to call again and again.
    """
    if workspace.status == "active":
        return True
    if hierarchy is not None and workspace.created_by is not None:
        try:
            await hierarchy.seed_workspace(workspace.id, workspace.created_by, bearer_token)
        except DependencyUnavailable:
            # Not an error for the caller: the workspace exists and works; the first space comes later.
            log.warning("hierarchy unavailable: workspace %s stays provisioning", workspace.id)
            return False
    # hierarchy is None = no HIERARCHY_URL configured (running access on its own): nothing to seed.
    await activate()
    return True


async def get_workspace(
    user_id: UUID, workspace_id: UUID, *, workspaces: WorkspaceRepo, members: MemberRepo
) -> Workspace:
    await require_member(members, user_id)
    workspace = await workspaces.get(workspace_id)
    if workspace is None:
        raise WorkspaceNotFound()
    return workspace


async def rename_workspace(
    user_id: UUID,
    workspace_id: UUID,
    name: str,
    expected_version: int,
    *,
    workspaces: WorkspaceRepo,
    members: MemberRepo,
    events: EventSink,
    cell_id: str,
) -> Workspace:
    member = await require_member(members, user_id)
    require_capability(member, "manage_workspace_settings")  # Owner and Admin; a Member gets 403
    cleaned = clean_workspace_name(name)

    current = await workspaces.get(workspace_id)
    if current is None:
        raise WorkspaceNotFound()
    if current.version != expected_version:
        raise VersionConflict(current_version=current.version)
    renamed = await workspaces.rename(workspace_id, cleaned, expected_version)
    if renamed is None:  # someone saved between our read and our write
        raise VersionConflict()
    events.add("access.workspace.updated", "workspace", renamed.id, renamed.version, workspace_event(renamed, cell_id))
    return renamed


async def list_my_workspaces(user_id: UUID, *, members: MemberRepo) -> list[MyWorkspace]:
    return await members.list_for_user(user_id)
