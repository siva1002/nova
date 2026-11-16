"""Settings. Environment variables only, validated at startup: a missing or malformed value stops the
service from booting (fail fast), instead of failing on the first request that needs it.

Every service extends `ServiceSettings` in its own `settings.py` with the extras it needs.
Field names map to upper-case env vars: `database_url` <- DATABASE_URL.
Secrets come from the environment (an env file outside Git in production), never from code.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class ServiceSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    service_name: str  # "identity" | "access" | ...: appears in every log line
    environment: str = "local"  # local | production. Some safety checks only relax in "local"
    log_level: str = "INFO"

    # ---- database (own database ONLY; the app login is subject to forced RLS)
    database_url: str
    db_pool_size: int = 10  # per process; see the sizing note in common/db.py
    db_max_overflow: int = 5

    # ---- tokens
    # Issuer written into and required from every access token. Same value in every service.
    token_issuer: str = "work-platform"  # noqa: S105 (a name, not a secret)
    # identity's public keys. Every service except identity verifies tokens against this URL.
    jwks_url: str = ""

    # ---- deployment
    cell_id: str = "aps1-c01"  # the one cell of the MVP (Mumbai); carried in events for sprint 8 routing
    # How many reverse proxies we run in front of the service that append to X-Forwarded-For
    # (production: Caddy -> Envoy). Used to pick the real client IP for rate limiting. 0 = trust no header.
    trusted_proxy_hops: int = 1
    # Browser origins allowed to call the API (comma separated). Empty = no CORS headers at all.
    cors_origins: str = ""

    # ---- other services this one may call. Set only the ones it really needs (see its clients/ folder).
    access_url: str = ""
    hierarchy_url: str = ""
    tasks_url: str = ""
    time_url: str = ""
    # Budget for one call to another service. After this we fail closed (503).
    peer_timeout_seconds: float = 2.0
