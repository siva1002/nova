"""USE CASES: invite people by link, list and revoke invites, accept an invite (S1-09).

THE LINK
  create_invites returns, once, a token per invite. The web app shows it as a link
  (https://app.../invite#<token>) for the inviter to copy. Real email sending arrives in sprint 33.
  Only the SHA-256 of the token is stored, so a database leak does not leak working links.

RULES
  - inviting needs the `manage_users` capability (Owner, Admin)
  - roles that can be invited in the MVP: admin, member
  - a link is valid for 7 days, works once, and can be revoked
  - it can only be accepted by a user signed in with the invited email
  - one open invite per email per workspace; an existing member cannot be invited again
  - unknown, expired, revoked and used links all answer the same 410 (the link reveals nothing)
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from uuid import UUID

from access_service.domain.errors import InviteEmailMismatch, InviteGone, WorkspaceNotFound
from access_service.domain.models import Actor, Invite, InviteRequest, InviteResult, Member
from access_service.domain.roles import require_capability
from access_service.domain.rules import (
    INVITABLE_ROLES,
    INVITE_TTL_DAYS,
    encode_invite_token,
    hash_invite_token,
    normalize_email,
)
from access_service.events.builders import member_event
from access_service.usecases.membership import require_member
from access_service.usecases.ports import InviteRepo, MemberRepo, WorkspaceRepo
from common.errors import NotFound
from common.ids import new_id
from common.ports import Clock, EventSink


async def create_invites(
    user_id: UUID,
    workspace_id: UUID,
    requests: list[InviteRequest],
    *,
    members: MemberRepo,
    invites: InviteRepo,
    clock: Clock,
    new_secret: Callable[[], bytes],
) -> list[InviteResult]:
    """One result per requested invite, in order. A bad item never fails the others (207 Multi-Status)."""
    inviter = await require_member(members, user_id)
    require_capability(inviter, "manage_users")
    now = clock.now()
    results: list[InviteResult] = []
    seen: set[str] = set()

    for request in requests:
        email = normalize_email(request.email)
        if email is None:
            results.append(InviteResult(request.email, 422, code="invite.invalid_email", detail="Not an email address"))
            continue
        if request.role_kind not in INVITABLE_ROLES:
            results.append(
                InviteResult(email, 422, code="invite.role_not_invitable", detail="Invite as admin or member")
            )
            continue
        if email in seen:
            results.append(InviteResult(email, 409, code="invite.duplicate", detail="Listed twice in this request"))
            continue
        seen.add(email)
        if await members.get_by_email(email) is not None:
            results.append(InviteResult(email, 409, code="invite.already_member", detail="Already a member"))
            continue

        token = encode_invite_token(workspace_id, new_secret())
        invite = Invite(
            id=new_id(),
            workspace_id=workspace_id,
            email=email,
            role_kind=request.role_kind,
            invited_by=user_id,
            token_hash=hash_invite_token(token),
            expires_at=now + timedelta(days=INVITE_TTL_DAYS),
            accepted_at=None,
            accepted_user_id=None,
            revoked_at=None,
            version=1,
            created_at=now,
            updated_at=now,
        )
        if await invites.insert(invite):
            results.append(InviteResult(email, 201, invite=invite, token=token))
        else:  # the unique index says an open invite for this email already exists
            results.append(
                InviteResult(
                    email, 409, code="invite.already_pending", detail="Already invited; revoke it to re-invite"
                )
            )
    return results


async def list_invites(user_id: UUID, *, members: MemberRepo, invites: InviteRepo, clock: Clock) -> list[Invite]:
    require_capability(await require_member(members, user_id), "manage_users")
    return await invites.list_open(clock.now())


async def revoke_invite(
    user_id: UUID, invite_id: UUID, *, members: MemberRepo, invites: InviteRepo, clock: Clock
) -> None:
    """Idempotent: revoking an already revoked invite succeeds. An unknown id is 404."""
    require_capability(await require_member(members, user_id), "manage_users")
    if await invites.revoke(invite_id, clock.now()):
        return
    if await invites.get(invite_id) is None:
        raise NotFound("Invite not found")


async def accept_invite(
    token: str,
    actor: Actor,
    workspace_id: UUID,
    *,
    workspaces: WorkspaceRepo,
    members: MemberRepo,
    invites: InviteRepo,
    events: EventSink,
    clock: Clock,
    cell_id: str,
) -> Member:
    """`workspace_id` was read from the token by the route, which scoped the transaction to it."""
    now = clock.now()
    invite = await invites.get_by_token_hash(hash_invite_token(token))
    if invite is None or invite.workspace_id != workspace_id:
        raise InviteGone()

    state = invite.state(now)
    if state == "accepted" and invite.accepted_user_id == actor.user_id:
        # The same person clicked the link again: answer with their membership instead of an error.
        existing = await members.get_by_user(actor.user_id)
        if existing is not None:
            return existing
    if state != "open":
        raise InviteGone()
    if invite.email != (normalize_email(actor.email) or ""):
        raise InviteEmailMismatch()

    # Claim the invite first, atomically: of two simultaneous accepts only one continues.
    if not await invites.mark_accepted(invite.id, actor.user_id, now):
        raise InviteGone()

    existing = await members.get_by_user(actor.user_id)
    if existing is not None:
        return existing  # already a member (joined another way): the invite is just consumed

    workspace = await workspaces.get(workspace_id)
    if workspace is None:
        raise WorkspaceNotFound()
    member = Member(
        id=new_id(),
        workspace_id=workspace_id,
        user_id=actor.user_id,
        role_kind=invite.role_kind,
        status="active",
        email=invite.email,
        display_name=actor.display_name,
        invited_by=invite.invited_by,
        joined_at=now,
        version=1,
        created_at=now,
        updated_at=now,
    )
    if not await members.insert(member):  # lost a race with another accept by the same user
        joined = await members.get_by_user(actor.user_id)
        if joined is not None:
            return joined
        raise InviteGone()
    await workspaces.bump_epoch(workspace_id)  # a new member changes permission answers
    events.add(
        "access.member.added", "member", member.id, member.version, member_event(member, workspace.name, cell_id)
    )
    return member
