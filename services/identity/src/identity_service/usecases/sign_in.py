"""USE CASE: sign in with email and password (S1-06, lockout from S1-07).

RESULT, NOT EXCEPTION
  A failed sign-in must still WRITE (count the failure, maybe lock the account). An exception would roll
  the transaction back and lose that write. So this use case RETURNS either `IssuedTokens` or `Denied`;
  the route commits first and raises `denied.error` afterwards.

BRUTE FORCE
  - per account: `max_failed_sign_ins` wrong passwords in a row lock the account for `lockout_seconds`
    (stored in the database, so it holds across processes and restarts). The attempt that reaches the
    limit already answers 429.
  - per IP: handled before this use case by the rate limiter in the api/ layer.

NO TIMING ORACLE
  An unknown email costs one fake verification (`hasher.burn`), so it takes as long as a wrong password.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta

from common.errors import DomainError
from common.ids import new_id
from common.ports import Clock
from identity_service.domain.errors import AccountLocked, AccountSuspended, InvalidCredentials, InvalidEmail
from identity_service.domain.models import IssuedTokens, RefreshToken, Session, SessionPolicy
from identity_service.domain.rules import hash_refresh_token, normalize_email
from identity_service.usecases.ports import PasswordHasher, SessionRepo, TokenIssuer, UserRepo


@dataclass(frozen=True, slots=True)
class Denied:
    """A refusal that must be raised AFTER the transaction commits (see module docstring)."""

    error: DomainError


async def sign_in(
    email: str,
    password: str,
    *,
    users: UserRepo,
    sessions: SessionRepo,
    hasher: PasswordHasher,
    tokens: TokenIssuer,
    clock: Clock,
    policy: SessionPolicy,
    new_secret: Callable[[], str],
    ip: str | None = None,
    user_agent: str | None = None,
) -> IssuedTokens | Denied:
    now = clock.now()
    try:
        found = await users.get_by_email(normalize_email(email))
    except InvalidEmail:
        found = None  # a malformed address is just "no such user": same answer, same timing
    if found is None:
        await hasher.burn(password)
        return Denied(InvalidCredentials())
    user, cred = found

    if cred.locked_until is not None and cred.locked_until > now:
        retry = int((cred.locked_until - now).total_seconds()) + 1
        return Denied(AccountLocked(retry_after_seconds=retry))

    if cred.password_hash is None or not await hasher.verify(cred.password_hash, password):
        lock_until = now + timedelta(seconds=policy.lockout_seconds)
        _, locked_until = await users.register_failed_sign_in(user.id, now, policy.max_failed_sign_ins, lock_until)
        if locked_until is not None:
            return Denied(AccountLocked(retry_after_seconds=policy.lockout_seconds))
        return Denied(InvalidCredentials())

    if user.status != "active":
        return Denied(AccountSuspended())

    # ---- success from here on
    if cred.failed_attempts or cred.locked_until:
        await users.reset_failed_sign_ins(user.id)
    if hasher.needs_rehash(cred.password_hash):
        # Hash parameters were raised since this password was stored: upgrade it now, while we have it.
        await users.update_password_hash(user.id, await hasher.hash(password), now)

    absolute = now + timedelta(seconds=policy.session_absolute_seconds)
    idle = min(now + timedelta(seconds=policy.refresh_idle_seconds), absolute)
    session = Session(id=new_id(), user_id=user.id, idle_expires_at=idle, absolute_expires_at=absolute, revoked_at=None)
    await sessions.create_session(session, ip, user_agent)

    raw_refresh = new_secret()
    await sessions.insert_refresh_token(
        RefreshToken(hash_refresh_token(raw_refresh), session.id, user.id, expires_at=idle, used_at=None)
    )
    access_token, expires_in = tokens.issue(user, session.id, now)
    return IssuedTokens(access_token, expires_in, raw_refresh, idle, user.id, session.id)
