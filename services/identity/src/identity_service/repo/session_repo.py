"""SQL for sessions and refresh tokens (implements usecases.ports.SessionRepo).

Tables: user_sessions (tools/db-split/identity.sql), refresh_tokens (migration 0002).
Queries only: no rules, no commits.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from identity_service.domain.models import RefreshToken, Session

_TOKEN_COLUMNS = "token_hash, session_id, user_id, expires_at, used_at"


def _to_token(row: Any) -> RefreshToken:
    return RefreshToken(bytes(row.token_hash), row.session_id, row.user_id, row.expires_at, row.used_at)


class SqlSessionRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create_session(self, session: Session, ip: str | None, user_agent: str | None) -> None:
        await self._s.execute(
            text(
                "INSERT INTO user_sessions (id, user_id, ip, user_agent, idle_expires_at, absolute_expires_at) "
                "VALUES (:id, :user_id, CAST(:ip AS inet), :user_agent, :idle, :absolute)"
            ),
            {
                "id": session.id,
                "user_id": session.user_id,
                "ip": ip,
                "user_agent": (user_agent or "")[:400] or None,  # header is client-controlled: cap its size
                "idle": session.idle_expires_at,
                "absolute": session.absolute_expires_at,
            },
        )

    async def get_session(self, session_id: UUID) -> Session | None:
        result = await self._s.execute(
            text(
                "SELECT id, user_id, idle_expires_at, absolute_expires_at, revoked_at FROM user_sessions WHERE id = :id"
            ),
            {"id": session_id},
        )
        row = result.first()
        if row is None:
            return None
        return Session(row.id, row.user_id, row.idle_expires_at, row.absolute_expires_at, row.revoked_at)

    async def touch_session(self, session_id: UUID, now: datetime, idle_expires_at: datetime) -> None:
        await self._s.execute(
            text("UPDATE user_sessions SET last_seen_at = :now, idle_expires_at = :idle WHERE id = :id"),
            {"id": session_id, "now": now, "idle": idle_expires_at},
        )

    async def revoke_session(self, session_id: UUID, now: datetime) -> None:
        # Idempotent: an already revoked session keeps its original revoked_at.
        await self._s.execute(
            text("UPDATE user_sessions SET revoked_at = :now WHERE id = :id AND revoked_at IS NULL"),
            {"id": session_id, "now": now},
        )

    async def revoke_all_sessions(self, user_id: UUID, now: datetime) -> None:
        await self._s.execute(
            text("UPDATE user_sessions SET revoked_at = :now WHERE user_id = :user_id AND revoked_at IS NULL"),
            {"user_id": user_id, "now": now},
        )

    async def insert_refresh_token(self, token: RefreshToken) -> None:
        await self._s.execute(
            text(
                "INSERT INTO refresh_tokens (token_hash, session_id, user_id, expires_at) "
                "VALUES (:hash, :session_id, :user_id, :expires_at)"
            ),
            {
                "hash": token.token_hash,
                "session_id": token.session_id,
                "user_id": token.user_id,
                "expires_at": token.expires_at,
            },
        )

    async def claim_refresh_token(self, token_hash: bytes, now: datetime) -> RefreshToken | None:
        # The WHERE used_at IS NULL makes the claim atomic: PostgreSQL row-locks the token, so of two
        # concurrent refreshes exactly one UPDATE matches; the other sees used_at set and returns no row.
        result = await self._s.execute(
            text(
                "UPDATE refresh_tokens SET used_at = :now WHERE token_hash = :hash AND used_at IS NULL "
                f"RETURNING {_TOKEN_COLUMNS}"
            ),
            {"hash": token_hash, "now": now},
        )
        row = result.first()
        return _to_token(row) if row else None

    async def get_refresh_token(self, token_hash: bytes) -> RefreshToken | None:
        result = await self._s.execute(
            text(f"SELECT {_TOKEN_COLUMNS} FROM refresh_tokens WHERE token_hash = :hash"),
            {"hash": token_hash},
        )
        row = result.first()
        return _to_token(row) if row else None
