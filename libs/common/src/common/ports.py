"""Ports: small Protocols that use cases depend on instead of concrete classes. PURE.

Why: a use case that asks for an `EventSink` can be unit-tested with a 5-line fake, with no database.
The real implementations are wired in by FastAPI dependencies in each service's api/ layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...


class EventSink(Protocol):
    def add(
        self,
        event_type: str,  # "<service>.<aggregate>.<verb>", e.g. "time.entry.created"
        aggregate_type: str,  # e.g. "time_entry"
        aggregate_id: UUID,
        version: int | None,
        data: dict[str, Any],
    ) -> None:
        """Queue an event in the SAME transaction as the change (transactional outbox)."""
        ...
