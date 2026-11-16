"""Entry point. Wiring only: no business logic here.  Run: uvicorn hierarchy_service.main:create_app --factory"""

from fastapi import FastAPI

from common.web import create_service_app
from hierarchy_service.api.routes import router
from hierarchy_service.settings import Settings


def create_app() -> FastAPI:
    app = create_service_app(Settings(), "Hierarchy service")
    app.include_router(router)
    return app
