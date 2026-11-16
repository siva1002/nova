"""Domain rules: pure functions, no fakes needed."""

from datetime import UTC, datetime, timedelta

import pytest

from time_service.domain.entry_rules import (
    MAX_DURATION_MS,
    EntryInFuture,
    InvalidDuration,
    validate_entry_times,
)

NOW = datetime(2026, 11, 25, 12, 0, tzinfo=UTC)
HOUR = 3_600_000


def test_valid_entry_passes():
    validate_entry_times(NOW - timedelta(hours=3), 2 * HOUR + HOUR // 2, NOW)  # 2 h 30 min, ended 30 min ago


@pytest.mark.parametrize("duration", [0, 59_999, MAX_DURATION_MS + 1, -5])
def test_duration_out_of_range(duration):
    with pytest.raises(InvalidDuration):
        validate_entry_times(NOW - timedelta(days=2), duration, NOW)


def test_entry_may_not_end_in_the_future():
    with pytest.raises(EntryInFuture):
        validate_entry_times(NOW, HOUR, NOW)


def test_small_clock_skew_is_tolerated():
    validate_entry_times(NOW - timedelta(minutes=1) + timedelta(seconds=30), 60_000, NOW)  # ends 30 s ahead
