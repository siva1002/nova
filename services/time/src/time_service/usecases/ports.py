"""What the use cases need from the outside world, as Protocols.

Real implementations: repo/time_repo.py, clients/tasks_client.py, common.permissions.PermissionClient.
Test implementations: tests/unit/conftest.py (in-memory fakes).
"""

from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from common.context import RequestContext
from time_service.domain.models import TaskRef, TimeEntry


class EntryRepo(Protocol):
    async def insert(self, entry: TimeEntry) -> None: ...
    async def get(self, entry_id: UUID) -> TimeEntry | None: ...
    async def update(self, entry: TimeEntry, expected_version: int) -> int | None:
        """Save the edit only if the stored version equals `expected_version`.
        Returns the new version, or None when the version no longer matches (someone else edited)."""
        ...


class TasksClient(Protocol):
    async def get_task(self, ctx: RequestContext, task_id: UUID) -> TaskRef:
        """Raises NotFound if the task does not exist OR the user may not see it."""
        ...


class Permissions(Protocol):
    async def require(self, ctx: RequestContext, permission: str, **resource: Any) -> None:
        """Raises Forbidden. Satisfied by common.permissions.PermissionClient."""
        ...
