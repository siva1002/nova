"""Fixtures for access unit tests: one in-memory world per test (see access_fakes.py)."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # makes `import access_fakes` work from the tests

from access_fakes import ASHA, CELL, FakeClock, FakeEvents, FakeInvites, FakeMembers, FakeWorkspaces, Scope

from access_service.domain.models import Actor, InviteRequest, InviteResult, Member, NewWorkspace, Workspace
from access_service.usecases.invites import accept_invite, create_invites
from access_service.usecases.workspaces import create_workspace
from common.ids import new_id


@dataclass
class World:
    """Everything the use cases need, wired with fakes, plus shortcuts for the common steps."""

    scope: Scope
    workspaces: FakeWorkspaces
    members: FakeMembers
    invites: FakeInvites
    events: FakeEvents
    clock: FakeClock
    secret_counter: list[int] = field(default_factory=lambda: [0])

    def new_secret(self) -> bytes:
        self.secret_counter[0] += 1
        return self.secret_counter[0].to_bytes(32, "big")  # deterministic "random" secrets

    async def create_workspace(
        self, actor: Actor = ASHA, name: str = "Pilot", slug: str = "pilot", ws_id: UUID | None = None
    ) -> Workspace:
        cmd = NewWorkspace(ws_id or new_id(), name, slug)
        self.scope.workspace_id = cmd.id  # the route scopes the transaction to the new workspace
        return await create_workspace(
            cmd,
            actor,
            workspaces=self.workspaces,
            members=self.members,
            events=self.events,
            clock=self.clock,
            cell_id=CELL,
        )

    async def invite(self, workspace: Workspace, by: Actor, *requests: InviteRequest) -> list[InviteResult]:
        self.scope.workspace_id = workspace.id
        return await create_invites(
            by.user_id,
            workspace.id,
            list(requests),
            members=self.members,
            invites=self.invites,
            clock=self.clock,
            new_secret=self.new_secret,
        )

    async def accept(self, token: str, actor: Actor, workspace: Workspace) -> Member:
        self.scope.workspace_id = workspace.id  # the route reads the workspace from the token
        return await accept_invite(
            token,
            actor,
            workspace.id,
            workspaces=self.workspaces,
            members=self.members,
            invites=self.invites,
            events=self.events,
            clock=self.clock,
            cell_id=CELL,
        )

    async def join(self, workspace: Workspace, actor: Actor, role: str = "member", by: Actor = ASHA) -> Member:
        """Invite `actor` and accept: the usual way a second person gets into a workspace."""
        (result,) = await self.invite(workspace, by, InviteRequest(actor.email, role))
        assert result.token is not None, result
        return await self.accept(result.token, actor, workspace)


@pytest.fixture
def world() -> World:
    scope = Scope()
    workspaces = FakeWorkspaces()
    return World(scope, workspaces, FakeMembers(scope, workspaces), FakeInvites(scope), FakeEvents(), FakeClock())
