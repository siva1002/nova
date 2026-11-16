"""Transactional outbox writer. Implements the `EventSink` port (common.ports).

`add()` queues an event; `flush()` inserts the queued rows into the service's own `outbox` table using the
request's session, so events commit or roll back together with the data change. In sprint 3, Debezium reads
this table and publishes to Kafka. Until then the rows just accumulate: that is intentional, so nothing
needs rewriting when events switch on.

Row shape: tools/db-split/_prelude.sql (table `outbox`). `payload` is the envelope's `data` object
(contracts/events/envelope.schema.json), normally {"after": {...}}.

Partition key: the `workspace_id` column is the Kafka key, so one workspace's events stay in order.
Global services (identity) have no workspace; they pass workspace_id=None and the aggregate id is used
instead, which keeps one user's events in order.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from common.ids import new_id

_INSERT = text(
    """
    INSERT INTO outbox (id, workspace_id, aggregate_type, aggregate_id, aggregate_version,
                        event_type, payload, actor_user_id, origin)
    VALUES (:id, :key, :agg_type, :agg_id, :ver, :etype, CAST(:payload AS jsonb), :actor, :origin)
    """
)


class SqlOutbox:
    def __init__(self, session: AsyncSession, *, workspace_id: UUID | None, actor_user_id: UUID | None) -> None:
        self._session = session
        self._workspace_id = workspace_id
        self._actor = actor_user_id
        self._pending: list[dict[str, Any]] = []

    def add(
        self, event_type: str, aggregate_type: str, aggregate_id: UUID, version: int | None, data: dict[str, Any]
    ) -> None:
        # Sync on purpose: use cases stay simple. Rows are written by flush() just before the commit.
        self._pending.append(
            {
                "id": new_id(),
                "key": self._workspace_id or aggregate_id,
                "agg_type": aggregate_type,
                "agg_id": aggregate_id,
                "ver": version,
                "etype": event_type,
                "payload": json.dumps(data, default=str),
                "actor": self._actor,
                "origin": "user" if self._actor else "system",
            }
        )

    async def flush(self) -> None:
        """Called by common.web after the use case returns and before the transaction commits."""
        if self._pending:
            await self._session.execute(_INSERT, self._pending)  # one round trip (executemany)
            self._pending.clear()
