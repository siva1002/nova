"""USE CASE: sign up with email and password (S1-05).

No account probing (contract: identity.yaml signUp): the caller gets the SAME answer whether or not the
email already exists, and it takes the same time. So this use case
  - always hashes the password, even when the email turns out to be taken
  - returns nothing; the route always answers 202
Later (sprint 7) an existing address gets a "you already have an account" email instead of silence.
"""

from __future__ import annotations

from common.ids import new_id
from common.ports import Clock, EventSink
from identity_service.domain.models import SignUp, User
from identity_service.domain.rules import (
    clean_display_name,
    color_for,
    initials_of,
    normalize_email,
    username_from,
    validate_password,
)
from identity_service.usecases.ports import PasswordHasher, UserRepo


def user_event(user: User) -> dict[str, object]:
    """Payload (`data`) of identity.user.* events. No password material, ever."""
    return {
        "after": {
            "id": str(user.id),
            "version": user.version,
            "email": user.email,
            "display_name": user.display_name,
            "initials": user.initials,
            "color": user.color,
            "status": user.status,
        }
    }


async def sign_up(cmd: SignUp, *, users: UserRepo, hasher: PasswordHasher, events: EventSink, clock: Clock) -> None:
    email = normalize_email(cmd.email)  # 1. pure validation first: cheapest, and it writes nothing
    validate_password(cmd.password, email)
    display_name = clean_display_name(cmd.display_name)

    password_hash = await hasher.hash(cmd.password)  # 2. ~50 ms of CPU in a worker thread

    now = clock.now()
    user_id = new_id()
    user = User(
        id=user_id,
        email=email,
        username=username_from(email),
        display_name=display_name,
        initials=initials_of(display_name),
        color=color_for(user_id),
        avatar_url=None,
        timezone=cmd.timezone,
        locale=None,
        email_verified=False,
        status="active",
        version=1,
        created_at=now,
        updated_at=now,
    )
    created = await users.insert_user(user, password_hash)  # 3. race-safe: False if the email exists
    if created:
        events.add("identity.user.created", "user", user.id, user.version, user_event(user))  # 4. outbox
