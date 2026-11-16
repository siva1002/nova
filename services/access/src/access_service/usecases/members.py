"""USE CASE: list the members of a workspace (S1-08). Any active member may see the member list."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from access_service.domain.models import Member
from access_service.usecases.membership import require_member
from access_service.usecases.ports import MemberRepo

PAGE_MAX = 200  # contracts/openapi/common.yaml, parameter Limit


@dataclass(frozen=True, slots=True)
class MemberPage:
    items: list[Member]
    next_after: UUID | None  # id to continue after, or None on the last page


async def list_members(
    user_id: UUID, *, members: MemberRepo, limit: int = 50, after_id: UUID | None = None, status: str | None = None
) -> MemberPage:
    """Keyset paging by member id (uuidv7, so this is also "oldest member first").

    Unlike OFFSET paging it stays fast on page 1000 and never skips or repeats rows when members are
    added while someone is paging. We fetch one row more than asked to learn whether another page exists.
    """
    await require_member(members, user_id)
    limit = max(1, min(limit, PAGE_MAX))
    rows = await members.list_page(limit + 1, after_id, status)
    has_more = len(rows) > limit
    items = rows[:limit]
    return MemberPage(items, items[-1].id if has_more and items else None)
