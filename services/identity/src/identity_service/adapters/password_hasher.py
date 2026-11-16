"""Argon2id password hashing (implements usecases.ports.PasswordHasher).

WHY A THREAD AND A SEMAPHORE
  Hashing is deliberately slow CPU work (~50 ms) that uses 64 MiB of memory. Run inline it would freeze
  the event loop, and every other request with it. So each hash runs in a worker thread
  (`asyncio.to_thread`; argon2 releases the GIL), and a semaphore caps how many run at once, so a burst
  of sign-ins queues briefly instead of exhausting memory or starving other requests of CPU.

The stored string is self-describing ($argon2id$v=19$m=65536,t=3,p=4$salt$hash): salt and parameters
travel with it, which is what makes `needs_rehash` possible when we raise the parameters later.
"""

from __future__ import annotations

import asyncio
import secrets

from argon2 import PasswordHasher as _Argon2
from argon2.exceptions import InvalidHashError, VerificationError


class Argon2Hasher:
    def __init__(self, *, time_cost: int, memory_kib: int, parallelism: int, max_concurrency: int) -> None:
        self._argon2 = _Argon2(time_cost=time_cost, memory_cost=memory_kib, parallelism=parallelism)
        self._slots = asyncio.Semaphore(max_concurrency)
        # A real hash of a random password nobody knows. `burn` verifies against it, so "unknown email"
        # costs exactly as much as "wrong password".
        self._dummy_hash = self._argon2.hash(secrets.token_urlsafe(32))

    async def hash(self, password: str) -> str:
        async with self._slots:
            return await asyncio.to_thread(self._argon2.hash, password)

    def _verify_sync(self, password_hash: str, password: str) -> bool:
        try:
            return self._argon2.verify(password_hash, password)
        except (VerificationError, InvalidHashError):
            return False  # wrong password, or a corrupt hash: both are simply "no"

    async def verify(self, password_hash: str, password: str) -> bool:
        async with self._slots:
            return await asyncio.to_thread(self._verify_sync, password_hash, password)

    async def burn(self, password: str) -> None:
        await self.verify(self._dummy_hash, password)

    def needs_rehash(self, password_hash: str) -> bool:
        return self._argon2.check_needs_rehash(password_hash)
