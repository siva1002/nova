"""USE CASES: publish our signing key at startup, and serve the public key set (S1-06).

Other services download GET /.well-known/jwks.json and verify tokens locally. The PRIVATE key never
enters the database; only the public half and a reference to where the private half lives.

ROTATION (already supported by the table and this code)
  Start the service with a new SIGNING_PRIVATE_KEY. The new key becomes 'active'; the previous one becomes
  'retiring' and stays published until every token it signed has expired. Verifiers pick keys by `kid`.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from common.ports import Clock
from identity_service.usecases.ports import KeyRepo, TokenIssuer


async def publish_signing_key(*, keys: KeyRepo, tokens: TokenIssuer, clock: Clock, token_ttl_seconds: int) -> None:
    now = clock.now()
    # A retiring key must outlive the longest-lived token it signed, plus a margin for clock skew.
    retire_after = now + timedelta(seconds=token_ttl_seconds + 300)
    await keys.publish_active(tokens.kid, tokens.public_jwk, tokens.key_ref, now, retire_after)


async def get_jwks(*, keys: KeyRepo) -> dict[str, list[dict[str, Any]]]:
    return {"keys": await keys.list_published()}
