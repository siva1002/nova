"""Business rules for workspaces and invites. PURE: values in, values or domain errors out."""

from __future__ import annotations

import base64
import binascii
import hashlib
import re
from uuid import UUID

from access_service.domain.errors import InvalidWorkspace, InviteGone

WORKSPACE_NAME_MAX = 120
_SLUG = re.compile(r"^[a-z0-9-]{3,40}$")  # contracts/openapi/access.yaml createWorkspace
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")

INVITE_TTL_DAYS = 7
INVITE_BATCH_MAX = 100
INVITABLE_ROLES = frozenset({"admin", "member"})  # guests arrive with node grants in sprint 12
_SECRET_BYTES = 32


def clean_workspace_name(raw: str) -> str:
    name = " ".join(raw.split())  # trim and collapse inner whitespace
    if not name or len(name) > WORKSPACE_NAME_MAX:
        raise InvalidWorkspace(f"Workspace name must be 1 to {WORKSPACE_NAME_MAX} characters")
    return name


def clean_slug(raw: str) -> str:
    slug = raw.strip().lower()
    if not _SLUG.match(slug):
        raise InvalidWorkspace("Workspace address must be 3 to 40 characters: a-z, 0-9 and '-'")
    return slug


def normalize_email(raw: str) -> str | None:
    """Lower-cased email, or None if it does not look like one."""
    email = raw.strip().lower()
    return email if len(email) <= 254 and _EMAIL.match(email) else None


# ----------------------------------------------------------------------------------------- invite tokens
# The token in an invite link is  base64url( workspace id (16 bytes) + random secret (32 bytes) ).
# Why the workspace id is inside: accepting an invite is the one request that arrives WITHOUT a workspace
# in the URL, yet the invites table is protected by row-level security per workspace. Reading the id from
# the token lets us scope the transaction to that workspace instead of bypassing the protection.
# The id is not a secret; the 256-bit secret is. Only the SHA-256 of the whole token is stored.


def encode_invite_token(workspace_id: UUID, secret: bytes) -> str:
    if len(secret) != _SECRET_BYTES:
        raise ValueError("invite secret must be 32 bytes")
    return base64.urlsafe_b64encode(workspace_id.bytes + secret).rstrip(b"=").decode("ascii")


def decode_invite_token(token: str) -> UUID:
    """Return the workspace id inside the token. Anything malformed is simply a dead link (410)."""
    try:
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
    except (binascii.Error, ValueError) as exc:
        raise InviteGone() from exc
    if len(raw) != 16 + _SECRET_BYTES:
        raise InviteGone()
    return UUID(bytes=raw[:16])


def hash_invite_token(token: str) -> str:
    return hashlib.sha256(token.encode("ascii", errors="replace")).hexdigest()
