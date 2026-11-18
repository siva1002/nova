"""Migration helpers shared by every service.

Usage in an Alembic migration:

    from common.migrations import add_rls, grant_table

    def upgrade() -> None:
        op.create_table("my_table", ...)
        add_rls("my_table")          # workspace_id-based isolation
        grant_table("my_table")      # SELECT/INSERT/UPDATE/DELETE to app_user, app_worker
"""

from __future__ import annotations

from alembic import op


def add_rls(table: str) -> None:
    """Enable forced RLS on a table with a NOT NULL workspace_id column.

    Creates the standard workspace_isolation policy used by every tenant table.
    Call this after op.create_table() for any table that has workspace_id.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY workspace_isolation ON {table} "
        f"USING (workspace_id = current_workspace()) "
        f"WITH CHECK (workspace_id = current_workspace())"
    )


def grant_table(table: str) -> None:
    """Grant SELECT/INSERT/UPDATE/DELETE on a new table to the app roles.

    The baseline grants on all tables that existed at migration 0001. Any table
    added in a later migration needs its own explicit grant.
    """
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_user, app_worker")


def add_rls_exempt(table: str) -> None:
    """Enable RLS on a global table that is filtered by user_id, not workspace_id.

    Use this for tables marked 'rls:exempt global, filtered by user' (e.g. user_workspaces).
    You must create the policy yourself since the filter column varies.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
