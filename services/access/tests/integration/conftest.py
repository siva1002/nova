"""Fixtures for access integration tests (helpers live in access_support.py).
The database is a fresh, migrated copy per test (see the repo-root conftest.py)."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # makes `import access_support` work from the tests

from access_support import Running, running


@pytest.fixture
async def access(make_db, token_factory) -> AsyncIterator[Running]:
    async with running(make_db("access"), token_factory) as r:
        yield r
