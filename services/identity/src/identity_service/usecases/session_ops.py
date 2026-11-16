"""USE CASES: sign out and "who am I" (S1-07). Small enough to share one module."""

from __future__ import annotations

from uuid import UUID

from common.errors import Unauthorized
from common.ports import Clock
from identity_service.domain.models import User
from identity_service.usecases.ports import SessionRepo, UserRepo


async def sign_out(
    user_id: UUID, session_id: UUID | None, all_sessions: bool, *, sessions: SessionRepo, clock: Clock
) -> None:
    """End this session, or every session of the user (`all_sessions`).

    Ending a session kills its refresh tokens at once. An access token already issued stays valid until
    it expires (at most 15 minutes): that is the price of verifying tokens without a database lookup.
    Idempotent: signing out twice is fine.
    """
    now = clock.now()
    if all_sessions:
        await sessions.revoke_all_sessions(user_id, now)
    elif session_id is not None:
        session = await sessions.get_session(session_id)
        if session is not None and session.user_id == user_id:  # never end someone else's session
            await sessions.revoke_session(session_id, now)


async def get_me(user_id: UUID, *, users: UserRepo) -> User:
    user = await users.get_by_id(user_id)
    if user is None or user.status != "active":
        # The token is valid but the account is gone or suspended: treat as signed out.
        raise Unauthorized("Account is no longer active")
    return user
