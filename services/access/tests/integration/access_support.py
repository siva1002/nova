"""Helpers for access integration tests: the REAL app on a REAL PostgreSQL, driven over HTTP in-process.

Access only VERIFIES tokens. Tests sign them with a throw-away key (`token_factory` from the repo-root
conftest) and hand the app a verifier that knows the matching public key, so no identity service and no
network are needed. Everything else (routing, validation, transactions, row-level security, SQL) is real.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from fastapi import FastAPI

from access_service.main import create_app
from access_service.settings import Settings
from common.auth import KeySetVerifier
from common.errors import DependencyUnavailable
from common.ids import new_id


@dataclass(frozen=True)
class Person:
    user_id: UUID
    email: str
    name: str


def person(name: str) -> Person:
    return Person(new_id(), f"{name.lower()}@example.com", f"{name} Tester")


class SwitchableHierarchy:
    """Stands in for the hierarchy service: can be switched off to simulate an outage."""

    def __init__(self, available: bool = True) -> None:
        self.available = available
        self.seeded: list[UUID] = []

    async def seed_workspace(self, workspace_id: UUID, owner_user_id: UUID, bearer_token: str | None) -> None:
        if not self.available:
            raise DependencyUnavailable("Hierarchy service did not answer")
        self.seeded.append(workspace_id)


@dataclass
class Running:
    client: httpx.AsyncClient
    app: FastAPI
    db: Any  # conftest.ServiceDb
    tokens: Any  # conftest.TokenFactory

    def auth(self, who: Person) -> dict[str, str]:
        return self.tokens.headers(who.user_id, who.email, who.name)

    async def create_workspace(
        self, owner: Person, name: str = "Pilot", slug: str | None = None, ws_id: UUID | None = None
    ) -> httpx.Response:
        body = {
            "id": str(ws_id or new_id()),
            "name": name,
            "slug": slug or f"ws-{new_id().hex[-10:]}",
            "region": "ap-south-1",
        }
        return await self.client.post("/v1/workspaces", json=body, headers=self.auth(owner))

    async def invite(self, ws_id: str, by: Person, email: str, role: str = "member") -> httpx.Response:
        return await self.client.post(
            f"/v1/w/{ws_id}/invites", json={"invites": [{"email": email, "roleKind": role}]}, headers=self.auth(by)
        )

    async def accept(self, token: str, who: Person) -> httpx.Response:
        return await self.client.post("/v1/invites/accept", json={"token": token}, headers=self.auth(who))

    async def join(self, ws_id: str, by: Person, who: Person, role: str = "member") -> dict[str, Any]:
        """Invite `who` and accept: the usual way a second person gets into a workspace."""
        invited = await self.invite(ws_id, by, who.email, role)
        assert invited.status_code == 207, invited.text
        token = invited.json()["results"][0]["inviteToken"]
        accepted = await self.accept(token, who)
        assert accepted.status_code == 200, accepted.text
        return accepted.json()


@asynccontextmanager
async def running(db: Any, tokens: Any, **setting_overrides: Any) -> AsyncIterator[Running]:
    values: dict[str, Any] = {"service_name": "access", "database_url": db.app_url, "log_level": "WARNING"}
    values.update(setting_overrides)

    async def public_keys() -> list[dict[str, Any]]:
        return tokens.jwks

    app = create_app(Settings(**values), verifier=KeySetVerifier(public_keys, tokens.issuer))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://access") as client:
            yield Running(client, app, db, tokens)
