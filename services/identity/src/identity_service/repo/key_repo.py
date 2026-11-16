"""SQL for the public signing keys (implements usecases.ports.KeyRepo). Table: signing_keys.

Only PUBLIC keys are stored. `kms_key_ref` says where the private half lives ("env:SIGNING_PRIVATE_KEY"
in the MVP, a KMS key id from sprint 18).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Any fixed number: all identity processes take the same advisory lock while they publish their key.
_PUBLISH_LOCK = 7_301_001


class SqlKeyRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_published(self) -> list[dict[str, Any]]:
        result = await self._s.execute(
            text(
                "SELECT public_jwk FROM signing_keys "
                "WHERE status IN ('next', 'active') OR (status = 'retiring' AND retire_after > now()) "
                "ORDER BY created_at DESC"
            )
        )
        return [dict(row.public_jwk) for row in result]

    async def publish_active(
        self, kid: str, public_jwk: dict[str, Any], key_ref: str, now: datetime, retire_after: datetime
    ) -> None:
        # Several workers start at once and all call this. The transaction-scoped advisory lock makes them
        # take turns, so the "one active key" unique index is never hit by a race.
        await self._s.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _PUBLISH_LOCK})
        # 1. The key that was active (if it is a different one) keeps verifying old tokens for a while.
        await self._s.execute(
            text(
                "UPDATE signing_keys SET status = 'retiring', retire_after = :retire_after "
                "WHERE status = 'active' AND kid <> :kid"
            ),
            {"kid": kid, "retire_after": retire_after},
        )
        # 2. Insert ours, or re-activate it if this key was used before.
        await self._s.execute(
            text(
                "INSERT INTO signing_keys (kid, algorithm, public_jwk, kms_key_ref, status, created_at) "
                "VALUES (:kid, 'EdDSA', CAST(:jwk AS jsonb), :key_ref, 'active', :now) "
                "ON CONFLICT (kid) DO UPDATE SET status = 'active', retire_after = NULL"
            ),
            {"kid": kid, "jwk": json.dumps(public_jwk), "key_ref": key_ref, "now": now},
        )
