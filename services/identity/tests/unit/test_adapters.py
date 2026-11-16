"""The real adapters, without a database: Argon2 hashing, Ed25519 signing (verified with the shared
verifier every other service uses), and the in-process rate limiter."""

import base64
import time
from datetime import UTC, datetime
from uuid import uuid4

import jwt
import pytest
from identity_fakes import T0

from common.auth import KeySetVerifier
from common.errors import Unauthorized
from identity_service.adapters.password_hasher import Argon2Hasher
from identity_service.adapters.rate_limiter import InMemoryRateLimiter
from identity_service.adapters.token_signer import Ed25519Signer
from identity_service.domain.models import User

SEED = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")  # a fixed test key


def _user() -> User:
    return User(
        uuid4(), "asha@example.com", "asha", "Asha Rao", "AR", "#fff", None, None, None, False, "active", 1, T0, T0
    )


def _signer(issuer: str = "work-platform", ttl: int = 900, seed: str = SEED) -> Ed25519Signer:
    return Ed25519Signer.from_settings(seed, environment="production", issuer=issuer, ttl_seconds=ttl)


def _verifier(signer: Ed25519Signer, issuer: str = "work-platform") -> KeySetVerifier:
    async def load():
        return [signer.public_jwk]

    return KeySetVerifier(load, issuer)


# ------------------------------------------------------------------------------------------------- hashing
async def test_argon2_hash_verifies_and_is_salted():
    hasher = Argon2Hasher(time_cost=1, memory_kib=8, parallelism=1, max_concurrency=2)  # tiny: fast tests
    first, second = await hasher.hash("correct horse battery"), await hasher.hash("correct horse battery")
    assert first.startswith("$argon2id$") and first != second  # random salt per hash
    assert await hasher.verify(first, "correct horse battery") is True
    assert await hasher.verify(first, "wrong") is False
    assert await hasher.verify("not-a-hash", "anything") is False  # a corrupt hash is just "no"
    await hasher.burn("anything")  # must not raise


async def test_needs_rehash_when_parameters_are_raised():
    weak = Argon2Hasher(time_cost=1, memory_kib=8, parallelism=1, max_concurrency=1)
    strong = Argon2Hasher(time_cost=2, memory_kib=16, parallelism=1, max_concurrency=1)
    old_hash = await weak.hash("correct horse battery")
    assert strong.needs_rehash(old_hash) is True and weak.needs_rehash(old_hash) is False


# ------------------------------------------------------------------------------------------------- signing
async def test_token_round_trip_carries_the_claims():
    signer, user, sid = _signer(), _user(), uuid4()
    token, ttl = signer.issue(user, sid, datetime.now(UTC))
    claims = await _verifier(signer).verify(token)
    assert (claims.user_id, claims.session_id, claims.email, claims.name) == (user.id, sid, user.email, "Asha Rao")
    assert ttl == 900 and jwt.get_unverified_header(token) == {"alg": "EdDSA", "kid": signer.kid, "typ": "JWT"}


async def test_kid_is_stable_for_a_key_and_differs_between_keys():
    other_seed = base64.urlsafe_b64encode(bytes(range(1, 33))).decode()
    assert _signer().kid == _signer().kid != _signer(seed=other_seed).kid
    assert "d" not in _signer().public_jwk  # the private part is never in the published key


async def test_tampered_expired_wrong_issuer_and_foreign_key_tokens_are_refused():
    signer, user = _signer(), _user()
    now = datetime.now(UTC)
    good, _ = signer.issue(user, uuid4(), now)
    verifier = _verifier(signer)
    await verifier.verify(good)

    head, payload, sig = good.split(".")
    flipped = payload[:-2] + ("AA" if payload[-2:] != "AA" else "BB")
    for bad in (f"{head}.{flipped}.{sig}", good[:-3] + "abc", "not.a.token", ""):
        with pytest.raises(Unauthorized):
            await verifier.verify(bad)

    expired, _ = _signer(ttl=-60).issue(user, uuid4(), now)
    with pytest.raises(Unauthorized):
        await verifier.verify(expired)

    with pytest.raises(Unauthorized):  # right key, wrong issuer
        await _verifier(signer, issuer="someone-else").verify(good)

    stranger = _signer(seed=base64.urlsafe_b64encode(bytes(range(1, 33))).decode())
    foreign, _ = stranger.issue(user, uuid4(), now)
    with pytest.raises(Unauthorized):  # signed by a key we never published
        await verifier.verify(foreign)


async def test_alg_none_and_hmac_confusion_are_refused():
    signer = _signer()
    verifier = _verifier(signer)
    claims = {"iss": "work-platform", "sub": str(uuid4()), "iat": int(time.time()), "exp": int(time.time()) + 60}
    unsigned = jwt.encode(claims, key="", algorithm="none", headers={"kid": signer.kid})
    hmac_with_public_key = jwt.encode(
        claims, key=signer.public_jwk["x"], algorithm="HS256", headers={"kid": signer.kid}
    )
    for forged in (unsigned, hmac_with_public_key):
        with pytest.raises(Unauthorized):
            await verifier.verify(forged)


def test_signer_requires_a_key_outside_local_and_rejects_garbage():
    with pytest.raises(RuntimeError):
        Ed25519Signer.from_settings("", environment="production", issuer="x", ttl_seconds=900)
    with pytest.raises(RuntimeError):
        Ed25519Signer.from_settings("not-a-seed", environment="local", issuer="x", ttl_seconds=900)
    local = Ed25519Signer.from_settings("", environment="local", issuer="x", ttl_seconds=900)
    assert local.key_ref == "ephemeral:local"


# -------------------------------------------------------------------------------------------- rate limiter
def test_rate_limiter_blocks_over_the_limit_and_resets_after_the_window():
    now = [1000.0]
    limiter = InMemoryRateLimiter(limit=3, window_seconds=60, monotonic=lambda: now[0])
    assert [limiter.hit("1.2.3.4") for _ in range(3)] == [None, None, None]
    wait = limiter.hit("1.2.3.4")
    assert wait is not None and 1 <= wait <= 61
    assert limiter.hit("5.6.7.8") is None  # another client is unaffected
    now[0] += 61
    assert limiter.hit("1.2.3.4") is None  # new window


def test_rate_limiter_memory_is_bounded():
    now = [0.0]
    limiter = InMemoryRateLimiter(limit=5, window_seconds=10, max_keys=100, monotonic=lambda: now[0])
    for i in range(100):
        limiter.hit(f"ip-{i}")
    now[0] += 11  # all of those windows are over
    limiter.hit("fresh")  # pushes the table past max_keys -> sweep
    assert len(limiter._hits) == 1
