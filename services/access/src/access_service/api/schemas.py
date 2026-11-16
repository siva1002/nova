"""Request/response models of the access API. They mirror contracts/openapi/access.yaml.

JSON is camelCase on the wire (`roleKind`); Python stays snake_case. Kept apart from domain/ types so the
wire format can change without touching business rules.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from access_service.domain.models import (
    Invite,
    InviteRequest,
    InviteResult,
    Member,
    MyWorkspace,
    NewWorkspace,
    PermissionCheck,
    Workspace,
)


class _Wire(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------------------------- workspaces
class WorkspaceIn(_Wire):
    id: UUID  # chosen by the client, so a retried request is harmless
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=3, max_length=40)
    # Where the workspace should live. One cell in the MVP, so it is accepted and ignored; the routing
    # service (sprint 8) starts using it. Optional here so the MVP web app need not send it.
    region: str | None = Field(default=None, max_length=32)

    def to_cmd(self) -> NewWorkspace:
        return NewWorkspace(self.id, self.name, self.slug)


class WorkspacePatch(_Wire):
    version: int = Field(ge=1)  # the version the client read; a mismatch returns 409
    name: str = Field(min_length=1, max_length=120)


class WorkspaceOut(_Wire):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime
    name: str
    slug: str | None
    status: str

    @classmethod
    def from_domain(cls, w: Workspace) -> WorkspaceOut:
        return cls(**{name: getattr(w, name) for name in cls.model_fields})


class MyWorkspaceOut(_Wire):
    workspace_id: UUID
    name: str
    role_kind: str
    status: str

    @classmethod
    def from_domain(cls, w: MyWorkspace) -> MyWorkspaceOut:
        return cls(workspace_id=w.workspace_id, name=w.name, role_kind=w.role_kind, status=w.status)


# ------------------------------------------------------------------------------------------------- members
class MemberOut(_Wire):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime
    user_id: UUID
    display_name: str
    email: str
    role_kind: str
    custom_role_id: UUID | None = None
    status: str
    joined_at: datetime | None

    @classmethod
    def from_domain(cls, m: Member) -> MemberOut:
        return cls(
            id=m.id,
            version=m.version,
            created_at=m.created_at,
            updated_at=m.updated_at,
            user_id=m.user_id,
            display_name=m.display_name,
            email=m.email,
            role_kind=m.role_kind,
            status=m.status,
            joined_at=m.joined_at,
        )


class MemberPageOut(_Wire):
    items: list[MemberOut]
    next_cursor: str | None


# ------------------------------------------------------------------------------------------------- invites
class InviteItemIn(_Wire):
    # Loose on purpose: a bad address or role fails only ITS item of the batch (207), not the whole request.
    email: str = Field(max_length=254)
    role_kind: str = Field(max_length=20)


class InvitesIn(_Wire):
    invites: list[InviteItemIn] = Field(min_length=1, max_length=100)

    def to_requests(self) -> list[InviteRequest]:
        return [InviteRequest(i.email, i.role_kind) for i in self.invites]


class InviteOut(_Wire):
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime
    email: str
    role_kind: str
    expires_at: datetime
    invited_by: UUID

    @classmethod
    def from_domain(cls, i: Invite) -> InviteOut:
        return cls(**{name: getattr(i, name) for name in cls.model_fields})


class InviteProblemOut(_Wire):
    code: str
    detail: str


class InviteResultOut(_Wire):
    """One entry of the 207 answer. `invite_token` is present only for status 201 and only this once."""

    email: str
    status: int
    id: UUID | None = None
    invite_token: str | None = None
    expires_at: datetime | None = None
    problem: InviteProblemOut | None = None

    @classmethod
    def from_domain(cls, r: InviteResult) -> InviteResultOut:
        return cls(
            email=r.email,
            status=r.status,
            id=r.invite.id if r.invite else None,
            invite_token=r.token,
            expires_at=r.invite.expires_at if r.invite else None,
            problem=InviteProblemOut(code=r.code, detail=r.detail or "") if r.code else None,
        )


class InviteResultsOut(_Wire):
    results: list[InviteResultOut]


class AcceptInviteIn(_Wire):
    token: str = Field(min_length=1, max_length=200)


# --------------------------------------------------------------------------------------------- permissions
class CheckIn(_Wire):
    permission: str = Field(max_length=64)
    node_ids: list[UUID] = Field(default_factory=list, max_length=100)
    task_id: UUID | None = None
    creator_id: UUID | None = None
    assignee_ids: list[UUID] = Field(default_factory=list, max_length=100)

    def to_check(self) -> PermissionCheck:
        return PermissionCheck(
            self.permission, tuple(self.node_ids), self.task_id, self.creator_id, tuple(self.assignee_ids)
        )


class ChecksIn(_Wire):
    user_id: UUID
    checks: list[CheckIn] = Field(max_length=500)
