"""HTTP routes of the access service (contract: contracts/openapi/access.yaml).

Every route is thin: build the context -> open ONE transaction -> call ONE use case -> build the response.

  POST   /v1/workspaces                          create a workspace; caller becomes Owner      S1-08
  GET    /v1/me/workspaces                       workspaces of the signed-in user              S1-08
  GET    /v1/w/{ws}/workspace                    read (members only)                           S1-08
  PATCH  /v1/w/{ws}/workspace                    rename (manage_workspace_settings, 409)       S1-08
  GET    /v1/w/{ws}/members                      member list, keyset paging                    S1-08
  POST   /v1/w/{ws}/invites                      invite by link, 207 per item (manage_users)   S1-09
  GET    /v1/w/{ws}/invites                      open invites (manage_users)                   S1-09
  DELETE /v1/w/{ws}/invites/{id}                 revoke (manage_users)                         S1-09
  POST   /v1/invites/accept                      join with a link token                        S1-09
  POST   /internal/v1/w/{ws}/authz/check         checkPermissions, for the other services      S1-10

Three kinds of transaction scope are used (see common.web):
  transaction(request, ctx)                      routes under /v1/w/{ws}: workspace from the URL
  global_transaction(workspace_id=...)           the workspace comes from the body (create) or the token (accept)
  global_transaction(user_id=...)                "my workspaces": the caller's own rows across workspaces

Not built yet: member role changes and deactivation, roles, groups, grants (sprints 12 to 14).
"""

from __future__ import annotations

import base64
import binascii
import secrets
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response

from access_service.api.schemas import (
    AcceptInviteIn,
    ChecksIn,
    InviteOut,
    InviteResultOut,
    InviteResultsOut,
    InvitesIn,
    MemberOut,
    MemberPageOut,
    MyWorkspaceOut,
    WorkspaceIn,
    WorkspaceOut,
    WorkspacePatch,
)
from access_service.domain.models import Actor, Workspace
from access_service.domain.rules import decode_invite_token
from access_service.repo.invite_repo import SqlInviteRepo
from access_service.repo.member_repo import SqlMemberRepo
from access_service.repo.workspace_repo import SqlWorkspaceRepo
from access_service.settings import Settings
from access_service.usecases.invites import accept_invite, create_invites, list_invites, revoke_invite
from access_service.usecases.members import list_members
from access_service.usecases.permissions import check_permissions
from access_service.usecases.ports import HierarchyClient
from access_service.usecases.workspaces import (
    create_workspace,
    finish_provisioning,
    get_workspace,
    list_my_workspaces,
    rename_workspace,
)
from common.auth import Claims
from common.context import RequestContext
from common.errors import Unprocessable
from common.ports import Clock
from common.web import get_claims, get_ctx, global_transaction, transaction

router = APIRouter()


@dataclass(slots=True)
class Deps:
    """The service's long-lived collaborators, built in main.py and kept on app.state.deps."""

    settings: Settings
    clock: Clock
    # None when HIERARCHY_URL is not configured (access running on its own). Set at startup otherwise.
    hierarchy: HierarchyClient | None = None


def _deps(request: Request) -> Deps:
    deps: Deps = request.app.state.deps
    return deps


def _actor(claims: Claims) -> Actor:
    return Actor(claims.user_id, claims.email, claims.name)


def _new_invite_secret() -> bytes:
    return secrets.token_bytes(32)  # 256 bits from the OS random source


async def _provision(request: Request, workspace: Workspace, user_id: UUID) -> Workspace:
    """Seed the first space (hierarchy) and flip the workspace to 'active'. Never fails the request:
    if hierarchy is down the workspace is returned as 'provisioning' and the next read tries again."""
    if workspace.status == "active":
        return workspace

    async def activate() -> None:
        async with global_transaction(request, workspace_id=workspace.id, user_id=user_id) as tx:
            await SqlWorkspaceRepo(tx.session).mark_active(workspace.id)

    await finish_provisioning(
        workspace, getattr(request.state, "bearer_token", None), hierarchy=_deps(request).hierarchy, activate=activate
    )
    async with global_transaction(request, workspace_id=workspace.id, user_id=user_id) as tx:
        return await SqlWorkspaceRepo(tx.session).get(workspace.id) or workspace


# ---------------------------------------------------------------------------------------------- workspaces
@router.post("/v1/workspaces", response_model=WorkspaceOut, status_code=202)
async def post_workspace(body: WorkspaceIn, request: Request, claims: Claims = Depends(get_claims)) -> WorkspaceOut:
    deps = _deps(request)
    # The new workspace's id scopes the transaction, so the rows we insert pass row-level security.
    async with global_transaction(request, workspace_id=body.id, user_id=claims.user_id) as tx:
        workspace = await create_workspace(
            body.to_cmd(),
            _actor(claims),
            workspaces=SqlWorkspaceRepo(tx.session),
            members=SqlMemberRepo(tx.session),
            events=tx.events,
            clock=deps.clock,
            cell_id=deps.settings.cell_id,
        )
    # Committed. Now the one call to another service, outside any transaction.
    return WorkspaceOut.from_domain(await _provision(request, workspace, claims.user_id))


@router.get("/v1/me/workspaces", response_model=list[MyWorkspaceOut])
async def read_my_workspaces(request: Request, claims: Claims = Depends(get_claims)) -> list[MyWorkspaceOut]:
    # No workspace in scope: only the caller's own membership rows are visible (policy member_self_read).
    async with global_transaction(request, user_id=claims.user_id) as tx:
        mine = await list_my_workspaces(claims.user_id, members=SqlMemberRepo(tx.session))
    return [MyWorkspaceOut.from_domain(w) for w in mine]


