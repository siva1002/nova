"""In-memory fakes for the time use cases. No database, no HTTP, no real clock.

Fakes instead of mock libraries: tests read like the real thing and survive refactors.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from common.context import RequestContext
from common.errors import Forbidden, NotFound
from time_service.domain.models import TaskRef, TimeEntry

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
WS, USER_A, USER_B, TASK, LIST = (uuid4() for _ in range(5))


class FakeClock:
    def now(self) -> datetime:
        return NOW


class FakeEvents:
    def __init__(self) -> None:
        self.added: list[tuple[str, UUID, int | None]] = []

    def add(
        self, event_type: str, aggregate_type: str, aggregate_id: UUID, version: int | None, data: dict[str, Any]
    ) -> None:
        self.added.append((event_type, aggregate_id, version))


class FakeRepo:
    def __init__(self) -> None:
        self.rows: dict[UUID, TimeEntry] = {}

    async def insert(self, entry: TimeEntry) -> None:
        self.rows[entry.id] = entry

    async def get(self, entry_id: UUID) -> TimeEntry | None:
        return self.rows.get(entry_id)

    async def update(self, entry: TimeEntry, expected_version: int) -> int | None:
        stored = self.rows[entry.id]
        if stored.version != expected_version:
            return None
        self.rows[entry.id] = replace(entry, version=stored.version + 1)
        return stored.version + 1


class FakeTasks:
    def __init__(self, visible: bool = True) -> None:
        self.visible = visible

    async def get_task(self, ctx: RequestContext, task_id: UUID) -> TaskRef:
        if not self.visible or task_id != TASK:
            raise NotFound("Task not found")
        return TaskRef(id=TASK, list_id=LIST)


class FakePerms:
    """Stands in for access. `admins` are users holding every permission; others only `track_time`."""

    def __init__(self, admins: set[UUID] | None = None) -> None:
        self.admins = admins or set()

    async def require(self, ctx: RequestContext, permission: str, **resource: Any) -> None:
        if ctx.user_id in self.admins or permission == "track_time":
            return
        raise Forbidden(f"Missing permission: {permission}")


def make_ctx(user: UUID) -> RequestContext:
    return RequestContext(user_id=user, workspace_id=WS, request_id="req-test")
