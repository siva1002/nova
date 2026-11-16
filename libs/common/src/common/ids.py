"""Identifiers. Every primary key in every service is a UUIDv7: time-ordered, so inserts stay index-friendly."""

from __future__ import annotations

from uuid import UUID

import uuid_utils


def new_id() -> UUID:
    return UUID(bytes=uuid_utils.uuid7().bytes)
