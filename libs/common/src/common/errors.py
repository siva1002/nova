"""Domain errors. PURE: no web framework, no database.

Use cases and domain rules RAISE these. They never build HTTP responses themselves.
`common.problems` turns them into RFC 9457 problem responses in one single place.

Every error class carries three stable identifiers:
  status  the HTTP status it maps to
  code    the machine code clients switch on, "<area>.<reason>" (contracts/openapi/common.yaml, Problem.code)
  slug    the last part of the problem `type` URL

A service defines its own errors by subclassing the closest class here and overriding `code`/`slug`/`title`
(example: services/identity/src/identity_service/domain/errors.py).
"""

from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status: int = 400
    code: str = "common.bad_request"
    slug: str = "bad-request"
    title: str = "Bad request"

    def __init__(self, detail: str | None = None, **extra: Any) -> None:
        super().__init__(detail or self.title)
        self.detail = detail or self.title
        # Machine-readable extras merged into the problem body, e.g. current_version, retry_after_seconds.
        self.extra = extra


class Unauthorized(DomainError):
    status, code, slug, title = 401, "common.unauthorized", "unauthorized", "Authentication required"


class Forbidden(DomainError):
    status, code, slug, title = 403, "common.forbidden", "forbidden", "You are not allowed to do this"


class NotFound(DomainError):
    # Also used for "exists but you may not see it": never reveal the difference.
    status, code, slug, title = 404, "common.not_found", "not-found", "Not found"


class Conflict(DomainError):
    status, code, slug, title = 409, "common.conflict", "conflict", "Conflict"


class VersionConflict(Conflict):
    """Optimistic concurrency: the client edited an old version. Carries `current_version`."""

    code, slug, title = "common.version_conflict", "version-conflict", "The item changed since you read it"


class Gone(DomainError):
    status, code, slug, title = 410, "common.gone", "gone", "No longer available"


class Unprocessable(DomainError):
    status, code, slug, title = 422, "common.unprocessable", "unprocessable", "The request cannot be processed"


class TooManyRequests(DomainError):
    """Carries `retry_after_seconds` when known; the problem handler also sets the Retry-After header."""

    status, code, slug, title = 429, "common.rate_limited", "too-many-requests", "Too many requests"


class DependencyUnavailable(DomainError):
    """Another service or the database did not answer in time. We fail closed: never 'allow' on a timeout."""

    status, code, slug, title = (
        503,
        "common.dependency_unavailable",
        "dependency-unavailable",
        "A required service is unavailable",
    )
