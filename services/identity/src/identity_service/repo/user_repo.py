"""SQL for users and their credentials (implements usecases.ports.UserRepo).

Queries only: no rules, no commits (the api/ layer owns the transaction).
Tables: users, user_credentials (tools/db-split/identity.sql). These are GLOBAL tables: no workspace_id,
no row-level security; every query filters by user id or email explicitly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from identity_service.domain.models import Credentials, User

_USER_COLUMNS = (
    "u.id, u.email, u.username, u.display_name, u.initials, u.color, u.avatar_url, u.timezone, u.locale, "
    "u.email_verified_at, u.status, u.version, u.created_at, u.updated_at"
)


def _to_user(row: Any) -> User:
    return User(
        id=row.id,
        email=row.email,
        username=row.username,
        display_name=row.display_name or "",
        initials=row.initials or "",
        color=row.color or "",
        avatar_url=row.avatar_url,
        timezone=row.timezone,
        locale=row.locale,
        email_verified=row.email_verified_at is not None,
        status=row.status,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlUserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def insert_user(self, user: User, password_hash: str) -> bool:
        # ON CONFLICT on the unique index users_email_uk (lower(email), live rows only) makes this
        # race-safe: of two concurrent sign-ups with one email, exactly one inserts; the other gets no row.
        result = await self._s.execute(
            text(
                "INSERT INTO users (id, email, username, display_name, initials, color, timezone, created_at, updated_at) "
                "VALUES (:id, :email, :username, :display_name, :initials, :color, :timezone, :now, :now) "
                "ON CONFLICT (lower(email)) WHERE deleted_at IS NULL DO NOTHING RETURNING id"
            ),
            {
                "id": user.id,
                "email": user.email,
                "username": user.username,
                "display_name": user.display_name,
                "initials": user.initials,
                "color": user.color,
                "timezone": user.timezone,
                "now": user.created_at,
            },
        )
        if result.first() is None:
            return False
        await self._s.execute(
            text(
                "INSERT INTO user_credentials (user_id, password_hash, password_changed_at) "
                "VALUES (:user_id, :hash, :now)"
            ),
            {"user_id": user.id, "hash": password_hash, "now": user.created_at},
        )
        return True

    async def get_by_email(self, email: str) -> tuple[User, Credentials] | None:
        result = await self._s.execute(
            text(
                f"SELECT {_USER_COLUMNS}, c.password_hash, c.failed_attempts, c.locked_until "
                "FROM users u LEFT JOIN user_credentials c ON c.user_id = u.id "
                "WHERE lower(u.email) = :email AND u.deleted_at IS NULL"
            ),
            {"email": email},
        )
        row = result.first()
        if row is None:
            return None
        cred = Credentials(row.id, row.password_hash, row.failed_attempts or 0, row.locked_until)
        return _to_user(row), cred

    async def get_by_id(self, user_id: UUID) -> User | None:
        result = await self._s.execute(
            text(f"SELECT {_USER_COLUMNS} FROM users u WHERE u.id = :id AND u.deleted_at IS NULL"),
            {"id": user_id},
        )
        row = result.first()
        return _to_user(row) if row else None

    async def register_failed_sign_in(
        self, user_id: UUID, now: datetime, max_attempts: int, lock_until: datetime
    ) -> tuple[int, datetime | None]:
        # ONE atomic statement, so parallel wrong guesses cannot under-count.
        # A lock that already ran out starts a fresh count at 1 (otherwise the next single mistake
        # would lock the account again immediately). Right-hand sides see the OLD row values.
        result = await self._s.execute(
            text(
                """
                UPDATE user_credentials SET
                  failed_attempts = CASE WHEN locked_until IS NOT NULL AND locked_until <= :now
                                         THEN 1 ELSE failed_attempts + 1 END,
                  locked_until = CASE
                      WHEN (CASE WHEN locked_until IS NOT NULL AND locked_until <= :now
                                 THEN 1 ELSE failed_attempts + 1 END) >= :max_attempts
                      THEN CAST(:lock_until AS timestamptz) ELSE NULL END,
                  updated_at = :now
                WHERE user_id = :user_id
                RETURNING failed_attempts, locked_until
                """
            ),
            {"user_id": user_id, "now": now, "max_attempts": max_attempts, "lock_until": lock_until},
        )
        row = result.one()
        return int(row.failed_attempts), row.locked_until

    async def reset_failed_sign_ins(self, user_id: UUID) -> None:
        await self._s.execute(
            text("UPDATE user_credentials SET failed_attempts = 0, locked_until = NULL WHERE user_id = :user_id"),
            {"user_id": user_id},
        )

    async def update_password_hash(self, user_id: UUID, password_hash: str, now: datetime) -> None:
        await self._s.execute(
            text("UPDATE user_credentials SET password_hash = :hash, updated_at = :now WHERE user_id = :user_id"),
            {"user_id": user_id, "hash": password_hash, "now": now},
        )
