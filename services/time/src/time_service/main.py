"""Entry point of the time service. WIRING ONLY.  Run: uvicorn time_service.main:create_app --factory"""

from __future__ import annotations

from fastapi import FastAPI

from common.auth import Verifier
from common.permissions import PermissionClient
from common.web import create_service_app
from time_service.api.routes import router
from time_service.clients.tasks_client import HttpTasksClient
from time_service.settings import Settings


def create_app(settings: Settings | None = None, *, verifier: Verifier | None = None) -> FastAPI:
    settings = settings or Settings()

    async def connect_clients(app: FastAPI) -> None:
        # The two other services this one may call (see README "Calls"), both on the shared pooled
        # HTTP client created by common.web. Everything else is forbidden by design.
        app.state.perms = PermissionClient(settings.access_url, app.state.http)
        app.state.tasks = HttpTasksClient(settings.tasks_url, app.state.http)

    app = create_service_app(settings, "Time service", verifier=verifier, on_startup=connect_clients)
    app.include_router(router)
    return app
