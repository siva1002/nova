"""Settings for the identity service (env vars; see common.config.ServiceSettings for the shared ones)."""

from common.config import ServiceSettings


class Settings(ServiceSettings):
    # ---- token signing
    # Base64url of the 32-byte Ed25519 private seed. Generate one with:  python tools/gen_signing_key.py
    # REQUIRED outside "local". In "local" an empty value means: generate a throw-away key at startup
    # (every restart then invalidates existing tokens, which is fine on a laptop and fatal in production).
    # Sprint 18 moves the private key into the cloud key service (KMS); only this setting changes.
    signing_private_key: str = ""
    access_token_ttl_seconds: int = 900  # 15 minutes: short, because access tokens cannot be revoked

    # ---- sessions and refresh tokens
    refresh_idle_days: int = 30  # a session unused this long ends
    session_absolute_days: int = 90  # hard cap, however active the session is
    refresh_cookie_name: str = "refresh_token"
    # "lax" works when the web app and the API share a site (app.example.com + api.example.com).
    # Use "none" only if they are on different sites, and then add a CSRF defence on /v1/auth/refresh.
    refresh_cookie_samesite: str = "lax"

    # ---- brute-force protection
    max_failed_sign_ins: int = 10  # wrong passwords in a row before the account locks
    lockout_minutes: int = 15
    ip_rate_limit: int = 30  # auth requests per IP per window (in-process; Redis in sprint 2)
    ip_rate_window_seconds: int = 60

    # ---- password hashing (Argon2id). Defaults follow RFC 9106 "low memory": 64 MiB, 3 passes, 4 lanes.
    argon2_time_cost: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 4
    # Each hash holds argon2_memory_kib of RAM for ~50 ms. This caps how many run at once per process, so a
    # burst of sign-ins cannot exhaust memory (the others wait their turn instead of failing).
    hash_concurrency: int = 4

    @property
    def cookie_secure(self) -> bool:
        return self.environment != "local"  # plain http://localhost needs a non-Secure cookie
