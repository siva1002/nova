"""The events our code writes to the outbox match the event contracts (contracts/events/*.schema.json).

Each test builds a payload with the SAME builder function the use cases call, wraps it in the envelope
the way Debezium will (sprint 3), and validates it against the JSON Schema. If someone renames a field in
a builder, or changes a schema, this fails before any consumer does.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from access_service.domain.models import Member, Workspace
from access_service.events.builders import member_event, workspace_event
from common.ids import new_id
from identity_service.domain.models import User
from identity_service.usecases.sign_up import user_event
from time_service.domain.models import TimeEntry
from time_service.usecases.create_entry import entry_event

EVENTS = Path(__file__).resolve().parents[2] / "contracts" / "events"
NOW = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def schemas() -> tuple[dict[str, Any], Registry]:
    loaded = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in EVENTS.glob("*.schema.json")}
    registry = Registry().with_resources([(name, Resource.from_contents(s)) for name, s in loaded.items()])
    return loaded, registry


def envelope(event_type: str, aggregate_type: str, data: dict[str, Any]) -> dict[str, Any]:
    """The envelope fields come from the outbox row's columns; `data` is the row's payload."""
    return {
        "id": str(new_id()),
        "type": event_type,
        "schema_version": 1,
        "workspace_id": str(new_id()),
        "aggregate_type": aggregate_type,
        "aggregate_id": str(new_id()),
        "aggregate_version": 1,
        "occurred_at": NOW.isoformat(),
        "actor": {"type": "user", "id": str(new_id())},
        "depth": 0,
        "data": data,
    }


def assert_valid(schemas, schema_name: str, event: dict[str, Any]) -> None:
    loaded, registry = schemas
    errors = [e.message for e in Draft202012Validator(loaded[schema_name], registry=registry).iter_errors(event)]
    assert errors == [], errors


def test_identity_user_created(schemas):
    user = User(
        new_id(),
        "asha@example.com",
        "asha",
        "Asha Rao",
        "AR",
        "#7B68EE",
        None,
        None,
        None,
        False,
        "active",
        1,
        NOW,
        NOW,
    )
    assert_valid(schemas, "identity.user.v1.schema.json", envelope("identity.user.created", "user", user_event(user)))


def test_access_workspace_and_member_events(schemas):
    ws = Workspace(new_id(), "Pilot", "pilot", "provisioning", new_id(), 1, NOW, NOW)
    member = Member(
        new_id(), ws.id, new_id(), "owner", "active", "asha@example.com", "Asha Rao", None, NOW, 1, NOW, NOW
    )
    for event_type in ("access.workspace.created", "access.workspace.updated"):
        assert_valid(
            schemas,
            "access.workspace.v1.schema.json",
            envelope(event_type, "workspace", workspace_event(ws, "aps1-c01")),
        )
    assert_valid(
        schemas,
        "access.member.v1.schema.json",
        envelope("access.member.added", "member", member_event(member, ws.name, "aps1-c01")),
    )


def test_time_entry_events(schemas):
    entry = TimeEntry(
        new_id(),
        new_id(),
        new_id(),
        new_id(),
        new_id(),
        NOW,
        NOW + timedelta(hours=1),
        3_600_000,
        "",
        False,
        "manual",
        1,
    )
    for event_type in ("time.entry.created", "time.entry.updated"):
        assert_valid(schemas, "time.entry.v1.schema.json", envelope(event_type, "time_entry", entry_event(entry)))


def test_a_broken_payload_is_caught(schemas):
    """Proves the check has teeth: a payload missing a required field must fail."""
    loaded, registry = schemas
    bad = envelope("access.member.added", "member", {"after": {"user_id": str(new_id())}})
    assert list(Draft202012Validator(loaded["access.member.v1.schema.json"], registry=registry).iter_errors(bad))
