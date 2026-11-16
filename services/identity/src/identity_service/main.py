"""Entry point of the identity service. WIRING ONLY: builds the long-lived objects and connects them.

Run:  uvicorn identity_service.main:create_app --factory --host 0.0.0.0 --port 8000

Startup order
  1. settings are read and validated (missing env var = the process refuses to start)
  2. the signing key is loaded (required outside local development)
  3. the app is built: connection pool, error handlers, request ids (common.web.create_service_app)
  4. on startup: our public key is published to the signing_keys table, so /.well-known/jwks.json and
     every other service can verify the tokens we are about to issue
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from common.auth import KeySetVerifier
from common.clock import SystemClock
from common.db import scoped_transaction
from common.web import create_service_app
from identity_service.adapters.password_hasher import Argon2Hasher
from identity_service.adapters.rate_limiter import InMemoryRateLimiter
from identity_service.adapters.token_signer import Ed25519Signer
from identity_service.api.routes import Deps, router
from identity_service.domain.models import SessionPolicy
from identity_service.repo.key_repo import SqlKeyRepo
from identity_service.settings import Settings
from identity_service.usecases.signing_keys import publish_signing_key


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()  # tests pass explicit settings; production reads the environment
    clock = SystemClock()
    signer = Ed25519Signer.from_settings(
        settings.signing_private_key,
        environment=settings.environment,
        issuer=settings.token_issuer,
        ttl_seconds=settings.access_token_ttl_seconds,
    )
    deps = Deps(
        settings=settings,
        hasher=Argon2Hasher(
            time_cost=settings.argon2_time_cost,
            memory_kib=settings.argon2_memory_kib,
            parallelism=settings.argon2_parallelism,
            max_concurrency=settings.hash_concurrency,
        ),
        signer=signer,
        limiter=InMemoryRateLimiter(settings.ip_rate_limit, settings.ip_rate_window_seconds),
        policy=SessionPolicy(
            refresh_idle_seconds=settings.refresh_idle_days * 86_400,
            session_absolute_seconds=settings.session_absolute_days * 86_400,
            max_failed_sign_ins=settings.max_failed_sign_ins,
            lockout_seconds=settings.lockout_minutes * 60,
        ),
        clock=clock,
    )

    # identity verifies its OWN tokens (GET /v1/me, sign-out) against its own key table, not over HTTP.
    # The loader runs at most once a minute (KeySetVerifier caches), and accepts retiring keys too.
    async def load_public_keys() -> list[dict[str, Any]]:
        async with scoped_transaction(app.state.session_factory) as session:
            return await SqlKeyRepo(session).list_published()

    async def publish_key(app: FastAPI) -> None:
        async with scoped_transaction(app.state.session_factory) as session:
            await publish_signing_key(
                keys=SqlKeyRepo(session),
                tokens=signer,
                clock=clock,
                token_ttl_seconds=settings.access_token_ttl_seconds,
            )

    app = create_service_app(
        settings,
        "Identity service",
        verifier=KeySetVerifier(load_public_keys, settings.token_issuer),
        on_startup=publish_key,
    )
    app.state.deps = deps
    app.include_router(router)
    return app
