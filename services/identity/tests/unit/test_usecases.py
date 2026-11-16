"""Identity use cases with in-memory fakes: sign up, sign in + lockout, refresh rotation, sign out.
Each test is one rule from tasks S1-05 to S1-07, checked in milliseconds."""

import pytest
from identity_fakes import GOOD_PASSWORD, POLICY, FakeKeys

from common.errors import Unauthorized
from identity_service.domain.errors import (
    AccountLocked,
    AccountSuspended,
    InvalidCredentials,
    InvalidEmail,
    InvalidRefreshToken,
    WeakPassword,
)
from identity_service.domain.models import IssuedTokens
from identity_service.usecases.session_ops import get_me, sign_out
from identity_service.usecases.sign_in import Denied
from identity_service.usecases.signing_keys import get_jwks, publish_signing_key


def issued(outcome) -> IssuedTokens:
    assert isinstance(outcome, IssuedTokens), f"expected tokens, got {outcome}"
    return outcome


def denied(outcome, error_type) -> Denied:
    assert isinstance(outcome, Denied), f"expected a refusal, got {outcome}"
    assert type(outcome.error) is error_type
    return outcome


# ------------------------------------------------------------------------------------------------- sign up
async def test_sign_up_creates_user_credentials_and_event(world):
    await world.sign_up(email="  Asha@Example.com ")
    (user,) = world.users.users.values()
    assert user.email == "asha@example.com" and user.initials == "AR" and user.email_verified is False
    assert world.users.creds[user.id].password_hash == f"hashed:{GOOD_PASSWORD}"
    (event,) = world.events.added
    assert event[0] == "identity.user.created" and event[1] == user.id
    assert "password" not in str(event[2]).lower()  # no secret material in events


async def test_sign_up_with_existing_email_is_silent_and_costs_the_same(world):
    await world.sign_up()
    hashes_before = world.hasher.hashes
    await world.sign_up(password="another long password")  # same email
    assert len(world.users.users) == 1  # nothing created
    assert len(world.events.added) == 1  # no second event
    assert world.hasher.hashes == hashes_before + 1  # the password was still hashed: same timing


@pytest.mark.parametrize(
    ("email", "password", "error"),
    [("not-an-email", GOOD_PASSWORD, InvalidEmail), ("a@example.com", "short", WeakPassword)],
)
async def test_sign_up_validates_before_any_work(world, email, password, error):
    with pytest.raises(error):
        await world.sign_up(email=email, password=password)
    assert world.users.users == {} and world.hasher.hashes == 0


# ------------------------------------------------------------------------------------------------- sign in
async def test_sign_in_returns_tokens_and_opens_a_session(world):
    await world.sign_up()
    tokens = issued(await world.sign_in(email="ASHA@example.com"))  # case-insensitive
    assert tokens.expires_in == 900 and tokens.refresh_token == "secret-1"
    session = world.sessions.sessions[tokens.session_id]
    assert session.is_live(world.clock.now())
    assert tokens.refresh_expires_at == session.idle_expires_at


async def test_wrong_password_and_unknown_email_look_the_same(world):
    await world.sign_up()
    denied(await world.sign_in(password="wrong password!!"), InvalidCredentials)
    verifications = world.hasher.verifications
    denied(await world.sign_in(email="nobody@example.com"), InvalidCredentials)
    assert world.hasher.verifications == verifications + 1  # unknown email still cost one verification
    denied(await world.sign_in(email="not an email"), InvalidCredentials)  # malformed: same answer


async def test_account_locks_after_max_failures_and_unlocks_after_the_lockout(world):
    await world.sign_up()
    for _ in range(POLICY.max_failed_sign_ins - 1):
        denied(await world.sign_in(password="wrong password!!"), InvalidCredentials)
    locked = denied(await world.sign_in(password="wrong password!!"), AccountLocked)  # the limit: 429
    assert locked.error.status == 429 and locked.error.extra["retry_after_seconds"] == POLICY.lockout_seconds

    # While locked even the RIGHT password is refused, and no hashing work is done.
    verifications = world.hasher.verifications
    denied(await world.sign_in(), AccountLocked)
    assert world.hasher.verifications == verifications

    world.clock.advance(seconds=POLICY.lockout_seconds + 1)
    issued(await world.sign_in())  # lock ran out: the right password works again
    (cred,) = world.users.creds.values()
    assert cred.failed_attempts == 0 and cred.locked_until is None


async def test_one_mistake_after_a_lock_expired_does_not_relock(world):
    await world.sign_up()
    for _ in range(POLICY.max_failed_sign_ins):
        await world.sign_in(password="wrong password!!")
    world.clock.advance(seconds=POLICY.lockout_seconds + 1)
    denied(await world.sign_in(password="wrong password!!"), InvalidCredentials)  # count restarted at 1


async def test_suspended_account_cannot_sign_in(world):
    await world.sign_up()
    (user,) = world.users.users.values()
    world.users.set_status(user.id, "suspended")
    denied(await world.sign_in(), AccountSuspended)


