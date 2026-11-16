"""USE CASE: checkPermissions (S1-10). The question every other service asks before it touches data:
"may this user do these things in this workspace?"

MVP: a role check (domain/roles.py). The request and response shape is already the final one
(contracts/openapi/access.yaml, operationId checkPermissions), so the full engine of sprint 13 replaces
only the inside of this function.

FAILS CLOSED: not a member, deactivated, unknown permission -> False. One membership lookup answers all
the checks of a call (up to 500), so a list view asking about 50 tasks costs one query.
"""

from __future__ import annotations

from uuid import UUID

from access_service.domain.models import PermissionCheck
from access_service.domain.roles import member_allows
from access_service.usecases.ports import MemberRepo

CHECKS_MAX = 500


async def check_permissions(user_id: UUID, checks: list[PermissionCheck], *, members: MemberRepo) -> list[bool]:
    """One answer per check, in the same order."""
    member = await members.get_by_user(user_id)
    return [member_allows(member, check.permission) for check in checks]
