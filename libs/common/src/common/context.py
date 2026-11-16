"""RequestContext: who is asking, in which workspace. PURE (no web, no database).

Built ONCE per request in the api/ layer (common.web.get_ctx, from the verified token and the URL) and
passed down to use cases. Use cases never read headers or globals; they only read this object.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class RequestContext:
    user_id: UUID
    workspace_id: UUID
    request_id: str
    # Raw bearer token, forwarded on calls to other services so they apply the same identity.
    bearer_token: str | None = None
    # Profile snapshot from the token (taken at sign-in). Good enough to label things; not for security
    # decisions other than "the email this user signed in with".
    email: str = ""
    display_name: str = ""
