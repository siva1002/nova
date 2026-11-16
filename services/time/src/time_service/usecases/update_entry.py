"""USE CASE: edit a time entry (S1-19). Your own entries freely; other people's only with the `manage_timesheets` capability
(Owner/Admin in the MVP role check). A stale `version` returns 409 instead of silently overwriting."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from common.context import RequestContext
from common.errors import NotFound, VersionConflict
from common.ports import Clock, EventSink
from time_service.domain.entry_rules import apply_changes
from time_service.domain.models import EntryChanges, TimeEntry
from time_service.usecases.create_entry import entry_event
from time_service.usecases.ports import EntryRepo, Permissions


async def update_entry(
    ctx: RequestContext,
    entry_id: UUID,
    changes: EntryChanges,
    *,
    repo: EntryRepo,
    perms: Permissions,
    events: EventSink,
    clock: Clock,
) -> TimeEntry:
    entry = await repo.get(entry_id)
    if entry is None:
        raise NotFound("Time entry not found")
    if entry.user_id != ctx.user_id:
        await perms.require(ctx, "manage_timesheets")  # someone else's entry: needs Admin/Owner
    if entry.version != changes.version:
        raise VersionConflict("The entry changed since you read it", current_version=entry.version)

    edited = apply_changes(entry, changes, clock.now())  # pure rules re-validate the new values
    new_version = await repo.update(edited, expected_version=changes.version)
    if new_version is None:  # lost a race between our read and write
        raise VersionConflict("The entry changed since you read it")
    edited = replace(edited, version=new_version)
    events.add("time.entry.updated", "time_entry", edited.id, edited.version, entry_event(edited))
    return edited
