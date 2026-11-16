"""Smoke test: the app boots with valid settings and answers /healthz without any dependency."""

from fastapi.testclient import TestClient

from tasks_service.main import create_app


def test_healthz(monkeypatch):
    monkeypatch.setenv("SERVICE_NAME", "tasks")
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://x:x@localhost:5432/tasks")
    monkeypatch.setenv("JWKS_URL", "http://localhost:9/jwks.json")
    with TestClient(create_app()) as client:
        r = client.get("/healthz")
        assert r.status_code == 200 and r.json() == {"status": "ok"}
        assert r.headers["x-request-id"]
