"""Alembic environment. Runs as the MIGRATOR login (owns the schema); the app login can never change schema.

Rules (docs/adr/0003): forward-only; expand then contract (add in one release, drop in a later one);
every new table gets workspace_id + forced RLS.
"""

import os

from alembic import context
from sqlalchemy import create_engine, pool

# Tests pass the URL through config.attributes; deployments use the MIGRATION_DATABASE_URL env var.
url = context.config.attributes.get("url") or os.environ["MIGRATION_DATABASE_URL"]
engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=None)
    with context.begin_transaction():
        context.run_migrations()
