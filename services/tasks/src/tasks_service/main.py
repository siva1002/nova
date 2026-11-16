"""Entry point. Wiring only: no business logic here.  Run: uvicorn tasks_service.main:create_app --factory"""

from fastapi import FastAPI

from common.web import create_service_app
from tasks_service.api.routes import router
from tasks_service.settings import Settings


def create_app() -> FastAPI:
    app = create_service_app(Settings(), "Tasks service")
    app.include_router(router)
    return app
