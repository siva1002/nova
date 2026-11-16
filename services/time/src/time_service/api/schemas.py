"""Request/response models for the time API. JSON is camelCase to match contracts/openapi/*.yaml;
Python and the database stay snake_case. Kept separate from domain/ so the wire format can change
without touching business rules."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from time_service.domain.models import EntryChanges, NewEntry, TimeEntry


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class EntryIn(_Wire):
    task_id: UUID
    started_at: datetime
    duration_ms: int = Field(gt=0)
    description: str = Field(default="", max_length=2000)
    billable: bool = False

    def to_cmd(self) -> NewEntry:
        return NewEntry(self.task_id, self.started_at, self.duration_ms, self.description, self.billable)


class EntryPatch(_Wire):
    version: int  # the version the client read; a mismatch returns 409
    started_at: datetime | None = None
    duration_ms: int | None = Field(default=None, gt=0)
    description: str | None = Field(default=None, max_length=2000)
    billable: bool | None = None

    def to_changes(self) -> EntryChanges:
        return EntryChanges(self.version, self.started_at, self.duration_ms, self.description, self.billable)


class EntryOut(_Wire):
    id: UUID
    task_id: UUID
    list_id: UUID
    user_id: UUID
    started_at: datetime
    ended_at: datetime
    duration_ms: int
    description: str
    billable: bool
    source: str
    version: int

    @classmethod
    def from_domain(cls, e: TimeEntry) -> EntryOut:
        return cls(**{f: getattr(e, f) for f in cls.model_fields})
