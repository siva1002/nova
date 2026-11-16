"""Fixtures for identity integration tests (helpers live in identity_support.py).
The database is a fresh, migrated copy per test (see the repo-root conftest.py)."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # makes `import identity_support` work from the tests

from identity_support import Env, Running, running


@pytest.fixture
def identity_env(make_db) -> Env:
    return Env(make_db("identity"))


@pytest.fixture
async def identity(identity_env: Env) -> AsyncIterator[Running]:
    async with running(identity_env) as r:
        yield r
