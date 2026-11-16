"""USE CASE: trade a refresh token for a new access token (S1-07).

ROTATION
  Every refresh token works ONCE. Using it returns a new access token AND a new refresh token; the old
  one is marked used in the same transaction.

REUSE = THEFT
  If a token that was already used shows up again, someone copied it (the real user or the thief used it
  first, we cannot know who). We end the WHOLE session, so both must sign in again.
  The claim is one atomic UPDATE, so two simultaneous refreshes with one token cannot both win.

Like sign-in, this returns `Denied` instead of raising: revoking the session on reuse must be committed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from common.ports import Clock
from identity_service.domain.errors import InvalidRefreshToken
from identity_service.domain.models import IssuedTokens, RefreshToken, SessionPolicy
from identity_service.domain.rules import hash_refresh_token
from identity_service.usecases.ports import SessionRepo, TokenIssuer, UserRepo
from identity_service.usecases.sign_in import Denied

log = logging.getLogger(__name__)


async def refresh_session(
    raw_token: str | None,
    *,
    users: UserRepo,
    sessions: SessionRepo,
    tokens: TokenIssuer,
    clock: Clock,
    policy: SessionPolicy,
    new_secret: Callable[[], str],
) -> IssuedTokens | Denied:
    if not raw_token:
        return Denied(InvalidRefreshToken())
    now = clock.now()
    token_hash = hash_refresh_token(raw_token)

    claimed = await sessions.claim_refresh_token(token_hash, now)
    if claimed is None:
        seen_before = await sessions.get_refresh_token(token_hash)
        if seen_before is not None:  # it exists, so it was already used: reuse detected
            await sessions.revoke_session(seen_before.session_id, now)
            log.warning("refresh token reuse: session %s revoked", seen_before.session_id)
        return Denied(InvalidRefreshToken())

    session = await sessions.get_session(claimed.session_id)
    if claimed.expires_at <= now or session is None or not session.is_live(now):
        return Denied(InvalidRefreshToken())

    user = await users.get_by_id(claimed.user_id)
    if user is None or user.status != "active":
        await sessions.revoke_session(claimed.session_id, now)  # suspended or deleted: end the session
        return Denied(InvalidRefreshToken())

    # Slide the idle window forward, but never past the session's absolute limit.
    idle = min(now + timedelta(seconds=policy.refresh_idle_seconds), session.absolute_expires_at)
    await sessions.touch_session(session.id, now, idle)

    raw_refresh = new_secret()
    await sessions.insert_refresh_token(
        RefreshToken(hash_refresh_token(raw_refresh), session.id, user.id, expires_at=idle, used_at=None)
    )
    access_token, expires_in = tokens.issue(user, session.id, now)
    return IssuedTokens(access_token, expires_in, raw_refresh, idle, user.id, session.id)
