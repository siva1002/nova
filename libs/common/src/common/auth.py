"""Access-token (JWT) verification.

Tokens are issued by the identity service, signed with Ed25519 (alg "EdDSA"), and carry:
    iss  the issuer name (settings.token_issuer)        sub  the user id
    sid  the session id (used by sign-out)              email, name  profile snapshot at sign-in
    iat / exp  issued-at and expiry (15 minutes)        header `kid`  which signing key was used

Verification is LOCAL in every service: the public keys (JWKS) are fetched once and cached, so no request
ever calls identity just to check a token. A token that is expired, tampered with, from another issuer, or
signed by an unknown key raises `Unauthorized` (401).

Two verifiers, one `Verifier` protocol:
  RemoteJwksVerifier  every service except identity: downloads identity's /.well-known/jwks.json
  KeySetVerifier      identity itself (keys from its own database) and tests (static keys): no HTTP

Only "EdDSA" is accepted. The algorithm is never taken from the token, which closes the classic
"alg: none" and key-confusion attacks.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

import jwt
from jwt import PyJWK, PyJWKClient
from jwt.exceptions import PyJWKClientConnectionError

from common.errors import DependencyUnavailable, Unauthorized

ALGORITHMS = ["EdDSA"]


@dataclass(frozen=True, slots=True)
class Claims:
    user_id: UUID
    email: str
    name: str
    session_id: UUID | None
    expires_at: int


class Verifier(Protocol):
    async def verify(self, token: str) -> Claims:
        """Return the claims of a valid token; raise Unauthorized otherwise."""
        ...


def decode_token(token: str, key: Any, issuer: str, leeway_seconds: int = 10) -> Claims:
    """Check signature, expiry and issuer with an already-selected public key."""
    try:
        data = jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            issuer=issuer,
            leeway=leeway_seconds,  # tolerates small clock differences between servers
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
        sid = data.get("sid")
        return Claims(
            user_id=UUID(data["sub"]),
            email=str(data.get("email", "")),
            name=str(data.get("name", "")),
            session_id=UUID(sid) if sid else None,
            expires_at=int(data["exp"]),
        )
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise Unauthorized("Invalid or expired token") from exc


class RemoteJwksVerifier:
    """Verifies against a JWKS URL. Keys are cached for 5 minutes and refetched when an unknown `kid`
    appears (that is how a key rotation in identity reaches the other services without a deploy)."""

    def __init__(self, jwks_url: str, issuer: str, leeway_seconds: int = 10) -> None:
        self._jwks = PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=2)
        self._issuer = issuer
        self._leeway = leeway_seconds

    def _verify_sync(self, token: str) -> Claims:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
        except PyJWKClientConnectionError as exc:
            # identity is unreachable and we have no cached key: that is an outage, not a bad token.
            raise DependencyUnavailable("Signing keys are unavailable") from exc
        except jwt.PyJWTError as exc:
            raise Unauthorized("Invalid or expired token") from exc
        return decode_token(token, key.key, self._issuer, self._leeway)

    async def verify(self, token: str) -> Claims:
        # PyJWKClient does blocking HTTP when it must (re)load keys. Run it in a worker thread so the
        # event loop keeps serving other requests meanwhile. With a warm cache this is a few microseconds.
        return await asyncio.to_thread(self._verify_sync, token)


class KeySetVerifier:
    """Verifies against a key set supplied by an async loader (identity: its own signing_keys table).

    The set is cached for `ttl_seconds`. An unknown `kid` triggers one reload, at most every
    `min_reload_seconds`, so a flood of tokens with random kids cannot hammer the database.
    """

    def __init__(
        self,
        load_keys: Callable[[], Awaitable[list[dict[str, Any]]]],
        issuer: str,
        *,
        ttl_seconds: float = 60,
        min_reload_seconds: float = 5,
        leeway_seconds: int = 10,
    ) -> None:
        self._load = load_keys
        self._issuer = issuer
        self._ttl = ttl_seconds
        self._min_reload = min_reload_seconds
        self._leeway = leeway_seconds
        self._keys: dict[str, Any] = {}
        self._loaded_at = float("-inf")
        self._lock = asyncio.Lock()

    async def _reload(self) -> None:
        async with self._lock:  # one loader at a time; the others wait and reuse its result
            if time.monotonic() - self._loaded_at < self._min_reload:
                return
            jwks = await self._load()
            self._keys = {k["kid"]: PyJWK(k).key for k in jwks}
            self._loaded_at = time.monotonic()

    async def verify(self, token: str) -> Claims:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
        except jwt.PyJWTError as exc:
            raise Unauthorized("Invalid or expired token") from exc
        if time.monotonic() - self._loaded_at > self._ttl or kid not in self._keys:
            await self._reload()
        key = self._keys.get(kid) if kid else None
        if key is None:
            raise Unauthorized("Invalid or expired token")
        return decode_token(token, key, self._issuer, self._leeway)
