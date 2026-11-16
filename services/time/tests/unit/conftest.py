"""Fixtures for time unit tests: fresh in-memory fakes per test (see time_fakes.py)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))  # makes `import time_fakes` work from the tests

from time_fakes import FakeEvents, FakeRepo


@pytest.fixture
def repo() -> FakeRepo:
    return FakeRepo()


@pytest.fixture
def events() -> FakeEvents:
    return FakeEvents()
