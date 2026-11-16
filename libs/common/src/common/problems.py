"""RFC 9457 problem responses. The ONE place where a DomainError becomes HTTP.

Every service calls `install_error_handlers(app)` once (done by common.web.create_service_app). After that,
use cases just `raise`. The body follows contracts/openapi/common.yaml `Problem`:

    { "type": "<url>", "title": "...", "status": 409, "code": "common.version_conflict",
      "detail": "...", "traceId": "<request id>", ...extras }

Unexpected exceptions are logged in full and answered with a bare 500: internals never reach the client.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from common.errors import DomainError

# TODO(S1-21): replace with the real public domain once it is registered.
PROBLEM_BASE = "https://errors.example.com/problems/"
log = logging.getLogger(__name__)


def problem(
    status: int, slug: str, code: str, title: str, detail: str, request_id: str | None, **extra: Any
) -> JSONResponse:
    body = {
        "type": PROBLEM_BASE + slug,
        "title": title,
        "status": status,
        "code": code,
        "detail": detail,
        "traceId": request_id,
        **extra,
    }
    headers = {}
    retry_after = extra.get("retry_after_seconds")
    if retry_after is not None:
        headers["Retry-After"] = str(int(retry_after))  # standard header, so generic clients back off too
    return JSONResponse(body, status_code=status, media_type="application/problem+json", headers=headers)


def _request_id(request: Request) -> str | None:
    # Set by the request-id middleware in common.web (falls back to the incoming header).
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(request: Request, exc: DomainError) -> JSONResponse:
        return problem(exc.status, exc.slug, exc.code, exc.title, exc.detail, _request_id(request), **exc.extra)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Shape from the contract: errors[] of {field, code}. The field path skips the leading "body"/"query".
        errors = [
            {"field": ".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]), "code": e["type"]}
            for e in exc.errors()
        ]
        return problem(
            422,
            "validation-failed",
            "common.validation_failed",
            "Validation failed",
            "The request body, path or query is invalid",
            _request_id(request),
            errors=errors,
        )

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")  # full detail goes to the log, never to the client
        return problem(
            500,
            "internal-error",
            "common.internal_error",
            "Internal error",
            "Something went wrong",
            _request_id(request),
        )
