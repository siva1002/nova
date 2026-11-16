"""Domain types for time entries. Plain dataclasses: no ORM, no web framework."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TimeEntry:
    id: UUID
    workspace_id: UUID
    user_id: UUID
    task_id: UUID
    list_id: UUID  # copied from the task at write time, so list reports need no join
    started_at: datetime
    ended_at: datetime  # = started_at + duration (manual entries always have an end)
    duration_ms: int
    description: str
    billable: bool
    source: str  # 'manual' in the MVP; 'timer' arrives in sprint 36
    version: int


@dataclass(frozen=True, slots=True)
class NewEntry:
    """What a user sends to log time by hand."""

    task_id: UUID
    started_at: datetime
    duration_ms: int
    description: str = ""
    billable: bool = False


@dataclass(frozen=True, slots=True)
class EntryChanges:
    """Edit of an existing entry. `version` is what the client last read (optimistic concurrency)."""

    version: int
    started_at: datetime | None = None
    duration_ms: int | None = None
    description: str | None = None
    billable: bool | None = None


@dataclass(frozen=True, slots=True)
class TaskRef:
    """The two facts we need from the tasks service."""

    id: UUID
    list_id: UUID
