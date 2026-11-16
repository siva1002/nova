"""SQL for workspaces (implements usecases.ports.WorkspaceRepo).

`workspaces` is the tenant ROOT: it has no workspace_id column and therefore no row-level security.
Every query here names the workspace id explicitly. The other tables touched (roles via
seed_default_roles, access_epochs) are protected by forced RLS, so the transaction must be scoped to the
workspace (common.web.transaction / global_transaction(workspace_id=...)).
Queries only: no rules, no commits.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from access_service.domain.models import Workspace

_COLUMNS = "id, name, slug, provision_status, created_by, version, created_at, updated_at"


def _to_workspace(row: Any) -> Workspace:
    return Workspace(
        id=row.id,
        name=row.name,
        slug=row.slug,
        status=row.provision_status,
        created_by=row.created_by,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class SqlWorkspaceRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def insert(self, workspace: Workspace) -> bool:
        # ON CONFLICT DO NOTHING (no target) covers both unique rules: the id and the slug.
        # No row back = one of them is taken; the use case works out which.
        result = await self._s.execute(
            text(
                "INSERT INTO workspaces (id, name, slug, provision_status, created_by, created_at, updated_at) "
                "VALUES (:id, :name, :slug, :status, :created_by, :now, :now) "
                "ON CONFLICT DO NOTHING RETURNING id"
            ),
            {
                "id": workspace.id,
                "name": workspace.name,
                "slug": workspace.slug,
                "status": workspace.status,
                "created_by": workspace.created_by,
                "now": workspace.created_at,
            },
        )
        return result.first() is not None

    async def get(self, workspace_id: UUID) -> Workspace | None:
        result = await self._s.execute(
            text(f"SELECT {_COLUMNS} FROM workspaces WHERE id = :id AND deleted_at IS NULL"),
            {"id": workspace_id},
        )
        row = result.first()
        return _to_workspace(row) if row else None

    async def rename(self, workspace_id: UUID, name: str, expected_version: int) -> Workspace | None:
        # Optimistic concurrency: matches only while nobody else has saved. The bump_version trigger
        # (tools/db-split/_prelude.sql) raises `version` and `updated_at` on every UPDATE.
        result = await self._s.execute(
            text(
                "UPDATE workspaces SET name = :name "
                "WHERE id = :id AND version = :expected AND deleted_at IS NULL "
                f"RETURNING {_COLUMNS}"
            ),
            {"id": workspace_id, "name": name, "expected": expected_version},
        )
        row = result.first()
        return _to_workspace(row) if row else None

    async def seed_default_roles(self, workspace_id: UUID) -> None:
        await self._s.execute(text("SELECT seed_default_roles(:id)"), {"id": workspace_id})

    async def mark_active(self, workspace_id: UUID) -> None:
        # Idempotent, and it does not touch `version`-relevant data for clients beyond the status flip.
        await self._s.execute(
            text(
                "UPDATE workspaces SET provision_status = 'active' WHERE id = :id AND provision_status = 'provisioning'"
            ),
            {"id": workspace_id},
        )

    async def bump_epoch(self, workspace_id: UUID) -> None:
        await self._s.execute(
            text(
                "INSERT INTO access_epochs (workspace_id, epoch) VALUES (:id, 1) "
                "ON CONFLICT (workspace_id) DO UPDATE SET epoch = access_epochs.epoch + 1, updated_at = now()"
            ),
            {"id": workspace_id},
        )
