"""USE CASE: log time by hand on a task (S1-19). The worked example of the service-layer pattern.

Order matters (docs/adr/0004): every check and every call to another service happens BEFORE our own write,
and the write plus its outbox event are one transaction (opened by the api/ layer). Nothing is written to
another service, so a failure leaves nothing half-done.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from common.context import RequestContext
from common.ids import new_id
from common.ports import Clock, EventSink
from time_service.domain.entry_rules import validate_entry_times
from time_service.domain.models import NewEntry, TimeEntry
from time_service.usecases.ports import EntryRepo, Permissions, TasksClient


def entry_event(e: TimeEntry, *, deleted: bool = False) -> dict[str, Any]:
    """Payload (`data`) of time.entry.* events; shape in contracts/events/time.entry.v1.schema.json."""
    return {
        "after": {
            "id": str(e.id),
            "version": e.version,
            "task_id": str(e.task_id),
            "list_id": str(e.list_id),
            "user_id": str(e.user_id),
            "started_at": e.started_at.isoformat(),
            "ended_at": e.ended_at.isoformat(),
            "duration_ms": e.duration_ms,
            "billable": e.billable,
            "locked": False,
            "deleted": deleted,
        }
    }


async def create_entry(
    ctx: RequestContext,
    cmd: NewEntry,
    *,
    repo: EntryRepo,
    tasks: TasksClient,
    perms: Permissions,
    events: EventSink,
    clock: Clock,
) -> TimeEntry:
    validate_entry_times(cmd.started_at, cmd.duration_ms, clock.now())  # 1. pure rules first: cheapest
    await perms.require(ctx, "track_time", task_id=cmd.task_id)  # 2. may this user log time here?
    task = await tasks.get_task(ctx, cmd.task_id)  # 3. task exists and is visible

    entry = TimeEntry(  # 4. build the new entry
        id=new_id(),
        workspace_id=ctx.workspace_id,
        user_id=ctx.user_id,  # you can only log for yourself
        task_id=task.id,
        list_id=task.list_id,
        started_at=cmd.started_at,
        ended_at=cmd.started_at + timedelta(milliseconds=cmd.duration_ms),
        duration_ms=cmd.duration_ms,
        description=cmd.description,
        billable=cmd.billable,
        source="manual",
        version=1,
    )
    await repo.insert(entry)  # 5. write (own database only)
    events.add("time.entry.created", "time_entry", entry.id, entry.version, entry_event(entry))  # 6. outbox
    return entry
