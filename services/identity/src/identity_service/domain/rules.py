"""Business rules of identity. PURE: values in, values or domain errors out. No I/O, no clock reads."""

from __future__ import annotations

import hashlib
import re
from uuid import UUID

from identity_service.domain.errors import InvalidDisplayName, InvalidEmail, WeakPassword

PASSWORD_MIN, PASSWORD_MAX = 12, 128  # contracts/openapi/identity.yaml
DISPLAY_NAME_MAX = 120
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

# Avatar background colours handed out to new users (stable per user id).
_COLORS = ("#7B68EE", "#0091FF", "#00B884", "#FFAB00", "#FF5C5C", "#E040FB", "#00BCD4", "#8D6E63")


def normalize_email(raw: str) -> str:
    """Trim and lower-case. Lookups are case-insensitive (unique index on lower(email))."""
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL.match(email):
        raise InvalidEmail()
    return email


def validate_password(password: str, email: str) -> None:
    """Length is what matters (NIST 800-63B): no forced symbols or digits. Also refuse the obvious."""
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise WeakPassword(f"Password must be {PASSWORD_MIN} to {PASSWORD_MAX} characters long")
    if not password.strip():
        raise WeakPassword("Password cannot be only spaces")
    lowered = password.lower()
    if lowered == email.lower() or lowered == email.split("@")[0].lower():
        raise WeakPassword("Password cannot be your email address")


def clean_display_name(raw: str) -> str:
    name = " ".join(raw.split())  # trim and collapse inner whitespace
    if not name or len(name) > DISPLAY_NAME_MAX:
        raise InvalidDisplayName()
    return name


def initials_of(display_name: str) -> str:
    """'Asha Rao' -> 'AR', 'asha' -> 'A'. At most two letters."""
    parts = display_name.split()
    letters = parts[0][:1] + (parts[-1][:1] if len(parts) > 1 else "")
    return letters.upper()


def color_for(user_id: UUID) -> str:
    return _COLORS[user_id.int % len(_COLORS)]


def username_from(email: str) -> str:
    """Default @handle: the part before the @. Not unique by design (the id is the identifier)."""
    return email.split("@")[0][:60]


def hash_refresh_token(raw: str) -> bytes:
    """Refresh tokens are 256 bits of randomness, so a plain SHA-256 is enough (no salt, no slow hash).
    Storing only the hash means a database leak does not leak usable tokens."""
    return hashlib.sha256(raw.encode("utf-8")).digest()
