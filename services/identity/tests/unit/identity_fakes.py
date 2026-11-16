"""In-memory fakes for the identity use cases. No database, no HTTP, no real clock, no real Argon2.

Fakes instead of mock libraries: each one is a tiny working implementation of a port
(usecases/ports.py), so tests read like the real thing and survive refactors.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from identity_service.domain.models import Credentials, RefreshToken, Session, SessionPolicy, User

T0 = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
POLICY = SessionPolicy(
    refresh_idle_seconds=30 * 86_400, session_absolute_seconds=90 * 86_400, max_failed_sign_ins=3, lockout_seconds=900
)
GOOD_PASSWORD = "correct horse battery"


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


class FakeHasher:
    """Reversible 'hash' so tests stay fast. Counts work, to prove timing equalisation happens."""

    def __init__(self) -> None:
        self.verifications = 0
        self.hashes = 0
        self.outdated: set[str] = set()

    async def hash(self, password: str) -> str:
        self.hashes += 1
        return f"hashed:{password}"

    async def verify(self, password_hash: str, password: str) -> bool:
        self.verifications += 1
        return password_hash in (f"hashed:{password}", f"old:{password}")

    async def burn(self, password: str) -> None:
        self.verifications += 1

    def needs_rehash(self, password_hash: str) -> bool:
        return password_hash.startswith("old:")


class FakeTokens:
    kid = "fake-kid"
    public_jwk: dict[str, Any] = {"kty": "OKP", "crv": "Ed25519", "x": "AAAA", "kid": "fake-kid"}  # noqa: RUF012
    key_ref = "fake:key"

    def issue(self, user: User, session_id: UUID, now: datetime) -> tuple[str, int]:
        return f"access.{user.id}.{session_id}.{int(now.timestamp())}", 900


class SecretSequence:
    """Deterministic 'random' refresh tokens: secret-1, secret-2, ..."""

    def __init__(self) -> None:
        self.n = 0

    def __call__(self) -> str:
        self.n += 1
        return f"secret-{self.n}"


class FakeUsers:
    def __init__(self) -> None:
        self.users: dict[UUID, User] = {}
        self.creds: dict[UUID, Credentials] = {}

    async def insert_user(self, user: User, password_hash: str) -> bool:
        if any(u.email == user.email for u in self.users.values()):
            return False
        self.users[user.id] = user
        self.creds[user.id] = Credentials(user.id, password_hash, 0, None)
        return True

    async def get_by_email(self, email: str) -> tuple[User, Credentials] | None:
        for user in self.users.values():
            if user.email == email:
                return user, self.creds[user.id]
        return None

    async def get_by_id(self, user_id: UUID) -> User | None:
        return self.users.get(user_id)

    async def register_failed_sign_in(
        self, user_id: UUID, now: datetime, max_attempts: int, lock_until: datetime
    ) -> tuple[int, datetime | None]:
        cred = self.creds[user_id]
        expired = cred.locked_until is not None and cred.locked_until <= now
        attempts = 1 if expired else cred.failed_attempts + 1
        locked = lock_until if attempts >= max_attempts else None
        self.creds[user_id] = replace(cred, failed_attempts=attempts, locked_until=locked)
        return attempts, locked

    async def reset_failed_sign_ins(self, user_id: UUID) -> None:
        self.creds[user_id] = replace(self.creds[user_id], failed_attempts=0, locked_until=None)

    async def update_password_hash(self, user_id: UUID, password_hash: str, now: datetime) -> None:
        self.creds[user_id] = replace(self.creds[user_id], password_hash=password_hash)

    # test helpers
    def set_status(self, user_id: UUID, status: str) -> None:
        self.users[user_id] = replace(self.users[user_id], status=status)


class FakeSessions:
    def __init__(self) -> None:
        self.sessions: dict[UUID, Session] = {}
        self.tokens: dict[bytes, RefreshToken] = {}

    async def create_session(self, session: Session, ip: str | None, user_agent: str | None) -> None:
        self.sessions[session.id] = session

    async def get_session(self, session_id: UUID) -> Session | None:
        return self.sessions.get(session_id)

    async def touch_session(self, session_id: UUID, now: datetime, idle_expires_at: datetime) -> None:
        self.sessions[session_id] = replace(self.sessions[session_id], idle_expires_at=idle_expires_at)

    async def revoke_session(self, session_id: UUID, now: datetime) -> None:
        session = self.sessions[session_id]
        if session.revoked_at is None:
            self.sessions[session_id] = replace(session, revoked_at=now)

    async def revoke_all_sessions(self, user_id: UUID, now: datetime) -> None:
        for sid, session in self.sessions.items():
            if session.user_id == user_id and session.revoked_at is None:
                self.sessions[sid] = replace(session, revoked_at=now)

    async def insert_refresh_token(self, token: RefreshToken) -> None:
        self.tokens[token.token_hash] = token

    async def claim_refresh_token(self, token_hash: bytes, now: datetime) -> RefreshToken | None:
        token = self.tokens.get(token_hash)
        if token is None or token.used_at is not None:
            return None
        self.tokens[token_hash] = replace(token, used_at=now)
        return self.tokens[token_hash]

    async def get_refresh_token(self, token_hash: bytes) -> RefreshToken | None:
        return self.tokens.get(token_hash)


class FakeKeys:
    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    async def list_published(self) -> list[dict[str, Any]]:
        return [r["jwk"] for r in self.rows.values() if r["status"] in ("active", "retiring")]

    async def publish_active(
        self, kid: str, public_jwk: dict[str, Any], key_ref: str, now: datetime, retire_after: datetime
    ) -> None:
        for other_kid, row in self.rows.items():
            if row["status"] == "active" and other_kid != kid:
                row["status"] = "retiring"
        self.rows[kid] = {"jwk": public_jwk, "status": "active"}
