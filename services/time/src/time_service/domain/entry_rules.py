"""Business rules for manual time entries. PURE: takes values, raises domain errors, returns values.

Rules (sprint plan, S1-19):
  - duration from 1 minute to 24 hours
  - you cannot log time that ends in the future (60 s of clock skew is tolerated)
  - editing re-applies the same rules to the new values
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from common.errors import Unprocessable
from time_service.domain.models import EntryChanges, TimeEntry

MIN_DURATION_MS = 60_000  # 1 minute
MAX_DURATION_MS = 24 * 3_600_000  # 24 hours
FUTURE_TOLERANCE = timedelta(seconds=60)


class InvalidDuration(Unprocessable):
    code, slug, title = "time.invalid_duration", "invalid-duration", "Duration must be between 1 minute and 24 hours"


class EntryInFuture(Unprocessable):
    code, slug, title = "time.entry_in_future", "entry-in-future", "Time cannot be logged in the future"


def validate_entry_times(started_at: datetime, duration_ms: int, now: datetime) -> None:
    if not MIN_DURATION_MS <= duration_ms <= MAX_DURATION_MS:
        raise InvalidDuration()
    if started_at + timedelta(milliseconds=duration_ms) > now + FUTURE_TOLERANCE:
        raise EntryInFuture()


def apply_changes(entry: TimeEntry, changes: EntryChanges, now: datetime) -> TimeEntry:
    """Return the edited entry (not yet saved). Re-validates the resulting times."""
    started_at = changes.started_at or entry.started_at
    duration_ms = entry.duration_ms if changes.duration_ms is None else changes.duration_ms
    validate_entry_times(started_at, duration_ms, now)
    return replace(
        entry,
        started_at=started_at,
        duration_ms=duration_ms,
        ended_at=started_at + timedelta(milliseconds=duration_ms),
        description=entry.description if changes.description is None else changes.description,
        billable=entry.billable if changes.billable is None else changes.billable,
    )
