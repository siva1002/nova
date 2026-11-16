"""What the access use cases need from the outside world, as Protocols.

Real implementations: repo/*.py (SQL) and clients/hierarchy_client.py.
Test implementations: tests/unit/fakes.py (in-memory).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from access_service.domain.models import Invite, Member, MyWorkspace, Workspace


class WorkspaceRepo(Protocol):
    async def insert(self, workspace: Workspace) -> bool:
        """False (nothing written) if the id or the slug is already taken. Race-safe."""
        ...

    async def get(self, workspace_id: UUID) -> Workspace | None: ...

    async def rename(self, workspace_id: UUID, name: str, expected_version: int) -> Workspace | None:
        """Save only while the stored version equals `expected_version`; None if it moved on."""
        ...

    async def seed_default_roles(self, workspace_id: UUID) -> None:
        """Create the workspace's role templates (SQL function seed_default_roles)."""
        ...

    async def mark_active(self, workspace_id: UUID) -> None: ...

    async def bump_epoch(self, workspace_id: UUID) -> None:
        """Advance the workspace's permission epoch. Every change that can alter a permission answer
        calls this, so caches keyed by the epoch (sprint 13) go stale at once."""
        ...


class MemberRepo(Protocol):
    async def insert(self, member: Member) -> bool:
        """False if this user already has a membership in the workspace. Race-safe."""
        ...

    async def get_by_user(self, user_id: UUID) -> Member | None: ...
    async def get_by_email(self, email: str) -> Member | None: ...

    async def list_page(self, limit: int, after_id: UUID | None, status: str | None) -> list[Member]:
        """Members of the current workspace ordered by id, starting after `after_id` (keyset paging)."""
        ...

    async def list_for_user(self, user_id: UUID) -> list[MyWorkspace]:
        """Every workspace this user belongs to. The only cross-workspace read in the service."""
        ...


class InviteRepo(Protocol):
    async def insert(self, invite: Invite) -> bool:
        """False if an open invite for this email already exists in the workspace. Race-safe."""
        ...

    async def get(self, invite_id: UUID) -> Invite | None: ...
    async def get_by_token_hash(self, token_hash: str) -> Invite | None: ...
    async def list_open(self, now: datetime) -> list[Invite]: ...

    async def revoke(self, invite_id: UUID, now: datetime) -> bool:
        """True if an open invite was revoked by this call."""
        ...

    async def mark_accepted(self, invite_id: UUID, user_id: UUID, now: datetime) -> bool:
        """Atomically claim an open invite. False if someone else used or revoked it first."""
        ...


class HierarchyClient(Protocol):
    async def seed_workspace(self, workspace_id: UUID, owner_user_id: UUID, bearer_token: str | None) -> None:
        """Ask hierarchy to create the first space and the default statuses. Idempotent on their side.
        Raises DependencyUnavailable if hierarchy cannot be reached."""
        ...
