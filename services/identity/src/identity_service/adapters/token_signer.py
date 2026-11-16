"""Ed25519 access-token signing (implements usecases.ports.TokenIssuer).

Ed25519 ("EdDSA"): small keys, fast, and no parameters to get wrong. The PRIVATE key lives only in this
process's memory (from the SIGNING_PRIVATE_KEY env var; KMS in sprint 18). The PUBLIC key is published
as a JWK so every other service can verify tokens without calling us.

`kid` is the RFC 7638 thumbprint of the public key: the same key always gets the same id, on every
instance, with no coordination.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
from datetime import datetime
from typing import Any
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from identity_service.domain.models import User

log = logging.getLogger(__name__)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


class Ed25519Signer:
    def __init__(self, private_key: Ed25519PrivateKey, *, issuer: str, ttl_seconds: int, key_ref: str) -> None:
        self._key = private_key
        self._issuer = issuer
        self._ttl = ttl_seconds
        self.key_ref = key_ref  # where the private half lives; stored next to the public key, for operators
        public = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        x = _b64url(public)
        # RFC 7638: SHA-256 over the required members, sorted by name, no whitespace.
        canonical = json.dumps({"crv": "Ed25519", "kty": "OKP", "x": x}, separators=(",", ":"), sort_keys=True)
        self.kid = _b64url(hashlib.sha256(canonical.encode("ascii")).digest())
        self.public_jwk: dict[str, Any] = {
            "kty": "OKP",
            "crv": "Ed25519",
            "x": x,
            "kid": self.kid,
            "use": "sig",
            "alg": "EdDSA",
        }

    @classmethod
    def from_settings(cls, seed_b64: str, *, environment: str, issuer: str, ttl_seconds: int) -> Ed25519Signer:
        """Load the key from configuration. Refuses to start without one outside local development."""
        if seed_b64:
            try:
                seed = base64.urlsafe_b64decode(seed_b64 + "=" * (-len(seed_b64) % 4))
                key = Ed25519PrivateKey.from_private_bytes(seed)
            except Exception as exc:
                # Never echo the value: it is a secret.
                raise RuntimeError("SIGNING_PRIVATE_KEY is not a base64url 32-byte Ed25519 seed") from exc
            return cls(key, issuer=issuer, ttl_seconds=ttl_seconds, key_ref="env:SIGNING_PRIVATE_KEY")
        if environment != "local":
            raise RuntimeError("SIGNING_PRIVATE_KEY is required outside local development")
        log.warning("SIGNING_PRIVATE_KEY is empty: using a throw-away key (tokens die on restart)")
        return cls(Ed25519PrivateKey.generate(), issuer=issuer, ttl_seconds=ttl_seconds, key_ref="ephemeral:local")

    def issue(self, user: User, session_id: UUID, now: datetime) -> tuple[str, int]:
        issued_at = int(now.timestamp())
        claims = {
            "iss": self._issuer,
            "sub": str(user.id),
            "sid": str(session_id),  # lets sign-out end exactly this session
            "email": user.email,
            "name": user.display_name,
            "iat": issued_at,
            "exp": issued_at + self._ttl,
        }
        token = jwt.encode(claims, self._key, algorithm="EdDSA", headers={"kid": self.kid})
        return token, self._ttl
