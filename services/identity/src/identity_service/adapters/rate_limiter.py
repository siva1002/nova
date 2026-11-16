"""In-process fixed-window rate limiter for the auth endpoints, keyed by client IP.

SCOPE AND LIMITS (be honest about what this is)
  It lives in ONE process. With several uvicorn workers or servers each has its own counters, so the
  effective limit is `limit x processes`. That is acceptable for the single-server MVP; sprint 2 replaces
  it with Redis behind the same `hit()` interface. The per-ACCOUNT lockout does not have this weakness:
  it is stored in PostgreSQL (see usecases/sign_in.py).

Fixed window: at most `limit` hits per key per `window_seconds`. Memory is bounded: expired windows are
swept once the table grows past `max_keys`.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class InMemoryRateLimiter:
    def __init__(
        self,
        limit: int,
        window_seconds: int,
        *,
        max_keys: int = 50_000,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window_seconds
        self._max_keys = max_keys
        self._now = monotonic
        self._hits: dict[str, tuple[float, int]] = {}  # key -> (window start, hits in this window)

    def hit(self, key: str) -> int | None:
        """Count one request. Returns None if allowed, or the seconds to wait if over the limit."""
        now = self._now()
        start, count = self._hits.get(key, (now, 0))
        if now - start >= self._window:
            start, count = now, 0  # the old window ended: start a fresh one
        count += 1
        self._hits[key] = (start, count)
        if len(self._hits) > self._max_keys:
            self._sweep(now)
        if count > self._limit:
            return max(1, int(self._window - (now - start)) + 1)
        return None

    def _sweep(self, now: float) -> None:
        self._hits = {k: v for k, v in self._hits.items() if now - v[0] < self._window}
