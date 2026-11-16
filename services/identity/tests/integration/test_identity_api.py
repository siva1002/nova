"""Identity end to end on a real PostgreSQL: HTTP in, SQL out. Tasks S1-05, S1-06, S1-07.

Run:  uv run pytest -m integration services/identity
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from identity_support import KEY_B, PASSWORD, running
from sqlalchemy import text

from common.auth import KeySetVerifier

pytestmark = pytest.mark.integration
COOKIE = "refresh_token"


async def refresh_with(identity, token: str):
    """POST /v1/auth/refresh presenting exactly this refresh token (the client's cookie jar is emptied
    first, so no other cookie rides along)."""
    identity.client.cookies.clear()
    return await identity.client.post("/v1/auth/refresh", headers={"Cookie": f"{COOKIE}={token}"})


def rows(db, sql: str, **params):
    with db.admin_engine().connect() as conn:
        return conn.execute(text(sql), params).all()


# ------------------------------------------------------------------------------------------------- sign up
async def test_sign_up_stores_a_hashed_password_and_an_outbox_event(identity):
    r = await identity.sign_up(email="Asha@Example.com")
    assert r.status_code == 202 and r.content == b""

    (user,) = rows(identity.db, "SELECT id, email, display_name, initials, email_verified_at, status FROM users")
    assert (user.email, user.display_name, user.initials, user.status) == (
        "asha@example.com",
        "Asha Rao",
        "AR",
        "active",
    )
    assert user.email_verified_at is None

    (cred,) = rows(identity.db, "SELECT password_hash FROM user_credentials")
    assert cred.password_hash.startswith("$argon2id$") and PASSWORD not in cred.password_hash

    (event,) = rows(
        identity.db, "SELECT workspace_id, aggregate_id, event_type, payload, actor_user_id, origin FROM outbox"
    )
    assert event.event_type == "identity.user.created" and event.aggregate_id == user.id
    assert event.workspace_id == user.id  # global service: the partition key is the user id
    assert event.payload["after"]["email"] == "asha@example.com" and "password" not in str(event.payload).lower()


async def test_sign_up_again_with_the_same_email_answers_the_same_and_creates_nothing(identity):
    assert (await identity.sign_up()).status_code == 202
    again = await identity.sign_up(email="ASHA@example.com", password="a different long password")
    assert again.status_code == 202 and again.content == b""  # no account probing
    assert len(rows(identity.db, "SELECT 1 FROM users")) == 1
    assert len(rows(identity.db, "SELECT 1 FROM outbox")) == 1
    # ... and the original password still works: the second sign-up changed nothing.
    assert (await identity.sign_in()).status_code == 200


async def test_two_simultaneous_sign_ups_create_exactly_one_user(identity):
    results = await asyncio.gather(*(identity.sign_up(email="race@example.com") for _ in range(5)))
    assert {r.status_code for r in results} == {202}
    assert len(rows(identity.db, "SELECT 1 FROM users")) == 1
    assert len(rows(identity.db, "SELECT 1 FROM user_credentials")) == 1


async def test_sign_up_validation_names_the_field_and_never_echoes_the_password(identity):
    r = await identity.client.post(
        "/v1/auth/sign-up", json={"email": "not-an-email", "password": "tiny-secret", "displayName": ""}
    )
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["code"] == "common.validation_failed"
    assert {e["field"] for e in body["errors"]} == {"email", "password", "displayName"}
    assert "tiny-secret" not in r.text
    assert rows(identity.db, "SELECT 1 FROM users") == []


# ---------------------------------------------------------------------------------------- sign in and "me"
async def test_sign_in_me_and_the_token_verifies_against_the_published_keys(identity):
    await identity.sign_up()
    r = await identity.sign_in(email="ASHA@EXAMPLE.COM")  # case-insensitive
    assert r.status_code == 200
    body = r.json()
    assert body["expiresIn"] == 900 and set(body) == {"accessToken", "expiresIn"}  # no refresh token in the body

    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{COOKIE}=") and "HttpOnly" in cookie and "Path=/v1/auth" in cookie
    assert "SameSite=lax" in cookie

    me = await identity.client.get("/v1/me", headers=identity.bearer(r))
    assert me.status_code == 200
    assert me.json()["email"] == "asha@example.com" and me.json()["displayName"] == "Asha Rao"
    assert me.json()["emailVerified"] is False and me.json()["version"] == 1

    # What every OTHER service does: download the JWKS and verify locally.
    jwks = await identity.client.get("/.well-known/jwks.json")
    assert jwks.status_code == 200 and "max-age=300" in jwks.headers["cache-control"]
    (key,) = jwks.json()["keys"]
    assert key["alg"] == "EdDSA" and "d" not in key  # public part only

    async def load():
        return jwks.json()["keys"]

    claims = await KeySetVerifier(load, "work-platform").verify(body["accessToken"])
    (user,) = rows(identity.db, "SELECT id FROM users")
    assert claims.user_id == user.id and claims.email == "asha@example.com" and claims.name == "Asha Rao"
    assert claims.session_id is not None


async def test_wrong_password_unknown_email_and_bad_tokens_are_all_401(identity):
    await identity.sign_up()
    wrong = await identity.sign_in(password="wrong password here")
    unknown = await identity.sign_in(email="nobody@example.com")
    malformed = await identity.sign_in(email="not an email")
    for r in (wrong, unknown, malformed):
        assert r.status_code == 401 and r.json()["code"] == "auth.invalid_credentials"
        assert "set-cookie" not in r.headers
    assert wrong.json()["detail"] == unknown.json()["detail"]  # indistinguishable

    good = (await identity.sign_in()).json()["accessToken"]
    for header in (
        {},
        {"Authorization": "Bearer nonsense"},
        {"Authorization": f"Bearer {good[:-4]}AAAA"},
        {"Authorization": good},
    ):
        r = await identity.client.get("/v1/me", headers=header)
        assert r.status_code == 401 and r.json()["code"] == "common.unauthorized"


async def test_account_locks_after_repeated_failures_and_the_count_survives_the_401(identity):
    await identity.sign_up()
    assert (await identity.sign_in(password="wrong password 1")).status_code == 401
    # The failed request answered 401 AND its counter update was committed (result-not-exception pattern).
    assert rows(identity.db, "SELECT failed_attempts FROM user_credentials")[0].failed_attempts == 1

    assert (await identity.sign_in(password="wrong password 2")).status_code == 401
    third = await identity.sign_in(password="wrong password 3")  # max_failed_sign_ins = 3 in tests
    assert third.status_code == 429 and third.json()["code"] == "auth.account_locked"
    assert int(third.headers["retry-after"]) == 900

    locked = await identity.sign_in()  # even the RIGHT password is refused while locked
    assert locked.status_code == 429 and 0 < int(locked.headers["retry-after"]) <= 901

    # Lock runs out (simulated by moving it into the past): sign-in works and the counter is cleared.
    with identity.db.admin_engine().begin() as conn:
        conn.execute(text("UPDATE user_credentials SET locked_until = now() - interval '1 second'"))
    assert (await identity.sign_in()).status_code == 200
    (cred,) = rows(identity.db, "SELECT failed_attempts, locked_until FROM user_credentials")
    assert cred.failed_attempts == 0 and cred.locked_until is None


async def test_per_ip_rate_limit_answers_429_before_any_work(identity_env):
    async with running(identity_env, ip_rate_limit=2) as identity:
        assert (await identity.sign_in()).status_code == 401
        assert (await identity.sign_in()).status_code == 401
        limited = await identity.sign_in()
        assert limited.status_code == 429 and limited.json()["code"] == "auth.rate_limited"
        assert int(limited.headers["retry-after"]) >= 1


# ------------------------------------------------------------------------------------------------- refresh
async def test_refresh_rotates_the_cookie_and_stores_only_hashes(identity):
    await identity.sign_up()
    await identity.sign_in()
    first_cookie = identity.client.cookies.get(COOKIE)

    r = await identity.client.post("/v1/auth/refresh")
    assert r.status_code == 200 and r.json()["expiresIn"] == 900
    second_cookie = identity.client.cookies.get(COOKIE)
    assert second_cookie and second_cookie != first_cookie
    assert (await identity.client.get("/v1/me", headers=identity.bearer(r))).status_code == 200

    stored = rows(identity.db, "SELECT token_hash, used_at FROM refresh_tokens ORDER BY created_at")
    assert len(stored) == 2
    assert bytes(stored[0].token_hash) == hashlib.sha256(first_cookie.encode()).digest()  # hash, not the token
    assert stored[0].used_at is not None and stored[1].used_at is None


async def test_reusing_an_old_refresh_token_ends_the_session_for_everyone(identity):
    await identity.sign_up()
    await identity.sign_in()
    stolen = identity.client.cookies.get(COOKIE)
    assert (await identity.client.post("/v1/auth/refresh")).status_code == 200  # the owner rotates
    current = identity.client.cookies.get(COOKIE)

    replay = await refresh_with(identity, stolen)  # the thief replays the old token
    assert replay.status_code == 401 and replay.json()["code"] == "auth.invalid_refresh_token"
    assert rows(identity.db, "SELECT revoked_at FROM user_sessions")[0].revoked_at is not None  # committed

    assert (await refresh_with(identity, current)).status_code == 401  # the newest token died too


async def test_two_simultaneous_refreshes_with_one_token_cannot_both_win(identity):
    await identity.sign_up()
    await identity.sign_in()
    token = identity.client.cookies.get(COOKIE)
    identity.client.cookies.clear()
    header = {"Cookie": f"{COOKIE}={token}"}
    results = await asyncio.gather(*(identity.client.post("/v1/auth/refresh", headers=header) for _ in range(4)))
    assert sorted(r.status_code for r in results).count(200) == 1  # the atomic claim: one winner only
    assert len(rows(identity.db, "SELECT 1 FROM refresh_tokens")) == 2  # the original + exactly one successor


async def test_refresh_without_or_with_an_unknown_cookie_is_401(identity):
    assert (await identity.client.post("/v1/auth/refresh")).status_code == 401
    r = await refresh_with(identity, "never-issued")
    assert r.status_code == 401 and r.json()["code"] == "auth.invalid_refresh_token"


# ------------------------------------------------------------------------------------------------ sign out
async def test_sign_out_ends_the_session_and_clears_the_cookie(identity):
    await identity.sign_up()
    signed_in = await identity.sign_in()
    refresh_cookie = identity.client.cookies.get(COOKIE)

    out = await identity.client.post("/v1/auth/sign-out", headers=identity.bearer(signed_in))
    assert out.status_code == 204
    assert f'{COOKIE}=""' in out.headers["set-cookie"] or f"{COOKIE}=;" in out.headers["set-cookie"]
    assert rows(identity.db, "SELECT revoked_at FROM user_sessions")[0].revoked_at is not None

    r = await refresh_with(identity, refresh_cookie)
    assert r.status_code == 401  # the session's refresh token is dead immediately
    assert (await identity.client.post("/v1/auth/sign-out")).status_code == 401  # sign-out needs a token


async def test_sign_out_all_ends_every_device(identity):
    await identity.sign_up()
    laptop = await identity.sign_in()
    await identity.sign_in()  # a second device
    assert len(rows(identity.db, "SELECT 1 FROM user_sessions WHERE revoked_at IS NULL")) == 2
    out = await identity.client.post("/v1/auth/sign-out?all=true", headers=identity.bearer(laptop))
    assert out.status_code == 204
    assert rows(identity.db, "SELECT 1 FROM user_sessions WHERE revoked_at IS NULL") == []


# -------------------------------------------------------------------------------------------- key rotation
async def test_key_rotation_keeps_old_tokens_valid_until_they_expire(identity_env):
    async with running(identity_env) as before:  # key A
        await before.sign_up()
        old = await before.sign_in()
        old_kid = (await before.client.get("/.well-known/jwks.json")).json()["keys"][0]["kid"]

    async with running(identity_env, signing_private_key=KEY_B) as after:  # restart with key B
        keys = (await after.client.get("/.well-known/jwks.json")).json()["keys"]
        assert len(keys) == 2 and keys[0]["kid"] != old_kid and keys[1]["kid"] == old_kid  # new first
        statuses = dict(rows(after.db, "SELECT kid, status FROM signing_keys"))
        assert statuses[old_kid] == "retiring" and sorted(statuses.values()) == ["active", "retiring"]

        assert (await after.client.get("/v1/me", headers=after.bearer(old))).status_code == 200  # A still verifies
        new = await after.sign_in()
        assert (await after.client.get("/v1/me", headers=after.bearer(new))).status_code == 200  # B works


# ------------------------------------------------------------------------------------------------- plumbing
async def test_request_id_is_returned_and_readiness_checks_the_database(identity):
    r = await identity.client.get("/readyz", headers={"X-Request-Id": "trace-42"})
    assert r.status_code == 200 and r.json() == {"status": "ready"} and r.headers["x-request-id"] == "trace-42"
    problem = await identity.client.get("/v1/me", headers={"X-Request-Id": "trace-43"})
    assert problem.json()["traceId"] == "trace-43"  # the id a user can quote in a bug report
