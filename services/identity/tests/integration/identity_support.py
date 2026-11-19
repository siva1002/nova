"""Helpers for identity integration tests: start the REAL app on a REAL PostgreSQL and talk HTTP to it.

Nothing is faked except the network: requests go through httpx's ASGI transport straight into the
FastAPI app (same routing, middleware, validation, transactions and SQL as in production).
"""

from __future__ import annotations

import base64
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import FastAPI

from identity_service.main import create_app
from identity_service.settings import Settings

KEY_A = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
KEY_B = base64.urlsafe_b64encode(bytes(range(1, 33))).decode().rstrip("=")
PASSWORD = "correct horse battery"


@dataclass
class Env:
    """One fresh identity database, plus a settings factory bound to it (so a test can start the
    service twice on the same data, e.g. to rotate the signing key)."""

    db: Any  # conftest.ServiceDb

    def settings(self, **overrides: Any) -> Settings:
        values: dict[str, Any] = {
            "service_name": "identity",
            "environment": "local",  # allows the non-Secure cookie that http://testserver needs
            "database_url": self.db.app_url,
            "signing_private_key": KEY_A,
            # Tiny Argon2 parameters: the real algorithm, in a millisecond instead of 50.
            "argon2_time_cost": 1,
            "argon2_memory_kib": 8,
            "argon2_parallelism": 1,
            "max_failed_sign_ins": 3,
            "ip_rate_limit": 10_000,  # out of the way, except in the test that lowers it
            "log_level": "WARNING",
        }
        values.update(overrides)
        return Settings(**values)


@dataclass
class Running:
    client: httpx.AsyncClient
    app: FastAPI
    db: Any

    async def sign_up(
        self, email: str = "asha@example.com", password: str = PASSWORD, name: str = "Asha Rao"
    ) -> httpx.Response:
        return await self.client.post(
            "/v1/auth/sign-up", json={"email": email, "password": password, "displayName": name}
        )

    async def sign_in(self, email: str = "asha@example.com", password: str = PASSWORD) -> httpx.Response:
        return await self.client.post("/v1/auth/sign-in", json={"email": email, "password": password})

    def bearer(self, sign_in_response: httpx.Response) -> dict[str, str]:
        return {"Authorization": f"Bearer {sign_in_response.json()['accessToken']}"}


@asynccontextmanager
async def running(env: Env, **setting_overrides: Any) -> AsyncGenerator[Running, None]:
    """Start the app (lifespan included: this publishes the signing key) and give an HTTP client."""
    app = create_app(env.settings(**setting_overrides))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield Running(client, app, env.db)
