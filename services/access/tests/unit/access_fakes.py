"""In-memory fakes for the access use cases. No database, no HTTP, no real clock.

The real repos are scoped to ONE workspace per transaction by row-level security. The fakes imitate that
with a shared `Scope`: tests set `scope.workspace_id` the way a route would open a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from access_service.domain.models import Actor, Invite, Member, MyWorkspace, Workspace
from common.errors import DependencyUnavailable
from common.ids import new_id

T0 = datetime(2026, 11, 19, 9, 0, tzinfo=UTC)
CELL = "aps1-c01"

ASHA = Actor(new_id(), "asha@example.com", "Asha Rao")  # creates workspaces: the Owner
BEN = Actor(new_id(), "ben@example.com", "Ben Okoro")  # gets invited
CARA = Actor(new_id(), "cara@example.com", "Cara Lim")  # an outsider


@dataclass
class Scope:
    workspace_id: UUID | None = None


class FakeClock:
    def __init__(self, now: datetime = T0) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, **delta: float) -> None:
        self.current += timedelta(**delta)


class FakeEvents:
    def __init__(self) -> None:
        self.added: list[tuple[str, UUID, dict[str, Any]]] = []

    def add(
        self, event_type: str, aggregate_type: str, aggregate_id: UUID, version: int | None, data: dict[str, Any]
    ) -> None:
        self.added.append((event_type, aggregate_id, data))

    def types(self) -> list[str]:
        return [e[0] for e in self.added]


class FakeWorkspaces:
    def __init__(self) -> None:
        self.rows: dict[UUID, Workspace] = {}
        self.roles_seeded: list[UUID] = []
        self.epochs: dict[UUID, int] = {}

    async def insert(self, workspace: Workspace) -> bool:
        if workspace.id in self.rows or any(w.slug == workspace.slug for w in self.rows.values()):
            return False
        self.rows[workspace.id] = workspace
        return True

    async def get(self, workspace_id: UUID) -> Workspace | None:
        return self.rows.get(workspace_id)

    async def rename(self, workspace_id: UUID, name: str, expected_version: int) -> Workspace | None:
        current = self.rows.get(workspace_id)
        if current is None or current.version != expected_version:
            return None
        self.rows[workspace_id] = replace(current, name=name, version=current.version + 1)
        return self.rows[workspace_id]

    async def seed_default_roles(self, workspace_id: UUID) -> None:
        self.roles_seeded.append(workspace_id)

    async def mark_active(self, workspace_id: UUID) -> None:
        self.rows[workspace_id] = replace(self.rows[workspace_id], status="active")

    async def bump_epoch(self, workspace_id: UUID) -> None:
        self.epochs[workspace_id] = self.epochs.get(workspace_id, 0) + 1


class FakeMembers:
    def __init__(self, scope: Scope, workspaces: FakeWorkspaces) -> None:
        self._scope = scope
        self._workspaces = workspaces
        self.rows: list[Member] = []

    def _here(self) -> list[Member]:
        return [m for m in self.rows if m.workspace_id == self._scope.workspace_id]

    async def insert(self, member: Member) -> bool:
        if any(m.workspace_id == member.workspace_id and m.user_id == member.user_id for m in self.rows):
            return False
        self.rows.append(member)
        return True

    async def get_by_user(self, user_id: UUID) -> Member | None:
        return next((m for m in self._here() if m.user_id == user_id), None)

    async def get_by_email(self, email: str) -> Member | None:
        return next((m for m in self._here() if m.email == email), None)

    async def list_page(self, limit: int, after_id: UUID | None, status: str | None) -> list[Member]:
        rows = sorted(self._here(), key=lambda m: m.id)
        rows = [m for m in rows if (after_id is None or m.id > after_id) and (status is None or m.status == status)]
        return rows[:limit]

    async def list_for_user(self, user_id: UUID) -> list[MyWorkspace]:
        mine = [m for m in self.rows if m.user_id == user_id and m.status != "deactivated"]
        return [
            MyWorkspace(m.workspace_id, self._workspaces.rows[m.workspace_id].name, m.role_kind, m.status) for m in mine
        ]

    # test helper
    def set_status(self, user_id: UUID, status: str) -> None:
        self.rows = [replace(m, status=status) if m.user_id == user_id else m for m in self.rows]


class FakeInvites:
    def __init__(self, scope: Scope) -> None:
        self._scope = scope
        self.rows: dict[UUID, Invite] = {}

    def _here(self) -> list[Invite]:
        return [i for i in self.rows.values() if i.workspace_id == self._scope.workspace_id]

    async def insert(self, invite: Invite) -> bool:
        now = invite.created_at
        for other in self._here():
            if other.email == invite.email and other.state(now) == "expired":
                self.rows[other.id] = replace(other, revoked_at=now)  # like the real repo: retire expired ones
        if any(i.email == invite.email and i.state(now) == "open" for i in self._here()):
            return False
        self.rows[invite.id] = invite
        return True

    async def get(self, invite_id: UUID) -> Invite | None:
        return next((i for i in self._here() if i.id == invite_id), None)

    async def get_by_token_hash(self, token_hash: str) -> Invite | None:
        return next((i for i in self._here() if i.token_hash == token_hash), None)

    async def list_open(self, now: datetime) -> list[Invite]:
        return [i for i in self._here() if i.state(now) == "open"]

    async def revoke(self, invite_id: UUID, now: datetime) -> bool:
        invite = await self.get(invite_id)
        if invite is None or invite.accepted_at is not None or invite.revoked_at is not None:
            return False
        self.rows[invite_id] = replace(invite, revoked_at=now)
        return True

    async def mark_accepted(self, invite_id: UUID, user_id: UUID, now: datetime) -> bool:
        invite = await self.get(invite_id)
        if invite is None or invite.state(now) != "open":
            return False
        self.rows[invite_id] = replace(invite, accepted_at=now, accepted_user_id=user_id)
        return True


class FakeHierarchy:
    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.seeded: list[UUID] = []

    async def seed_workspace(self, workspace_id: UUID, owner_user_id: UUID, bearer_token: str | None) -> None:
        if not self.available:
            raise DependencyUnavailable("Hierarchy service did not answer")
        self.seeded.append(workspace_id)
