"""SQLAlchemy Core table definitions for the identity service.

These mirror the schema in migrations/sql/0001_baseline.sql and migration 0002.
Used for autogenerate support and as a single source of truth for column names.
No ORM mappers — repos use raw SQL via session.execute(text(...)).
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import BYTEA, INET, JSONB, UUID

metadata = sa.MetaData()

users = sa.Table(
    "users",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("email", sa.Text, nullable=False),
    sa.Column("username", sa.Text, nullable=False),
    sa.Column("display_name", sa.Text),
    sa.Column("initials", sa.Text),
    sa.Column("color", sa.Text),
    sa.Column("avatar_url", sa.Text),
    sa.Column("timezone", sa.Text),
    sa.Column("locale", sa.Text),
    sa.Column("email_verified_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("default_workspace_id", UUID),
    sa.Column("status", sa.Text, nullable=False, server_default="active"),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("deleted_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("anonymized_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("version", sa.Integer, nullable=False, server_default="1"),
)

user_credentials = sa.Table(
    "user_credentials",
    metadata,
    sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("password_hash", sa.Text),
    sa.Column("password_changed_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("breached_checked_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("failed_attempts", sa.SmallInteger, nullable=False, server_default="0"),
    sa.Column("locked_until", sa.TIMESTAMP(timezone=True)),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
)

user_sessions = sa.Table(
    "user_sessions",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("device_label", sa.Text),
    sa.Column("ip", INET),
    sa.Column("user_agent", sa.Text),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("last_seen_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("idle_expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("absolute_expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("revoked_at", sa.TIMESTAMP(timezone=True)),
)

refresh_tokens = sa.Table(
    "refresh_tokens",
    metadata,
    sa.Column("token_hash", BYTEA, primary_key=True),
    sa.Column("session_id", UUID, sa.ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False),
    sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("used_at", sa.TIMESTAMP(timezone=True)),
)

auth_tokens = sa.Table(
    "auth_tokens",
    metadata,
    sa.Column("token_hash", BYTEA, primary_key=True),
    sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("used_at", sa.TIMESTAMP(timezone=True)),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
)

user_workspaces = sa.Table(
    "user_workspaces",
    metadata,
    sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("workspace_id", UUID, nullable=False),
    sa.Column("cell_id", sa.Text, nullable=False),
    sa.Column("workspace_name", sa.Text, nullable=False),
    sa.Column("role_kind", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("source_version", sa.Integer, nullable=False),
    sa.Column("updated_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.PrimaryKeyConstraint("user_id", "workspace_id"),
)

signing_keys = sa.Table(
    "signing_keys",
    metadata,
    sa.Column("kid", sa.Text, primary_key=True),
    sa.Column("algorithm", sa.Text, nullable=False, server_default="EdDSA"),
    sa.Column("public_jwk", JSONB, nullable=False),
    sa.Column("kms_key_ref", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("retire_after", sa.TIMESTAMP(timezone=True)),
)

data_subject_requests = sa.Table(
    "data_subject_requests",
    metadata,
    sa.Column("id", UUID, primary_key=True),
    sa.Column("workspace_id", UUID),
    sa.Column("user_id", UUID, sa.ForeignKey("users.id"), nullable=False),
    sa.Column("kind", sa.Text, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default="open"),
    sa.Column("due_at", sa.TIMESTAMP(timezone=True), nullable=False),
    sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    sa.Column("completed_at", sa.TIMESTAMP(timezone=True)),
)

