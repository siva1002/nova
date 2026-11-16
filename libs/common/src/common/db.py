"""Database plumbing: the connection pool, sessions, and the guard that makes forced row-level security work.

POOLING
  One AsyncEngine (= one connection pool) per service PROCESS, created at startup and disposed at shutdown.
  Never create an engine per request. Sizing: each uvicorn worker holds up to pool_size + max_overflow
  connections, so  workers x (pool_size + max_overflow)  must stay below PostgreSQL's max_connections
  (minus head-room for migrations and psql). Defaults: 10 + 5 per worker.
  `pool_pre_ping` replaces connections the server closed; `pool_recycle` retires old ones (30 min), which
  also plays well with PgBouncer in transaction mode later (plan/tech/02-data-and-cells.md).

THE TENANCY RULE
  Every transaction starts by setting `app.workspace_id` (and `app.user_id` when known). The database then
  shows only that workspace's rows (policies in tools/db-split/_epilogue.sql). With no workspace set,
  NOTHING is visible. `set_config(..., true)` is transaction-local, so a pooled connection can never leak
  one tenant into the next request.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine


def make_engine(database_url: str, *, pool_size: int = 10, max_overflow: int = 5) -> AsyncEngine:
    return create_async_engine(
        database_url,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=5,  # fail fast (503) instead of queueing requests behind an exhausted pool
        pool_pre_ping=True,
        pool_recycle=1800,
    )


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # expire_on_commit=False: objects stay readable after commit, so responses can be built after it.
    return async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def scoped_transaction(
    factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """ONE transaction: commits when the block ends normally, rolls back on any exception.

    workspace_id  scopes every query to that workspace through forced RLS. None = global tables only
                  (identity's users/sessions, access's `workspaces`); workspace tables then show no rows.
    user_id       exposed to policies as `app.user_id`. Used by the few "my own rows across workspaces"
                  policies, e.g. access's `member_self_read` behind GET /v1/me/workspaces.

    Repo functions use the yielded session and NEVER commit themselves. That is what guarantees that a
    change and its outbox event are saved together or not at all.
    """
    async with factory() as session, session.begin():
        if workspace_id is not None:
            await session.execute(text("SELECT set_config('app.workspace_id', :v, true)"), {"v": str(workspace_id)})
        if user_id is not None:
            await session.execute(text("SELECT set_config('app.user_id', :v, true)"), {"v": str(user_id)})
        yield session
