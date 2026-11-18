"""Alembic environment. Runs as the MIGRATOR login (owns the schema); the app login can never change schema.

Rules (docs/adr/0003): forward-only; expand then contract (add in one release, drop in a later one);
every new table gets workspace_id + forced RLS.
"""

import os
from pathlib import Path
from logging.config import fileConfig

from alembic import op
from alembic import context
from alembic.autogenerate import rewriter
from alembic.operations import ops
from sqlalchemy import create_engine, pool
from dotenv import load_dotenv

from identity_service.repo.models import metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

load_dotenv(Path(__file__).parents[1] / ".env")

url = context.config.attributes.get(
    "url") or os.environ["MIGRATION_DATABASE_URL"]


def _has_workspace_id(create_table_op: ops.CreateTableOp) -> bool:
    return any(col.key == "workspace_id" for col in create_table_op.columns)


_CREATE_WORKSPACE_FN = """
    CREATE OR REPLACE FUNCTION current_workspace() RETURNS uuid LANGUAGE sql STABLE AS
    $$ SELECT current_setting('app.workspace_id', true)::uuid $$
"""


def process_revision_directives(context, revision, directives):
    """Append grant_table + add_rls after every CreateTableOp that has workspace_id.
    On the first migration (down_revision is None) also create current_workspace().
    """
    for directive in directives:
        is_first = directive.down_revision is None
        if is_first:
            directive.upgrade_ops.ops.insert(0, ops.ExecuteSQLOp(_CREATE_WORKSPACE_FN))

        for upgrade_op in list(directive.upgrade_ops.ops):
            if isinstance(upgrade_op, ops.CreateTableOp) and _has_workspace_id(upgrade_op):
                table = upgrade_op.table_name
                directive.upgrade_ops.ops += [
                    ops.ExecuteSQLOp(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO app_user, app_worker"),
                    ops.ExecuteSQLOp(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"),
                    ops.ExecuteSQLOp(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY"),
                    ops.ExecuteSQLOp(
                        f"CREATE POLICY workspace_isolation ON {table} "
                        f"USING (workspace_id = current_workspace()) "
                        f"WITH CHECK (workspace_id = current_workspace())"
                    ),
                ]


def run_migrations_online() -> None:
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=metadata,
            process_revision_directives=process_revision_directives,
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
