"""Payload builders for the events access writes to its outbox.

Each returns the envelope's `data` object (contracts/events/envelope.schema.json): {"after": {...}} with
snake_case keys. Shapes: contracts/events/access.member.v1.schema.json and access.workspace.v1.schema.json.
"""

from __future__ import annotations

from typing import Any

from access_service.domain.models import Member, Workspace


def member_event(member: Member, workspace_name: str, cell_id: str) -> dict[str, Any]:
    """access.member.added | updated | removed. identity uses it for "my workspaces" (sprint 3)."""
    return {
        "after": {
            "user_id": str(member.user_id),
            "version": member.version,
            "role_kind": member.role_kind,
            "custom_role_id": None,
            "status": member.status,
            "cell_id": cell_id,
            "workspace_name": workspace_name,
            "group_ids": [],
        }
    }


def workspace_event(workspace: Workspace, cell_id: str) -> dict[str, Any]:
    """access.workspace.created | updated."""
    return {
        "after": {
            "id": str(workspace.id),
            "version": workspace.version,
            "name": workspace.name,
            "slug": workspace.slug,
            "status": workspace.status,
            "cell_id": cell_id,
            "created_by": str(workspace.created_by) if workspace.created_by else None,
        }
    }
