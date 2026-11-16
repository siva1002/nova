"""SQL for time entries. Queries only: no rules, no permission checks, no commits.

The session already has `app.workspace_id` set (common.db.workspace_transaction), so forced RLS limits every
query to the current workspace. Inserts still carry workspace_id explicitly (the policy's WITH CHECK needs it).
Table: tools/db-split/time.sql (time_entries, hash-partitioned by workspace_id).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from time_service.domain.models import TimeEntry

_COLUMNS = (
    "id, workspace_id, user_id, task_id, list_id, started_at, ended_at, duration_ms, "
    "description, billable, source, version"
)


def _to_entry(row: Any) -> TimeEntry:
    return TimeEntry(
        id=row.id,
        workspace_id=row.workspace_id,
        user_id=row.user_id,
        task_id=row.task_id,
        list_id=row.list_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        duration_ms=row.duration_ms,
        description=row.description,
        billable=row.billable,
        source=row.source,
        version=row.version,
    )


class TimeRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def insert(self, e: TimeEntry) -> None:
        await self._s.execute(
            text(
                f"INSERT INTO time_entries ({_COLUMNS}) VALUES "
                "(:id, :ws, :user_id, :task_id, :list_id, :started_at, :ended_at, :duration_ms, "
                ":description, :billable, :source, :version)"
            ),
            {
                "id": e.id,
                "ws": e.workspace_id,
                "user_id": e.user_id,
                "task_id": e.task_id,
                "list_id": e.list_id,
                "started_at": e.started_at,
                "ended_at": e.ended_at,
                "duration_ms": e.duration_ms,
                "description": e.description,
                "billable": e.billable,
                "source": e.source,
                "version": e.version,
            },
        )

    async def get(self, entry_id: UUID) -> TimeEntry | None:
        result = await self._s.execute(
            text(f"SELECT {_COLUMNS} FROM time_entries WHERE id = :id AND deleted_at IS NULL"),
            {"id": entry_id},
        )
        row = result.first()
        return _to_entry(row) if row else None

    async def update(self, e: TimeEntry, expected_version: int) -> int | None:
        """Optimistic concurrency in SQL: only matches while the stored version is still the one the client
        read. The bump_version trigger raises `version` on every UPDATE; RETURNING gives the new value."""
        result = await self._s.execute(
            text(
                "UPDATE time_entries SET started_at = :started_at, ended_at = :ended_at, "
                "duration_ms = :duration_ms, description = :description, billable = :billable "
                "WHERE id = :id AND version = :expected AND deleted_at IS NULL RETURNING version"
            ),
            {
                "id": e.id,
                "expected": expected_version,
                "started_at": e.started_at,
                "ended_at": e.ended_at,
                "duration_ms": e.duration_ms,
                "description": e.description,
                "billable": e.billable,
            },
        )
        row = result.first()
        return int(row.version) if row else None
