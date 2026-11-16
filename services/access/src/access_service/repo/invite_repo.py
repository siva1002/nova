"""SQL for invites (implements usecases.ports.InviteRepo). Table: invites.

Forced row-level security scopes every query to the workspace of the current transaction (for accepting
an invite the route reads that workspace from the token). Queries only: no rules, no commits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from access_service.domain.models import Invite

_COLUMNS = (
    "id, workspace_id, email, role_kind, invited_by, token_hash, expires_at, accepted_at, accepted_user_id, "
    "revoked_at, version, created_at, updated_at"
)


def _to_invite(row: Any) -> Invite:
    return Invite(
        id=row.id,
        workspace_id=row.workspace_id,
        email=row.email,
        role_kind=row.role_kind,
        invited_by=row.invited_by,
        token_hash=row.token_hash,
        expires_at=row.expires_at,
        accepted_at=row.accepted_at,
        accepted_user_id=row.accepted_user_id,
        revoked_at=row.revoked_at,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlInviteRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def insert(self, invite: Invite) -> bool:
        # The unique index invites_open_uk allows ONE open invite per email per workspace, and it counts
        # an expired invite as still open. Retire expired ones first so a person can be invited again.
        await self._s.execute(
            text(
                "UPDATE invites SET revoked_at = :now "
                "WHERE workspace_id = :workspace_id AND lower(email) = :email "
                "AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at <= :now"
            ),
            {"workspace_id": invite.workspace_id, "email": invite.email, "now": invite.created_at},
        )
        result = await self._s.execute(
            text(
                "INSERT INTO invites (id, workspace_id, email, role_kind, invited_by, token_hash, expires_at, "
                "created_at, updated_at) "
                "VALUES (:id, :workspace_id, :email, :role_kind, :invited_by, :token_hash, :expires_at, :now, :now) "
                "ON CONFLICT (workspace_id, lower(email)) WHERE accepted_at IS NULL AND revoked_at IS NULL "
                "DO NOTHING RETURNING id"
            ),
            {
                "id": invite.id,
                "workspace_id": invite.workspace_id,
                "email": invite.email,
                "role_kind": invite.role_kind,
                "invited_by": invite.invited_by,
                "token_hash": invite.token_hash,
                "expires_at": invite.expires_at,
                "now": invite.created_at,
            },
        )
        return result.first() is not None

    async def get(self, invite_id: UUID) -> Invite | None:
        result = await self._s.execute(
            text(f"SELECT {_COLUMNS} FROM invites WHERE id = :id"),
            {"id": invite_id},
        )
        row = result.first()
        return _to_invite(row) if row else None

    async def get_by_token_hash(self, token_hash: str) -> Invite | None:
        result = await self._s.execute(
            text(f"SELECT {_COLUMNS} FROM invites WHERE token_hash = :token_hash"),
            {"token_hash": token_hash},
        )
        row = result.first()
        return _to_invite(row) if row else None

    async def list_open(self, now: datetime) -> list[Invite]:
        result = await self._s.execute(
            text(
                f"SELECT {_COLUMNS} FROM invites "
                "WHERE accepted_at IS NULL AND revoked_at IS NULL AND expires_at > :now "
                "ORDER BY created_at DESC, id LIMIT 500"
            ),
            {"now": now},
        )
        return [_to_invite(row) for row in result]

    async def revoke(self, invite_id: UUID, now: datetime) -> bool:
        result = await self._s.execute(
            text(
                "UPDATE invites SET revoked_at = :now "
                "WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL RETURNING id"
            ),
            {"id": invite_id, "now": now},
        )
        return result.first() is not None

    async def mark_accepted(self, invite_id: UUID, user_id: UUID, now: datetime) -> bool:
        # Atomic claim: the conditions are re-checked under the row lock, so of two simultaneous accepts
        # exactly one UPDATE matches.
        result = await self._s.execute(
            text(
                "UPDATE invites SET accepted_at = :now, accepted_user_id = :user_id "
                "WHERE id = :id AND accepted_at IS NULL AND revoked_at IS NULL AND expires_at > :now RETURNING id"
            ),
            {"id": invite_id, "user_id": user_id, "now": now},
        )
        return result.first() is not None
