"""Shared test fixtures for the whole repository (pytest loads this file for every test).

INTEGRATION TESTS RUN AGAINST A REAL POSTGRESQL, WITHOUT DOCKER
  Row-level security, ON CONFLICT, triggers and the migrations cannot be tested with fakes or SQLite.
  The server comes from, in this order:
    1. PG_TEST_URL   a superuser URL of any PostgreSQL 16 (CI uses a service container; you can point it
                     at the Compose database:  postgresql://postgres:<password>@localhost:5432/postgres)
    2. pgserver      a PostgreSQL 16 shipped as a pip package (dev dependency). Started once per test
                     run in a temp folder and removed afterwards. Nothing to install.

HOW A TEST GETS A DATABASE
  `make_db("identity")` returns a fresh, migrated, EMPTY database for that service:
    - roles are created exactly like deploy/postgres/init.sh does (migrator owns, app login is in app_user)
    - the service's real Alembic migrations run once into a template database
    - every test gets its own copy of the template (fast), dropped when the test ends
  Tests connect as the APP login, never as a superuser: superusers bypass row-level security, which
  would make every isolation test pass for the wrong reason.

Also here: `token_factory`, which signs access tokens for tests of services that only VERIFY tokens.
"""

from __future__ import annotations

import base64
import itertools
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.pool import NullPool

ROOT = Path(__file__).resolve().parent
TEST_PASSWORD = "test-only"
ISSUER = "work-platform"


# ----------------------------------------------------------------------------------------------- PostgreSQL
@pytest.fixture(scope="session")
def pg_admin_url() -> Iterator[URL]:
    """Superuser URL of the test server (psycopg driver). Used only to create roles and databases."""
    configured = os.environ.get("PG_TEST_URL")
    if configured:
        yield make_url(configured).set(drivername="postgresql+psycopg")
        return
    try:
        import pgserver
    except ImportError:  # pragma: no cover
        pytest.skip("No PostgreSQL for integration tests: set PG_TEST_URL or install the dev dependencies")
    data_dir = tempfile.mkdtemp(prefix="pgtest-")
    server = pgserver.get_server(data_dir, cleanup_mode="stop")
    try:
        yield make_url(server.get_uri()).set(drivername="postgresql+psycopg")
    finally:
        server.cleanup()
        shutil.rmtree(data_dir, ignore_errors=True)


def _admin(url: URL) -> Any:
    return create_engine(url, isolation_level="AUTOCOMMIT", poolclass=NullPool)


@dataclass(frozen=True)
class ServiceDb:
    name: str
    app_url: str  # what the service uses: asyncpg driver, app login, forced RLS applies
    migrator_url: str  # owner of the schema (psycopg driver)
    admin_url: URL  # superuser, for assertions that must see everything

    def admin_engine(self) -> Any:
        return create_engine(self.admin_url.set(database=self.name), poolclass=NullPool)

    def app_sync_engine(self) -> Any:
        """The APP login over the sync driver, for raw-SQL isolation assertions."""
        return create_engine(make_url(self.app_url).set(drivername="postgresql+psycopg"), poolclass=NullPool)


def _run_migrations(service: str, migrator_url: str) -> None:
    """Run the service's real Alembic migrations (the same files a deploy runs)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(ROOT / "services" / service / "migrations"))
    cfg.attributes["url"] = migrator_url  # read by migrations/env.py
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def _template_dbs(pg_admin_url: URL) -> Callable[[str], str]:
    """Build (once per service per test run) a migrated template database, and return its name."""
    built: dict[str, str] = {}
    engine = _admin(pg_admin_url)
    with engine.connect() as conn:
        # Same roles as deploy/postgres/init.sh. The baseline's epilogue grants to these.
        for role, attrs in (("app_user", "NOLOGIN"), ("app_worker", "NOLOGIN BYPASSRLS"), ("app_migrator", "NOLOGIN")):
            if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first():
                conn.execute(text(f"CREATE ROLE {role} {attrs}"))

    def build(service: str) -> str:
        if service in built:
            return built[service]
        template = f"tpl_{service}_{os.getpid()}"
        with engine.connect() as conn:
            for login, group in ((f"{service}_migrator", "app_migrator"), (f"{service}_app", "app_user")):
                if not conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": login}).first():
                    conn.execute(text(f"CREATE ROLE {login} LOGIN PASSWORD '{TEST_PASSWORD}' IN ROLE {group}"))
            conn.execute(text(f"DROP DATABASE IF EXISTS {template}"))
            conn.execute(text(f"CREATE DATABASE {template} OWNER {service}_migrator"))
        migrator = pg_admin_url.set(username=f"{service}_migrator", password=TEST_PASSWORD, database=template)
        _run_migrations(service, migrator.render_as_string(hide_password=False))
        built[service] = template
        return template

    return build


@pytest.fixture
def make_db(pg_admin_url: URL, _template_dbs: Callable[[str], str]) -> Iterator[Callable[[str], ServiceDb]]:
    """Factory fixture: `make_db("access")` -> a fresh migrated database for that service."""
    counter = itertools.count()
    created: list[str] = []
    engine = _admin(pg_admin_url)

    def make(service: str) -> ServiceDb:
        template = _template_dbs(service)
        name = f"t_{service}_{os.getpid()}_{int(time.time() * 1000) % 10_000_000}_{next(counter)}"
        with engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {name} TEMPLATE {template} OWNER {service}_migrator"))
        created.append(name)
        app = pg_admin_url.set(
            drivername="postgresql+asyncpg", username=f"{service}_app", password=TEST_PASSWORD, database=name
        )
        migrator = pg_admin_url.set(username=f"{service}_migrator", password=TEST_PASSWORD, database=name)
        return ServiceDb(
            name=name,
            app_url=app.render_as_string(hide_password=False),
            migrator_url=migrator.render_as_string(hide_password=False),
            admin_url=pg_admin_url,
        )

    yield make
    with engine.connect() as conn:
        for name in created:
            conn.execute(text(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)"))


# --------------------------------------------------------------------------------------------------- tokens
@dataclass(frozen=True)
class TokenFactory:
    """Signs access tokens the way identity does, for tests of services that only verify them."""

    private_key: Ed25519PrivateKey
    kid: str
    issuer: str

    @property
    def jwks(self) -> list[dict[str, Any]]:
        raw = self.private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        return [{"kty": "OKP", "crv": "Ed25519", "x": x, "kid": self.kid, "use": "sig", "alg": "EdDSA"}]

    def issue(self, user_id: UUID, email: str, name: str = "Test User", *, ttl: int = 900, **overrides: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": self.issuer,
            "sub": str(user_id),
            "email": email,
            "name": name,
            "iat": now,
            "exp": now + ttl,
            **overrides,
        }
        return jwt.encode(claims, self.private_key, algorithm="EdDSA", headers={"kid": self.kid})

    def headers(self, user_id: UUID, email: str, name: str = "Test User") -> dict[str, str]:
        return {"Authorization": f"Bearer {self.issue(user_id, email, name)}"}


@pytest.fixture(scope="session")
def token_factory() -> TokenFactory:
    return TokenFactory(Ed25519PrivateKey.generate(), kid="test-key-1", issuer=ISSUER)
