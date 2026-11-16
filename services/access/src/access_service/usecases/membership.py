"""Shared first step of every workspace-scoped use case in access: is the caller a member here?

Other services ask access over HTTP (PermissionClient). Access itself reads its own member table, in the
same transaction as the rest of the use case.
"""

from __future__ import annotations

from uuid import UUID

from access_service.domain.errors import WorkspaceNotFound
from access_service.domain.models import Member
from access_service.usecases.ports import MemberRepo


async def require_member(members: MemberRepo, user_id: UUID) -> Member:
    """Return the caller's ACTIVE membership of the current workspace.

    A non-member gets the same 404 as for a workspace that does not exist, so workspace ids cannot be
    probed. (Row-level security already hides the rows; this turns "no rows" into a clear answer.)
    """
    member = await members.get_by_user(user_id)
    if member is None or not member.is_active:
        raise WorkspaceNotFound()
    return member
