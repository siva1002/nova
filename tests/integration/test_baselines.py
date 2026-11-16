"""Every service's migrations run on a REAL, empty PostgreSQL, and tenant isolation is switched on.

For each of the 5 services (seed of task S1-25):
  - `alembic upgrade head` succeeds as the migrator login (baseline + later migrations)
  - every table that carries a NOT NULL workspace_id has row-level security FORCED
  - the app login can connect and is NOT able to bypass row-level security
  - the outbox table exists

Run:  uv run pytest -m integration tests/integration
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

SERVICES = ["identity", "access", "hierarchy", "tasks", "time"]

pytestmark = pytest.mark.integration

_UNPROTECTED = text(
    """
    SELECT c.relname FROM pg_class c
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'workspace_id' AND NOT a.attisdropped
    WHERE c.relkind IN ('r','p') AND NOT c.relispartition AND a.attnotnull
      AND c.relnamespace = 'public'::regnamespace
      AND c.relname NOT IN ('outbox','inbox')
      AND coalesce(obj_description(c.oid,'pg_class'),'') NOT LIKE 'rls:exempt%'
      AND NOT c.relforcerowsecurity
    """
)


@pytest.mark.parametrize("service", SERVICES)
def test_migrations_run_and_rls_is_forced(make_db, service):
    db = make_db(service)  # runs the real Alembic migrations of that service

    with db.admin_engine().connect() as conn:
        unprotected = conn.execute(_UNPROTECTED).scalars().all()
        assert unprotected == [], f"{service}: tables with workspace_id but no forced RLS: {unprotected}"
        assert conn.execute(text("SELECT count(*) FROM outbox")).scalar() == 0  # from the prelude
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert head is not None

    with db.app_sync_engine().connect() as conn:
        # The login the service runs as must be an ordinary role: a superuser or BYPASSRLS role would
        # silently ignore every isolation policy.
        row = conn.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user")).one()
        assert (row.rolsuper, row.rolbypassrls) == (False, False)
