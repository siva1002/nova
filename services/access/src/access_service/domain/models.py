"""Domain types of the access service. Plain dataclasses: no ORM, no web framework.

Tables: tools/db-split/access.sql (workspaces, workspace_members, invites, roles ...) plus
migrations/versions/0002_mvp_access.py (provision_status, member profile snapshot, self-read policy).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Actor:
    """The signed-in user, from the verified token. Email and name are the snapshot taken at sign-in."""

    user_id: UUID
    email: str
    display_name: str


@dataclass(frozen=True, slots=True)
class Workspace:
    id: UUID  # the tenant key of every workspace-scoped table in every service
    name: str
    slug: str | None
    status: str  # 'provisioning' (first space not seeded yet) | 'active'
    created_by: UUID | None
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class NewWorkspace:
    id: UUID  # chosen by the client (uuidv7), which makes a retried request harmless
    name: str
    slug: str


@dataclass(frozen=True, slots=True)
class Member:
    id: UUID
    workspace_id: UUID
    user_id: UUID
    role_kind: str  # 'owner' | 'admin' | 'member' | 'guest'
    status: str  # 'active' | 'pending' | 'deactivated'
    email: str  # snapshot from the user's token when they joined (kept fresh from events in sprint 3)
    display_name: str
    invited_by: UUID | None
    joined_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime

    @property
    def is_active(self) -> bool:
        return self.status == "active"


@dataclass(frozen=True, slots=True)
class MyWorkspace:
    """One row of "workspaces I belong to" (GET /v1/me/workspaces)."""

    workspace_id: UUID
    name: str
    role_kind: str
    status: str


@dataclass(frozen=True, slots=True)
class Invite:
    id: UUID
    workspace_id: UUID
    email: str  # lower-cased; the invite can only be accepted by a user signed in with this email
    role_kind: str  # 'admin' | 'member' in the MVP
    invited_by: UUID
    token_hash: str  # sha256 hex of the link token; the token itself is never stored
    expires_at: datetime
    accepted_at: datetime | None
    accepted_user_id: UUID | None
    revoked_at: datetime | None
    version: int
    created_at: datetime
    updated_at: datetime

    def state(self, now: datetime) -> str:
        """'accepted' | 'revoked' | 'expired' | 'open' (checked in that order)."""
        if self.accepted_at is not None:
            return "accepted"
        if self.revoked_at is not None:
            return "revoked"
        if self.expires_at <= now:
            return "expired"
        return "open"


@dataclass(frozen=True, slots=True)
class InviteRequest:
    email: str
    role_kind: str


@dataclass(frozen=True, slots=True)
class InviteResult:
    """Outcome for ONE invite of a batch (the batch answers 207 with one of these per item)."""

    email: str
    status: int  # 201 created, 409 already a member / already invited, 422 invalid
    invite: Invite | None = None
    token: str | None = None  # the link token, returned ONCE to the inviter (MVP: no email sending yet)
    code: str | None = None  # machine code of the refusal
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class PermissionCheck:
    """One question to the permission engine. The MVP role check only looks at `permission`; the other
    fields are accepted so callers already send what the full engine (sprint 13) needs."""

    permission: str
    node_ids: tuple[UUID, ...] = ()
    task_id: UUID | None = None
    creator_id: UUID | None = None
    assignee_ids: tuple[UUID, ...] = ()