async def test_old_hash_is_upgraded_on_successful_sign_in(world):
    await world.sign_up()
    (user,) = world.users.users.values()
    await world.users.update_password_hash(user.id, f"old:{GOOD_PASSWORD}", world.clock.now())
    issued(await world.sign_in())
    assert world.users.creds[user.id].password_hash == f"hashed:{GOOD_PASSWORD}"


# ------------------------------------------------------------------------------------------------- refresh
async def test_refresh_rotates_the_token(world):
    await world.sign_up()
    first = issued(await world.sign_in())
    world.clock.advance(minutes=10)
    second = issued(await world.refresh(first.refresh_token))
    assert second.refresh_token != first.refresh_token and second.session_id == first.session_id
    third = issued(await world.refresh(second.refresh_token))  # the NEW token works
    assert third.session_id == first.session_id


async def test_reusing_a_refresh_token_ends_the_whole_session(world):
    await world.sign_up()
    first = issued(await world.sign_in())
    second = issued(await world.refresh(first.refresh_token))
    denied(await world.refresh(first.refresh_token), InvalidRefreshToken)  # the old one again: theft
    assert world.sessions.sessions[first.session_id].revoked_at is not None
    denied(await world.refresh(second.refresh_token), InvalidRefreshToken)  # even the newest is dead now


@pytest.mark.parametrize("raw", [None, "", "never-issued"])
async def test_unknown_or_missing_refresh_token_is_refused(world, raw):
    denied(await world.refresh(raw), InvalidRefreshToken)


async def test_refresh_fails_after_idle_timeout_and_after_absolute_limit(world):
    await world.sign_up()
    tokens = issued(await world.sign_in())
    world.clock.advance(seconds=POLICY.refresh_idle_seconds + 1)
    denied(await world.refresh(tokens.refresh_token), InvalidRefreshToken)

    tokens = issued(await world.sign_in())
    for _ in range(4):  # keep the session active every 25 days: idle never hits, absolute (90 d) does
        world.clock.advance(days=25)
        outcome = await world.refresh(tokens.refresh_token)
        if isinstance(outcome, Denied):
            break
        tokens = outcome
    else:
        pytest.fail("session outlived its absolute limit")


async def test_refresh_is_refused_and_session_ended_for_a_suspended_user(world):
    await world.sign_up()
    tokens = issued(await world.sign_in())
    world.users.set_status(tokens.user_id, "suspended")
    denied(await world.refresh(tokens.refresh_token), InvalidRefreshToken)
    assert world.sessions.sessions[tokens.session_id].revoked_at is not None


# --------------------------------------------------------------------------------------- sign out and "me"
async def test_sign_out_ends_only_this_session(world):
    await world.sign_up()
    laptop, phone = issued(await world.sign_in()), issued(await world.sign_in())
    await sign_out(laptop.user_id, laptop.session_id, False, sessions=world.sessions, clock=world.clock)
    denied(await world.refresh(laptop.refresh_token), InvalidRefreshToken)
    issued(await world.refresh(phone.refresh_token))  # the other device is untouched
    await sign_out(laptop.user_id, laptop.session_id, False, sessions=world.sessions, clock=world.clock)  # idempotent


async def test_sign_out_all_ends_every_session(world):
    await world.sign_up()
    laptop, phone = issued(await world.sign_in()), issued(await world.sign_in())
    await sign_out(laptop.user_id, laptop.session_id, True, sessions=world.sessions, clock=world.clock)
    denied(await world.refresh(phone.refresh_token), InvalidRefreshToken)


async def test_cannot_end_someone_elses_session(world):
    await world.sign_up()
    await world.sign_up(email="ben@example.com", name="Ben")
    asha = issued(await world.sign_in())
    ben = issued(await world.sign_in(email="ben@example.com"))
    await sign_out(ben.user_id, asha.session_id, False, sessions=world.sessions, clock=world.clock)
    assert world.sessions.sessions[asha.session_id].revoked_at is None


async def test_get_me_and_inactive_account(world):
    await world.sign_up()
    tokens = issued(await world.sign_in())
    me = await get_me(tokens.user_id, users=world.users)
    assert me.email == "asha@example.com" and me.display_name == "Asha Rao"
    world.users.set_status(tokens.user_id, "suspended")
    with pytest.raises(Unauthorized):
        await get_me(tokens.user_id, users=world.users)


# ------------------------------------------------------------------------------------------------- keys
async def test_publishing_a_new_key_keeps_the_previous_one_verifiable(world):
    keys = FakeKeys()
    await publish_signing_key(keys=keys, tokens=world.tokens, clock=world.clock, token_ttl_seconds=900)
    assert [k["kid"] for k in (await get_jwks(keys=keys))["keys"]] == ["fake-kid"]

    class Rotated:
        kid, key_ref = "new-kid", "fake:key2"
        public_jwk = {"kty": "OKP", "kid": "new-kid"}  # noqa: RUF012

    await publish_signing_key(keys=keys, tokens=Rotated(), clock=world.clock, token_ttl_seconds=900)
    assert {k["kid"] for k in (await get_jwks(keys=keys))["keys"]} == {"fake-kid", "new-kid"}
    assert keys.rows["fake-kid"]["status"] == "retiring" and keys.rows["new-kid"]["status"] == "active"
