"""Smoke test: the app is built from valid settings and answers /healthz with no dependency at all.
(The lifespan is deliberately NOT entered here: identity's startup publishes its signing key, which
needs the database. That path is covered by tests/integration.)"""

from fastapi.testclient import TestClient

from identity_service.main import create_app
from identity_service.settings import Settings


def test_healthz_and_request_id():
    settings = Settings(service_name="identity", database_url="postgresql+asyncpg://x:x@localhost:5432/identity")
    client = TestClient(create_app(settings))
    r = client.get("/healthz", headers={"X-Request-Id": "abc-123"})
    assert r.status_code == 200 and r.json() == {"status": "ok"}
    assert r.headers["x-request-id"] == "abc-123"  # a safe incoming id is echoed
    r = client.get("/healthz", headers={"X-Request-Id": "bad id	with spaces"})
    assert r.headers["x-request-id"] != "bad id	with spaces"  # an unsafe one is replaced


def test_production_refuses_to_start_without_a_signing_key():
    import pytest

    settings = Settings(
        service_name="identity", environment="production", database_url="postgresql+asyncpg://x:x@localhost/identity"
    )
    with pytest.raises(RuntimeError, match="SIGNING_PRIVATE_KEY"):
        create_app(settings)
