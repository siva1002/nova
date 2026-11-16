"""Domain types of the identity service. Plain dataclasses: no ORM, no web framework.

Users are GLOBAL (a person can belong to many workspaces), so nothing here has a workspace_id.
Tables: tools/db-split/identity.sql (users, user_credentials, user_sessions, signing_keys)
and migrations/versions/0002_refresh_tokens.py (refresh_tokens).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class User:
    id: UUID
    email: str  # stored lower-cased; looked up case-insensitively
    username: str
    display_name: str
    initials: str
    color: str
    avatar_url: str | None
    timezone: str | None
    locale: str | None
    email_verified: bool  # always False in the MVP (verification emails arrive in sprint 7)
    status: str  # 'active' | 'suspended'
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Credentials:
    user_id: UUID
    password_hash: str | None  # Argon2id; None for SSO-only users (later)
    failed_attempts: int
    locked_until: datetime | None


@dataclass(frozen=True, slots=True)
class Session:
    """One signed-in device. Ends when revoked, idle for too long, or past its absolute limit."""

    id: UUID
    user_id: UUID
    idle_expires_at: datetime
    absolute_expires_at: datetime
    revoked_at: datetime | None

    def is_live(self, now: datetime) -> bool:
        return self.revoked_at is None and self.idle_expires_at > now and self.absolute_expires_at > now


@dataclass(frozen=True, slots=True)
class RefreshToken:
    """A single-use token that buys the next access token. Only its SHA-256 hash is stored."""

    token_hash: bytes
    session_id: UUID
    user_id: UUID
    expires_at: datetime
    used_at: datetime | None


@dataclass(frozen=True, slots=True)
class SignUp:
    email: str
    password: str
    display_name: str
    timezone: str | None = None


@dataclass(frozen=True, slots=True)
class SessionPolicy:
    """Lifetimes and limits, from settings. Passed to use cases so they read no globals."""

    refresh_idle_seconds: int
    session_absolute_seconds: int
    max_failed_sign_ins: int
    lockout_seconds: int


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """What a successful sign-in or refresh hands back to the api/ layer."""

    access_token: str
    expires_in: int  # seconds
    refresh_token: str  # the raw value, for the HttpOnly cookie. Never logged, never stored
    refresh_expires_at: datetime
    user_id: UUID
    session_id: UUID
