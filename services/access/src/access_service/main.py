"""Entry point of the access service. WIRING ONLY: builds the long-lived objects and connects them.

Run:  uvicorn access_service.main:create_app --factory --host 0.0.0.0 --port 8000

Tokens are verified locally against identity's public keys (JWKS_URL), fetched once and cached.
The only other service access calls is hierarchy (seed the first space); that client is created at
startup on top of the shared pooled HTTP client.
"""

from __future__ import annotations

from fastapi import FastAPI

from access_service.api.routes import Deps, router
from access_service.clients.hierarchy_client import HttpHierarchyClient
from access_service.settings import Settings
from common.auth import Verifier
from common.clock import SystemClock
from common.web import create_service_app


def create_app(settings: Settings | None = None, *, verifier: Verifier | None = None) -> FastAPI:
    """`settings` and `verifier` are injectable for tests; production reads the environment and
    verifies against JWKS_URL."""
    settings = settings or Settings()
    deps = Deps(settings=settings, clock=SystemClock())

    async def connect_clients(app: FastAPI) -> None:
        if settings.hierarchy_url:
            deps.hierarchy = HttpHierarchyClient(settings.hierarchy_url, app.state.http)

    app = create_service_app(settings, "Access service", verifier=verifier, on_startup=connect_clients)
    app.state.deps = deps
    app.include_router(router)
    return app
