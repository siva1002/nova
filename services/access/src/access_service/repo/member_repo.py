"""SQL for workspace members (implements usecases.ports.MemberRepo). Table: workspace_members.

Forced row-level security limits every query to the workspace of the current transaction, so the
queries below do not repeat `workspace_id = ...` in WHERE (inserts still carry it: the policy's WITH CHECK
verifies it). The ONE exception is `list_for_user`, which reads the caller's own rows across workspaces
through the `member_self_read` policy (migration 0002) and must run with app.user_id set.
Queries only: no rules, no commits.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from access_service.domain.models import Member, MyWorkspace

_COLUMNS = (
    "id, workspace_id, user_id, role_kind, status, email, display_name, invited_by, joined_at, "
    "version, created_at, updated_at"
)


def _to_member(row: Any) -> Member:
    return Member(
        id=row.id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        role_kind=row.role_kind,
        status=row.status,
        email=row.email or "",
        display_name=row.display_name or "",
        invited_by=row.invited_by,
        joined_at=row.joined_at,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlMemberRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def insert(self, member: Member) -> bool:
        # The unique index workspace_members_ws_user_uk allows one live membership per user per
        # workspace; ON CONFLICT turns a concurrent duplicate into "no row" instead of an error.
        result = await self._s.execute(
            text(
                "INSERT INTO workspace_members (id, workspace_id, user_id, role_kind, status, email, display_name, "
                "invited_by, invited_at, joined_at, created_at, updated_at) "
                "VALUES (:id, :workspace_id, :user_id, :role_kind, :status, :email, :display_name, "
                ":invited_by, :invited_at, "
                ":joined_at, :now, :now) "
                "ON CONFLICT (workspace_id, user_id) WHERE deleted_at IS NULL DO NOTHING RETURNING id"
            ),
            {
                "id": member.id,
                "workspace_id": member.workspace_id,
                "user_id": member.user_id,
                "role_kind": member.role_kind,
                "status": member.status,
                "email": member.email,
                "display_name": member.display_name,
                "invited_by": member.invited_by,
                "invited_at": member.created_at if member.invited_by else None,
                "joined_at": member.joined_at,
                "now": member.created_at,
            },
        )
        return result.first() is not None

    async def get_by_user(self, user_id: UUID) -> Member | None:
        # Scoped to the current workspace explicitly as well: with app.user_id set, the self-read policy
        # would otherwise also show this user's memberships of OTHER workspaces.
        result = await self._s.execute(
            text(
                f"SELECT {_COLUMNS} FROM workspace_members "
                "WHERE workspace_id = current_workspace() AND user_id = :user_id AND deleted_at IS NULL"
            ),
            {"user_id": user_id},
        )
        row = result.first()
        return _to_member(row) if row else None

    async def get_by_email(self, email: str) -> Member | None:
        result = await self._s.execute(
            text(
                f"SELECT {_COLUMNS} FROM workspace_members "
                "WHERE workspace_id = current_workspace() AND lower(email) = :email AND deleted_at IS NULL"
            ),
            {"email": email},
        )
        row = result.first()
        return _to_member(row) if row else None

    async def list_page(self, limit: int, after_id: UUID | None, status: str | None) -> list[Member]:
        # The WHERE clause is assembled from fixed fragments only; values always travel as parameters.
        where = ["workspace_id = current_workspace()", "deleted_at IS NULL"]
        params: dict[str, Any] = {"limit": limit}
        if after_id is not None:
            where.append("id > :after_id")
            params["after_id"] = after_id
        if status is not None:
            where.append("status = :status")
            params["status"] = status
        result = await self._s.execute(
            text(f"SELECT {_COLUMNS} FROM workspace_members WHERE {' AND '.join(where)} ORDER BY id LIMIT :limit"),
            params,
        )
        return [_to_member(row) for row in result]

    async def list_for_user(self, user_id: UUID) -> list[MyWorkspace]:
        result = await self._s.execute(
            text(
                "SELECT m.workspace_id, w.name, m.role_kind, m.status "
                "FROM workspace_members m JOIN workspaces w ON w.id = m.workspace_id "
                "WHERE m.user_id = :user_id AND m.deleted_at IS NULL AND w.deleted_at IS NULL "
                "AND m.status <> 'deactivated' "
                "ORDER BY lower(w.name), m.workspace_id"
            ),
            {"user_id": user_id},
        )
        return [MyWorkspace(row.workspace_id, row.name, row.role_kind, row.status) for row in result]
