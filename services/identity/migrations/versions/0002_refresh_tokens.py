"""refresh tokens: single-use, rotated on every refresh, reuse ends the session (task S1-07)

The baseline has user_sessions but nowhere to keep refresh tokens. Each row is ONE token; `used_at` is
set when it is traded in. A second use of the same token is treated as theft
(see usecases/refresh_session.py).

Expand-only migration: adds a table, touches nothing existing. Safe to run while the service is up.
"""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE refresh_tokens (
          token_hash  bytea PRIMARY KEY,                -- SHA-256 of the token; the token itself is never stored
          session_id  uuid NOT NULL REFERENCES user_sessions(id) ON DELETE CASCADE,
          user_id     uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          created_at  timestamptz NOT NULL DEFAULT now(),
          expires_at  timestamptz NOT NULL,
          used_at     timestamptz                       -- set once, when rotated
        )
        """
    )
    # "all tokens of a session" (clean-up, investigations)
    op.execute("CREATE INDEX refresh_tokens_session_idx ON refresh_tokens (session_id)")
    # clean-up job: delete rows long past expiry (job arrives with the worker in sprint 2)
    op.execute("CREATE INDEX refresh_tokens_expires_idx ON refresh_tokens (expires_at)")
    # Global table like users: no workspace_id, so no row-level security. Queries always filter by hash.
    op.execute("COMMENT ON TABLE refresh_tokens IS 'rls:exempt global, looked up by token hash'")
    # The baseline granted on the tables that existed then; a new table needs its own grant.
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON refresh_tokens TO app_user, app_worker")


def downgrade() -> None:
    raise RuntimeError("Forward-only: write a new migration instead of downgrading.")
