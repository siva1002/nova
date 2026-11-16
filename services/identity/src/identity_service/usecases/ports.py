"""What the identity use cases need from the outside world, as Protocols.

Real implementations: repo/*.py (SQL) and adapters/*.py (Argon2, Ed25519).
Test implementations: tests/unit/fakes.py (in-memory).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from identity_service.domain.models import Credentials, RefreshToken, Session, User


class UserRepo(Protocol):
    async def insert_user(self, user: User, password_hash: str) -> bool:
        """Create the user and their credentials. Returns False (and writes nothing) if the email is taken.
        Must be race-safe: two concurrent sign-ups with one email create exactly one user."""
        ...

    async def get_by_email(self, email: str) -> tuple[User, Credentials] | None: ...
    async def get_by_id(self, user_id: UUID) -> User | None: ...

    async def register_failed_sign_in(
        self, user_id: UUID, now: datetime, max_attempts: int, lock_until: datetime
    ) -> tuple[int, datetime | None]:
        """Atomically count one more wrong password; lock the account once `max_attempts` is reached.
        Returns (failed_attempts, locked_until) after the update."""
        ...

    async def reset_failed_sign_ins(self, user_id: UUID) -> None: ...
    async def update_password_hash(self, user_id: UUID, password_hash: str, now: datetime) -> None: ...


class SessionRepo(Protocol):
    async def create_session(self, session: Session, ip: str | None, user_agent: str | None) -> None: ...
    async def get_session(self, session_id: UUID) -> Session | None: ...
    async def touch_session(self, session_id: UUID, now: datetime, idle_expires_at: datetime) -> None: ...
    async def revoke_session(self, session_id: UUID, now: datetime) -> None: ...
    async def revoke_all_sessions(self, user_id: UUID, now: datetime) -> None: ...
    async def insert_refresh_token(self, token: RefreshToken) -> None: ...

    async def claim_refresh_token(self, token_hash: bytes, now: datetime) -> RefreshToken | None:
        """Mark the token used and return it, ONLY if it was still unused (one atomic statement).
        Two concurrent refreshes with the same token: exactly one gets it."""
        ...

    async def get_refresh_token(self, token_hash: bytes) -> RefreshToken | None: ...


class KeyRepo(Protocol):
    async def list_published(self) -> list[dict[str, Any]]:
        """Public JWKs that verifiers must accept: the active key and keys still being retired."""
        ...

    async def publish_active(
        self, kid: str, public_jwk: dict[str, Any], key_ref: str, now: datetime, retire_after: datetime
    ) -> None:
        """Make `kid` the one active key. A previously active key becomes 'retiring' until `retire_after`."""
        ...


class PasswordHasher(Protocol):
    async def hash(self, password: str) -> str: ...
    async def verify(self, password_hash: str, password: str) -> bool: ...
    async def burn(self, password: str) -> None:
        """Spend the time of one verification without a real hash, so 'no such user' takes as long as
        'wrong password' (no timing oracle)."""
        ...

    def needs_rehash(self, password_hash: str) -> bool:
        """True if the hash was made with weaker parameters than today's settings."""
        ...


class TokenIssuer(Protocol):
    kid: str
    public_jwk: dict[str, Any]
    key_ref: str

    def issue(self, user: User, session_id: UUID, now: datetime) -> tuple[str, int]:
        """Return (signed access token, lifetime in seconds)."""
        ...
