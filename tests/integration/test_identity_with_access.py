"""Identity and access TOGETHER, each on its own real PostgreSQL database, wired the way production is:
access never sees a password or a user table; it only verifies identity's tokens against identity's
published public keys (GET /.well-known/jwks.json).

This is steps 1 and 3 of the MVP demo script (plan/tech/15-sprint-plan.md) as far as these two
services go: A signs up and creates the workspace "Pilot"; B signs up, joins by invite link and lands as a
Member; B cannot rename the workspace.

Run:  uv run pytest -m integration tests/integration
"""

from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from access_service.main import create_app as create_access
from access_service.settings import Settings as AccessSettings
from common.auth import KeySetVerifier
from common.ids import new_id
from identity_service.main import create_app as create_identity
from identity_service.settings import Settings as IdentitySettings

pytestmark = pytest.mark.integration
PASSWORD = "correct horse battery"
SIGNING_KEY = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")


async def test_sign_up_create_workspace_invite_and_join(make_db):
    identity_db, access_db = make_db("identity"), make_db("access")
    identity_app = create_identity(
        IdentitySettings(
            service_name="identity",
            database_url=identity_db.app_url,
            signing_private_key=SIGNING_KEY,
            argon2_time_cost=1,
            argon2_memory_kib=8,
            argon2_parallelism=1,
            log_level="WARNING",
        )
    )

    async with identity_app.router.lifespan_context(identity_app):
        identity = httpx.AsyncClient(transport=httpx.ASGITransport(app=identity_app), base_url="http://identity")

        async def identity_public_keys() -> list[dict[str, Any]]:
            # What RemoteJwksVerifier does over the network in production, here through the ASGI app.
            return (await identity.get("/.well-known/jwks.json")).json()["keys"]

        access_app = create_access(
            AccessSettings(service_name="access", database_url=access_db.app_url, log_level="WARNING"),
            verifier=KeySetVerifier(identity_public_keys, "work-platform"),
        )
        async with access_app.router.lifespan_context(access_app), identity:
            access = httpx.AsyncClient(transport=httpx.ASGITransport(app=access_app), base_url="http://access")
            async with access:

                async def sign_up_and_in(email: str, name: str) -> dict[str, str]:
                    body = {"email": email, "password": PASSWORD, "displayName": name}
                    assert (await identity.post("/v1/auth/sign-up", json=body)).status_code == 202
                    signed_in = await identity.post("/v1/auth/sign-in", json={"email": email, "password": PASSWORD})
                    assert signed_in.status_code == 200
                    identity.cookies.clear()  # one client plays two people: do not mix their refresh cookies
                    return {"Authorization": f"Bearer {signed_in.json()['accessToken']}"}

                # 1. Person A signs up and creates the workspace "Pilot".
                a = await sign_up_and_in("asha@example.com", "Asha Rao")
                created = await access.post(
                    "/v1/workspaces", json={"id": str(new_id()), "name": "Pilot", "slug": "pilot"}, headers=a
                )
                assert created.status_code == 202
                ws = created.json()
                base = f"/v1/w/{ws['id']}"

                # 3. A invites B by link. B signs up, accepts, and lands in "Pilot" as a Member.
                invited = await access.post(
                    f"{base}/invites", json={"invites": [{"email": "ben@example.com", "roleKind": "member"}]}, headers=a
                )
                token = invited.json()["results"][0]["inviteToken"]
                b = await sign_up_and_in("ben@example.com", "Ben Okoro")
                joined = await access.post("/v1/invites/accept", json={"token": token}, headers=b)
                assert joined.status_code == 200 and joined.json()["roleKind"] == "member"

                # The member list shows names and emails that came from the identity tokens.
                members = (await access.get(f"{base}/members", headers=b)).json()["items"]
                assert [(m["displayName"], m["email"], m["roleKind"]) for m in members] == [
                    ("Asha Rao", "asha@example.com", "owner"),
                    ("Ben Okoro", "ben@example.com", "member"),
                ]
                assert [w["name"] for w in (await access.get("/v1/me/workspaces", headers=b)).json()] == ["Pilot"]

                # B is a Member: cannot rename. A can.
                rename = {
                    "name": "Renamed",
                    "version": (await access.get(f"{base}/workspace", headers=b)).json()["version"],
                }
                assert (await access.patch(f"{base}/workspace", json=rename, headers=b)).status_code == 403
                assert (await access.patch(f"{base}/workspace", json=rename, headers=a)).status_code == 200

                # A token that identity did not sign is refused by access.
                forged = {"Authorization": a["Authorization"][:-6] + "AAAAAA"}
                assert (await access.get("/v1/me/workspaces", headers=forged)).status_code == 401

    # The two services share NOTHING at the database level: the user ids in access exist as users only
    # in identity's database, and access's database has no users table at all.
    with identity_db.admin_engine().connect() as conn:
        user_ids = {r.id for r in conn.execute(text("SELECT id FROM users"))}
    with access_db.admin_engine().connect() as conn:
        member_ids = {r.user_id for r in conn.execute(text("SELECT user_id FROM workspace_members"))}
        assert conn.execute(text("SELECT to_regclass('public.users')")).scalar() is None
    assert member_ids == user_ids and len(user_ids) == 2
