"""Fixtures for identity unit tests: one set of in-memory fakes per test (see identity_fakes.py)."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # makes `import identity_fakes` work from the tests

from identity_fakes import (
    GOOD_PASSWORD,
    POLICY,
    FakeClock,
    FakeEvents,
    FakeHasher,
    FakeSessions,
    FakeTokens,
    FakeUsers,
    SecretSequence,
)

from identity_service.domain.models import IssuedTokens, SignUp
from identity_service.usecases.refresh_session import refresh_session
from identity_service.usecases.sign_in import Denied, sign_in
from identity_service.usecases.sign_up import sign_up


@dataclass
class World:
    """Everything a use case needs, wired with fakes, plus shortcuts for the common steps."""

    users: FakeUsers
    sessions: FakeSessions
    hasher: FakeHasher
    tokens: FakeTokens
    events: FakeEvents
    clock: FakeClock
    secrets: SecretSequence

    async def sign_up(
        self, email: str = "asha@example.com", password: str = GOOD_PASSWORD, name: str = "Asha Rao"
    ) -> None:
        await sign_up(
            SignUp(email, password, name), users=self.users, hasher=self.hasher, events=self.events, clock=self.clock
        )

    async def sign_in(self, email: str = "asha@example.com", password: str = GOOD_PASSWORD) -> IssuedTokens | Denied:
        return await sign_in(
            email,
            password,
            users=self.users,
            sessions=self.sessions,
            hasher=self.hasher,
            tokens=self.tokens,
            clock=self.clock,
            policy=POLICY,
            new_secret=self.secrets,
        )

    async def refresh(self, raw: str | None) -> IssuedTokens | Denied:
        return await refresh_session(
            raw,
            users=self.users,
            sessions=self.sessions,
            tokens=self.tokens,
            clock=self.clock,
            policy=POLICY,
            new_secret=self.secrets,
        )


@pytest.fixture
def world() -> World:
    return World(FakeUsers(), FakeSessions(), FakeHasher(), FakeTokens(), FakeEvents(), FakeClock(), SecretSequence())
