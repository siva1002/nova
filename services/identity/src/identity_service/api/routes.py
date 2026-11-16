"""HTTP routes of the identity service (contract: contracts/openapi/identity.yaml).

Every route is thin: throttle -> open ONE transaction -> call ONE use case -> build the response.

  POST /v1/auth/sign-up        202 always (no account probing)                        S1-05
  POST /v1/auth/sign-in        200 access token + refresh cookie | 401 | 429          S1-06
  GET  /.well-known/jwks.json  public signing keys                                    S1-06
  POST /v1/auth/refresh        rotate the refresh cookie, new access token | 401      S1-07
  POST /v1/auth/sign-out       204, ends this session (or all with ?all=true)         S1-07
  GET  /v1/me                  the signed-in user's profile                           S1-07

Not built yet (sprint 7): verify-email, forgot/reset password, PATCH /v1/me, change password,
session list. GET /v1/me/workspaces is served by the access service in the MVP.

THE REFRESH TOKEN travels only in an HttpOnly cookie scoped to /v1/auth: page JavaScript can never read
it (so XSS cannot steal it), and the browser sends it to no other path.
"""

from __future__ import annotations

import ipaddress
import secrets
from dataclasses import dataclass

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from common.auth import Claims
from common.ports import Clock
from common.web import client_ip, get_claims, global_transaction
from identity_service.adapters.password_hasher import Argon2Hasher
from identity_service.adapters.rate_limiter import InMemoryRateLimiter
from identity_service.adapters.token_signer import Ed25519Signer
from identity_service.api.schemas import SignInIn, SignUpIn, TokensOut, UserOut
from identity_service.domain.errors import RateLimited
from identity_service.domain.models import IssuedTokens, SessionPolicy
from identity_service.repo.key_repo import SqlKeyRepo
from identity_service.repo.session_repo import SqlSessionRepo
from identity_service.repo.user_repo import SqlUserRepo
from identity_service.settings import Settings
from identity_service.usecases.refresh_session import refresh_session
from identity_service.usecases.session_ops import get_me, sign_out
from identity_service.usecases.sign_in import Denied, sign_in
from identity_service.usecases.sign_up import sign_up
from identity_service.usecases.signing_keys import get_jwks

router = APIRouter()
_COOKIE_PATH = "/v1/auth"


@dataclass(frozen=True, slots=True)
class Deps:
    """The service's long-lived collaborators, built once in main.py and kept on app.state.deps."""

    settings: Settings
    hasher: Argon2Hasher
    signer: Ed25519Signer
    limiter: InMemoryRateLimiter
    policy: SessionPolicy
    clock: Clock


def _deps(request: Request) -> Deps:
    deps: Deps = request.app.state.deps
    return deps


def _new_refresh_secret() -> str:
    return secrets.token_urlsafe(32)  # 256 bits from the OS random source


def _throttle(request: Request) -> None:
    """Per-IP limit on the unauthenticated auth endpoints. Runs before any hashing or database work."""
    wait = _deps(request).limiter.hit(client_ip(request))
    if wait is not None:
        raise RateLimited(retry_after_seconds=wait)


def _ip_for_storage(request: Request) -> str | None:
    """Only a syntactically valid address goes into the inet column; anything else is stored as NULL."""
    try:
        return str(ipaddress.ip_address(client_ip(request)))
    except ValueError:
        return None


def _set_refresh_cookie(response: Response, deps: Deps, issued: IssuedTokens) -> None:
    max_age = max(0, int((issued.refresh_expires_at - deps.clock.now()).total_seconds()))
    response.set_cookie(
        deps.settings.refresh_cookie_name,
        issued.refresh_token,
        max_age=max_age,
        path=_COOKIE_PATH,
        httponly=True,  # not readable from JavaScript
        secure=deps.settings.cookie_secure,  # HTTPS only (relaxed for http://localhost)
        samesite=deps.settings.refresh_cookie_samesite,  # type: ignore[arg-type]
    )


def _clear_refresh_cookie(response: Response, deps: Deps) -> None:
    response.delete_cookie(
        deps.settings.refresh_cookie_name,
        path=_COOKIE_PATH,
        httponly=True,
        secure=deps.settings.cookie_secure,
        samesite=deps.settings.refresh_cookie_samesite,  # type: ignore[arg-type]
    )


@router.post("/v1/auth/sign-up", status_code=202)
async def post_sign_up(body: SignUpIn, request: Request) -> Response:
    _throttle(request)
    deps = _deps(request)
    async with global_transaction(request) as tx:
        await sign_up(
            body.to_cmd(), users=SqlUserRepo(tx.session), hasher=deps.hasher, events=tx.events, clock=deps.clock
        )
    return Response(status_code=202)  # same answer whether or not the email already existed


@router.post("/v1/auth/sign-in", response_model=TokensOut)
async def post_sign_in(body: SignInIn, request: Request, response: Response) -> TokensOut:
    _throttle(request)
    deps = _deps(request)
    async with global_transaction(request) as tx:
        outcome = await sign_in(
            body.email,
            body.password,
            users=SqlUserRepo(tx.session),
            sessions=SqlSessionRepo(tx.session),
            hasher=deps.hasher,
            tokens=deps.signer,
            clock=deps.clock,
            policy=deps.policy,
            new_secret=_new_refresh_secret,
            ip=_ip_for_storage(request),
            user_agent=request.headers.get("user-agent"),
        )
    # The transaction is committed here, so a counted failure / lockout is saved even though we now raise.
    if isinstance(outcome, Denied):
        raise outcome.error
    _set_refresh_cookie(response, deps, outcome)
    return TokensOut.from_issued(outcome)


@router.post("/v1/auth/refresh", response_model=TokensOut)
async def post_refresh(request: Request, response: Response) -> TokensOut:
    _throttle(request)
    deps = _deps(request)
    async with global_transaction(request) as tx:
        outcome = await refresh_session(
            request.cookies.get(deps.settings.refresh_cookie_name),
            users=SqlUserRepo(tx.session),
            sessions=SqlSessionRepo(tx.session),
            tokens=deps.signer,
            clock=deps.clock,
            policy=deps.policy,
            new_secret=_new_refresh_secret,
        )
    if isinstance(outcome, Denied):  # committed first: a detected reuse has already revoked the session
        raise outcome.error
    _set_refresh_cookie(response, deps, outcome)
    return TokensOut.from_issued(outcome)


@router.post("/v1/auth/sign-out", status_code=204)
async def post_sign_out(request: Request, all: bool = False, claims: Claims = Depends(get_claims)) -> Response:
    deps = _deps(request)
    async with global_transaction(request, user_id=claims.user_id) as tx:
        await sign_out(claims.user_id, claims.session_id, all, sessions=SqlSessionRepo(tx.session), clock=deps.clock)
    response = Response(status_code=204)
    _clear_refresh_cookie(response, deps)
    return response


@router.get("/v1/me", response_model=UserOut)
async def read_me(request: Request, claims: Claims = Depends(get_claims)) -> UserOut:
    async with global_transaction(request, user_id=claims.user_id) as tx:
        user = await get_me(claims.user_id, users=SqlUserRepo(tx.session))
    return UserOut.from_domain(user)


@router.get("/.well-known/jwks.json")
async def read_jwks(request: Request) -> JSONResponse:
    async with global_transaction(request) as tx:
        jwks = await get_jwks(keys=SqlKeyRepo(tx.session))
    # Public and cacheable: verifiers and proxies may keep it for 5 minutes.
    return JSONResponse(jwks, headers={"Cache-Control": "public, max-age=300"})
