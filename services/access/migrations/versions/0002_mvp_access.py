"""MVP additions to the access schema (tasks S1-08, S1-09)

1. workspaces.provision_status       'provisioning' until hierarchy has seeded the first space
2. workspace_members.email / display_name
                                     profile snapshot taken when the member joins, so the member list
                                     needs no call to identity (kept fresh from identity events, sprint 3)
3. policy member_self_read           lets a user read THEIR OWN membership rows across workspaces
                                     (GET /v1/me/workspaces). It is SELECT-only and matches on the user id
                                     the service sets per transaction (app.user_id); every other access to
                                     workspace_members still goes through the per-workspace policy.
4. two indexes                       member list paging, "is this email already a member"

Expand-only: new columns are nullable or have defaults, nothing is dropped. Safe while the service runs.
"""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE workspaces
          ADD COLUMN provision_status text NOT NULL DEFAULT 'active'
          CHECK (provision_status IN ('provisioning', 'active'))
        """
    )
    op.execute("ALTER TABLE workspace_members ADD COLUMN email text, ADD COLUMN display_name text")

    # The user of the current transaction, set by the service next to app.workspace_id.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION current_app_user() RETURNS uuid LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.user_id', true), '')::uuid $$
        """
    )
    # Policies on one table are OR-ed: a row is visible if it is in the current workspace
    # (workspace_isolation, from the baseline) OR it is the caller's own membership (this one).
    op.execute(
        """
        CREATE POLICY member_self_read ON workspace_members
          FOR SELECT USING (user_id = current_app_user())
        """
    )

    # Keyset paging of the member list: WHERE workspace_id = ? AND id > ? ORDER BY id
    op.execute(
        "CREATE INDEX workspace_members_ws_id_idx ON workspace_members (workspace_id, id) WHERE deleted_at IS NULL"
    )
    # "Is this email already a member?" when inviting
    op.execute(
        "CREATE INDEX workspace_members_ws_email_idx ON workspace_members (workspace_id, lower(email)) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    raise RuntimeError("Forward-only: write a new migration instead of downgrading.")
