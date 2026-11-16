"""The only place that reads the wall clock. Use cases take a `Clock`, so tests control time. PURE."""

from __future__ import annotations

from datetime import UTC, datetime


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)
