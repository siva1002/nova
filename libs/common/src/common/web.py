"""FastAPI wiring shared by every service. Used ONLY from each service's main.py and api/ layer.

  create_service_app(settings, title)   builds the app: JSON logging, request ids + access log, CORS,
                                        error handlers, /healthz, /readyz, and the long-lived resources
  get_claims / get_ctx                  FastAPI dependencies: verified token -> Claims / RequestContext
  transaction / global_transaction      `async with` block = ONE database transaction, outbox flushed
                                        before the commit
  client_ip(request)                    the caller's address behind our proxies (for rate limits)

LONG-LIVED RESOURCES (created once per process, closed on shutdown; never per request)
  app.state.engine / session_factory    the PostgreSQL connection pool (see common/db.py for sizing)
  app.state.http                        one pooled httpx.AsyncClient for calls to other services
                                        (keep-alive connections, 2 s timeout, fail closed)
  app.state.verifier                    the token verifier with its cached keys

WHY THE ROUTE OPENS THE TRANSACTION
  `async with transaction(...)` in the route makes the commit happen BEFORE the response is built, so a
  client never receives "201 Created" for something that then fails to commit. (A yield-dependency would
  commit after the response on some FastAPI versions.)
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import exc as sa_exc
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from common.auth import Claims, RemoteJwksVerifier, Verifier
from common.config import ServiceSettings
from common.context import RequestContext
from common.db import make_engine, make_session_factory, scoped_transaction
from common.errors import DependencyUnavailable, Unauthorized
from common.ids import new_id
from common.logging import configure_logging, request_id_var, user_id_var, workspace_id_var
from common.outbox import SqlOutbox
from common.problems import install_error_handlers, problem

log = logging.getLogger("common.web")
access_log = logging.getLogger("access")

# An incoming X-Request-Id is reused only if it looks harmless: it ends up in logs and response headers.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class RequestIdMiddleware:
    """Pure ASGI middleware (no BaseHTTPMiddleware: that one breaks contextvars and streaming).

    - takes X-Request-Id from the proxy (Envoy generates it) or creates one
    - exposes it as request.state.request_id and on every log line of this request
    - echoes it in the response header, so a user can quote it in a bug report
    - writes ONE access-log line per request: method, path (never the query string: it may carry
      tokens), status, duration
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _SAFE_REQUEST_ID.match(incoming) else str(new_id())
        scope.setdefault("state", {})["request_id"] = rid
        rid_token = request_id_var.set(rid)
        ws_token = workspace_id_var.set(None)
        user_token = user_id_var.set(None)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-Id"] = rid
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            if scope["path"] not in ("/healthz", "/readyz"):  # probes would drown the log
                access_log.info(
                    "%s %s -> %s in %.1f ms",
                    scope["method"],
                    scope["path"],
                    status,
                    (time.perf_counter() - started) * 1000,
                )
            request_id_var.reset(rid_token)
            workspace_id_var.reset(ws_token)
            user_id_var.reset(user_token)


def create_service_app(
    settings: ServiceSettings,
    title: str,
    *,
    verifier: Verifier | None = None,
    on_startup: Callable[[FastAPI], Awaitable[None]] | None = None,
) -> FastAPI:
    """Build a service's FastAPI app.

    verifier    override the token verifier (identity passes one backed by its own key table; tests pass
                static keys). Default: verify against settings.jwks_url.
    on_startup  optional async hook run once when the process starts serving (identity publishes its
                signing key there).
    """
    configure_logging(settings.service_name, settings.log_level)
    engine = make_engine(settings.database_url, pool_size=settings.db_pool_size, max_overflow=settings.db_max_overflow)
    if verifier is None:
        if not settings.jwks_url:
            raise RuntimeError("JWKS_URL is required: this service verifies tokens issued by identity")
        verifier = RemoteJwksVerifier(settings.jwks_url, settings.token_issuer)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # One pooled HTTP client for all calls to other services. A client per call would open a new
        # TCP connection each time and exhaust sockets under load.
        app.state.http = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.peer_timeout_seconds),
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
        try:
            if on_startup is not None:
                await on_startup(app)
            yield
        finally:
            await app.state.http.aclose()
            await engine.dispose()  # return every pooled connection to PostgreSQL

    app = FastAPI(title=title, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    app.state.verifier = verifier
    install_error_handlers(app)
    _install_database_error_handlers(app)

    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if origins:
        # Explicit origins only (never "*"): the refresh-token cookie needs allow_credentials.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match", "X-Request-Id"],
            expose_headers=["X-Request-Id", "Retry-After"],
            max_age=600,
        )
    app.add_middleware(RequestIdMiddleware)  # added last = outermost: wraps CORS and everything else

    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}  # liveness: the process is up. No dependencies checked on purpose

    @app.get("/readyz", include_in_schema=False)
    async def readyz() -> dict[str, str]:
        # Readiness: can we reach our database? A failing check takes the instance out of rotation.
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
        except Exception as exc:
            raise DependencyUnavailable("Database not reachable") from exc
        return {"status": "ready"}

    return app