@router.get("/v1/w/{workspace_id}/workspace", response_model=WorkspaceOut)
async def read_workspace(request: Request, ctx: RequestContext = Depends(get_ctx)) -> WorkspaceOut:
    async with transaction(request, ctx) as tx:
        workspace = await get_workspace(
            ctx.user_id, ctx.workspace_id, workspaces=SqlWorkspaceRepo(tx.session), members=SqlMemberRepo(tx.session)
        )
    # Self-healing: a workspace whose first space could not be seeded earlier gets another try here.
    return WorkspaceOut.from_domain(await _provision(request, workspace, ctx.user_id))


@router.patch("/v1/w/{workspace_id}/workspace", response_model=WorkspaceOut)
async def patch_workspace(
    body: WorkspacePatch, request: Request, ctx: RequestContext = Depends(get_ctx)
) -> WorkspaceOut:
    async with transaction(request, ctx) as tx:
        workspace = await rename_workspace(
            ctx.user_id,
            ctx.workspace_id,
            body.name,
            body.version,
            workspaces=SqlWorkspaceRepo(tx.session),
            members=SqlMemberRepo(tx.session),
            events=tx.events,
            cell_id=_deps(request).settings.cell_id,
        )
    return WorkspaceOut.from_domain(workspace)


# ------------------------------------------------------------------------------------------------- members
def _decode_cursor(cursor: str | None) -> UUID | None:
    """Cursors are opaque to clients: base64url of the last member id of the previous page."""
    if cursor is None:
        return None
    try:
        return UUID(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("ascii"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise Unprocessable("Invalid cursor") from exc


def _encode_cursor(after: UUID | None) -> str | None:
    return base64.urlsafe_b64encode(str(after).encode("ascii")).rstrip(b"=").decode("ascii") if after else None


@router.get("/v1/w/{workspace_id}/members", response_model=MemberPageOut)
async def read_members(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None, max_length=200),
    status: str | None = Query(default=None, pattern="^(active|pending|deactivated)$"),
    ctx: RequestContext = Depends(get_ctx),
) -> MemberPageOut:
    async with transaction(request, ctx) as tx:
        page = await list_members(
            ctx.user_id, members=SqlMemberRepo(tx.session), limit=limit, after_id=_decode_cursor(cursor), status=status
        )
    return MemberPageOut(
        items=[MemberOut.from_domain(m) for m in page.items], next_cursor=_encode_cursor(page.next_after)
    )


# ------------------------------------------------------------------------------------------------- invites
@router.post("/v1/w/{workspace_id}/invites", response_model=InviteResultsOut, status_code=207)
async def post_invites(body: InvitesIn, request: Request, ctx: RequestContext = Depends(get_ctx)) -> InviteResultsOut:
    async with transaction(request, ctx) as tx:
        results = await create_invites(
            ctx.user_id,
            ctx.workspace_id,
            body.to_requests(),
            members=SqlMemberRepo(tx.session),
            invites=SqlInviteRepo(tx.session),
            clock=_deps(request).clock,
            new_secret=_new_invite_secret,
        )
    return InviteResultsOut(results=[InviteResultOut.from_domain(r) for r in results])


@router.get("/v1/w/{workspace_id}/invites", response_model=list[InviteOut])
async def read_invites(request: Request, ctx: RequestContext = Depends(get_ctx)) -> list[InviteOut]:
    async with transaction(request, ctx) as tx:
        invites = await list_invites(
            ctx.user_id,
            members=SqlMemberRepo(tx.session),
            invites=SqlInviteRepo(tx.session),
            clock=_deps(request).clock,
        )
    return [InviteOut.from_domain(i) for i in invites]


@router.delete("/v1/w/{workspace_id}/invites/{invite_id}", status_code=204)
async def delete_invite(invite_id: UUID, request: Request, ctx: RequestContext = Depends(get_ctx)) -> Response:
    async with transaction(request, ctx) as tx:
        await revoke_invite(
            ctx.user_id,
            invite_id,
            members=SqlMemberRepo(tx.session),
            invites=SqlInviteRepo(tx.session),
            clock=_deps(request).clock,
        )
    return Response(status_code=204)


@router.post("/v1/invites/accept", response_model=MemberOut)
async def post_accept_invite(body: AcceptInviteIn, request: Request, claims: Claims = Depends(get_claims)) -> MemberOut:
    deps = _deps(request)
    workspace_id = decode_invite_token(body.token)  # a malformed token is a dead link: 410
    async with global_transaction(request, workspace_id=workspace_id, user_id=claims.user_id) as tx:
        member = await accept_invite(
            body.token,
            _actor(claims),
            workspace_id,
            workspaces=SqlWorkspaceRepo(tx.session),
            members=SqlMemberRepo(tx.session),
            invites=SqlInviteRepo(tx.session),
            events=tx.events,
            clock=deps.clock,
            cell_id=deps.settings.cell_id,
        )
    return MemberOut.from_domain(member)


# --------------------------------------------------------------------------------------------- permissions
@router.post("/internal/v1/w/{workspace_id}/authz/check", response_model=list[bool])
async def post_authz_check(body: ChecksIn, request: Request, ctx: RequestContext = Depends(get_ctx)) -> list[bool]:
    """INTERNAL: called by the other services over the private network (Envoy does not route /internal).
    A valid user token is still required (defence in depth); service tokens arrive with the workers."""
    async with transaction(request, ctx) as tx:
        return await check_permissions(
            body.user_id, [c.to_check() for c in body.checks], members=SqlMemberRepo(tx.session)
        )
