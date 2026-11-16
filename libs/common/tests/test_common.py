"""Unit tests for libs/common. No database, no network."""

import json
import logging
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from common.errors import Forbidden, NotFound, TooManyRequests, VersionConflict
from common.ids import new_id
from common.logging import JsonFormatter
from common.problems import install_error_handlers
from common.web import client_ip


def test_new_id_is_uuid7_and_time_ordered():
    a, b = new_id(), new_id()
    assert isinstance(a, UUID) and a.version == 7
    assert a < b  # later ids sort after earlier ones (index-friendly)


class _Body(BaseModel):
    name: str


def _app() -> TestClient:
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/forbidden")
    async def forbidden() -> None:
        raise Forbidden()

    @app.get("/missing")
    async def missing() -> None:
        raise NotFound("No such task")

    @app.get("/conflict")
    async def conflict() -> None:
        raise VersionConflict(current_version=7)

    @app.get("/slow-down")
    async def slow_down() -> None:
        raise TooManyRequests(retry_after_seconds=30)

    @app.post("/validate")
    async def validate(body: _Body) -> None:
        return None

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    return TestClient(app, raise_server_exceptions=False)


def test_domain_errors_become_problem_responses_in_the_contract_shape():
    c = _app()
    r = c.get("/forbidden", headers={"x-request-id": "req-1"})
    assert r.status_code == 403
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    # contracts/openapi/common.yaml Problem: type, title, status, code are required
    assert body["type"].endswith("/forbidden") and body["status"] == 403 and body["title"]
    assert body["code"] == "common.forbidden" and body["traceId"] == "req-1"

    assert c.get("/missing").json()["detail"] == "No such task"
    conflict = c.get("/conflict")
    assert conflict.status_code == 409 and conflict.json()["current_version"] == 7
    assert conflict.json()["code"] == "common.version_conflict"


def test_rate_limit_problem_sets_the_retry_after_header():
    r = _app().get("/slow-down")
    assert r.status_code == 429 and r.headers["retry-after"] == "30"


def test_validation_errors_name_the_field_but_never_echo_the_input():
    r = _app().post("/validate", json={"name": {"secret": "hunter2"}})
    assert r.status_code == 422 and r.json()["code"] == "common.validation_failed"
    assert r.json()["errors"][0]["field"] == "name"
    assert "hunter2" not in r.text


def test_unexpected_errors_do_not_leak_details():
    r = _app().get("/boom")
    assert r.status_code == 500 and r.json()["code"] == "common.internal_error"
    assert "secret detail" not in r.text


def test_json_log_line_has_required_fields():
    rec = logging.LogRecord("x", logging.INFO, __file__, 1, "hello %s", ("world",), None)
    line = json.loads(JsonFormatter("time").format(rec))
    assert line["msg"] == "hello world" and line["service"] == "time"
    assert {"request_id", "workspace_id", "user_id", "ts", "level"} <= line.keys()


def _request(forwarded: str | None, hops: int, peer: str = "10.0.0.9"):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    settings = SimpleNamespace(trusted_proxy_hops=hops)
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=peer),
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
    )


def test_client_ip_trusts_only_what_our_own_proxies_appended():
    # one trusted proxy: the LAST entry is what it saw; earlier entries are client-supplied and ignored
    assert client_ip(_request("6.6.6.6, 203.0.113.7", hops=1)) == "203.0.113.7"
    # two trusted proxies (Caddy -> Envoy): second from the right
    assert client_ip(_request("6.6.6.6, 203.0.113.7, 10.0.0.2", hops=2)) == "203.0.113.7"
    # no header, or fewer entries than proxies, or proxies not trusted: the socket peer
    assert client_ip(_request(None, hops=1)) == "10.0.0.9"
    assert client_ip(_request("203.0.113.7", hops=2)) == "10.0.0.9"
    assert client_ip(_request("6.6.6.6", hops=0)) == "10.0.0.9"