def _install_database_error_handlers(app: FastAPI) -> None:
    """Pool exhausted or database unreachable -> 503 (retryable), not a generic 500."""

    async def _unavailable(request: Request, exc: Exception) -> JSONResponse:
        log.error("database unavailable: %s", type(exc).__name__)
        return problem(
            503,
            DependencyUnavailable.slug,
            DependencyUnavailable.code,
            DependencyUnavailable.title,
            "The database is temporarily unavailable",
            getattr(request.state, "request_id", None),
            retry_after_seconds=1,
        )

    for error in (sa_exc.TimeoutError, sa_exc.OperationalError, sa_exc.InterfaceError):
        app.add_exception_handler(error, _unavailable)


# --------------------------------------------------------------------------------------------- dependencies


async def get_claims(request: Request) -> Claims:
    """Dependency: a valid bearer token is required. Verification is local (cached public keys)."""
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized("Missing bearer token")
    verifier: Verifier = request.app.state.verifier
    claims = await verifier.verify(token.strip())
    request.state.bearer_token = token.strip()
    user_id_var.set(str(claims.user_id))
    return claims


async def get_ctx(request: Request, workspace_id: UUID, claims: Claims = Depends(get_claims)) -> RequestContext:
    """Dependency for /v1/w/{workspace_id}/... routes: who is asking, in which workspace.

    Being signed in does NOT mean being a member of this workspace. Each service checks that itself
    (access looks at its member table; the others ask access through PermissionClient).
    """
    workspace_id_var.set(str(workspace_id))
    return RequestContext(
        user_id=claims.user_id,
        workspace_id=workspace_id,
        request_id=request.state.request_id,
        bearer_token=request.state.bearer_token,
        email=claims.email,
        display_name=claims.name,
    )


def client_ip(request: Request) -> str:
    """Best-effort client address for rate limiting.

    Each trusted proxy APPENDS the address it saw to X-Forwarded-For, so with N trusted proxies the real
    client is the N-th entry from the right. Entries further left are supplied by the client and can be
    forged, so they are never used. With no header (local runs, tests) the socket peer is used.
    """
    hops: int = request.app.state.settings.trusted_proxy_hops
    forwarded = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    if hops > 0 and len(forwarded) >= hops:
        return forwarded[-hops]
    return request.client.host if request.client else "unknown"


# --------------------------------------------------------------------------------------------- transactions


@dataclass(frozen=True, slots=True)
class Tx:
    session: AsyncSession  # hand this to repo classes
    events: SqlOutbox  # hand this to use cases as their EventSink


@asynccontextmanager
async def transaction(request: Request, ctx: RequestContext) -> AsyncIterator[Tx]:
    """One transaction scoped to ctx.workspace_id (forced RLS) on behalf of ctx.user_id."""
    factory = request.app.state.session_factory
    async with scoped_transaction(factory, workspace_id=ctx.workspace_id, user_id=ctx.user_id) as session:
        outbox = SqlOutbox(session, workspace_id=ctx.workspace_id, actor_user_id=ctx.user_id)
        yield Tx(session=session, events=outbox)
        await outbox.flush()  # same transaction as the change; skipped if the block raised


@asynccontextmanager
async def global_transaction(
    request: Request, *, user_id: UUID | None = None, workspace_id: UUID | None = None
) -> AsyncIterator[Tx]:
    """One transaction for routes that are not under /v1/w/{workspace_id}:
    identity (global tables), POST /v1/workspaces (the workspace id comes from the body),
    POST /v1/invites/accept (it comes from the token), GET /v1/me/workspaces (user-scoped)."""
    factory = request.app.state.session_factory
    async with scoped_transaction(factory, workspace_id=workspace_id, user_id=user_id) as session:
        outbox = SqlOutbox(session, workspace_id=workspace_id, actor_user_id=user_id)
        yield Tx(session=session, events=outbox)
        await outbox.flush()
