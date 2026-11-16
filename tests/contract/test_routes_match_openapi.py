"""Every HTTP route a service implements is declared in its OpenAPI contract, with the same method, path
and success status. (The reverse is not required yet: contracts describe the whole product, the code
implements the sprint-1 part. Full conformance, including response bodies, is task S1-23.)

Catches: a route added without touching the contract, a typo in a path, a status code that drifted.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi import FastAPI

from access_service.main import create_app as create_access
from access_service.settings import Settings as AccessSettings
from identity_service.main import create_app as create_identity
from identity_service.settings import Settings as IdentitySettings

OPENAPI = Path(__file__).resolve().parents[2] / "contracts" / "openapi"
DB = "postgresql+asyncpg://x:x@localhost:5432/unused"  # never connected: we only inspect the route table


def _identity() -> FastAPI:
    return create_identity(IdentitySettings(service_name="identity", database_url=DB))


def _access() -> FastAPI:
    return create_access(AccessSettings(service_name="access", database_url=DB, jwks_url="http://unused/jwks.json"))


def _declared(*contracts: str) -> dict[tuple[str, str], dict[str, Any]]:
    declared: dict[tuple[str, str], dict[str, Any]] = {}
    for name in contracts:
        spec = yaml.safe_load((OPENAPI / name).read_text(encoding="utf-8"))
        for path, item in spec["paths"].items():
            for method, operation in item.items():
                if method in ("get", "post", "put", "patch", "delete"):
                    declared[(method.upper(), path)] = operation
    return declared


@pytest.mark.parametrize(
    ("build", "contracts"),
    [
        (_identity, ["identity.yaml"]),
        # GET /v1/me/workspaces is declared in identity.yaml but SERVED by access in the MVP (ADR 0002).
        (_access, ["access.yaml", "identity.yaml"]),
    ],
    ids=["identity", "access"],
)
def test_implemented_routes_are_in_the_contract(build, contracts):
    declared = _declared(*contracts)
    # app.openapi() is the route table as FastAPI itself sees it (it follows included routers).
    implemented = build().openapi()["paths"]
    assert implemented, "no routes found"
    for path, item in implemented.items():
        for method, generated in item.items():
            operation = declared.get((method.upper(), path))
            assert operation is not None, f"{method.upper()} {path} is implemented but not in {contracts}"
            success = next(code for code in generated["responses"] if code.startswith("2"))
            assert success in operation["responses"], (
                f"{method.upper()} {path} answers {success}, but the contract lists {sorted(operation['responses'])}"
            )
