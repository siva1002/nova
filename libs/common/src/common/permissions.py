"""Client for access's `checkPermissions` (contracts/openapi/access.yaml,
POST /internal/v1/w/{workspace_id}/authz/check). Used by every service except access itself.

Permission names are the capability keys of the access service (tools/db-split/access.sql, table
`capabilities`): view, edit, create, track_time, manage_users, manage_timesheets ...

MVP: access answers with a role check (Owner / Admin / Member). Sprint 13: the full engine sits behind the
SAME request and response shape, so this client does not change.

FAIL CLOSED: if access times out or errors we raise `DependencyUnavailable` (503). We never "allow" on
failure. The shared httpx client (app.state.http) supplies pooling and the 2 s timeout.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import httpx

from common.context import RequestContext
from common.errors import DependencyUnavailable, Forbidden


class PermissionClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = http

    async def check(
        self,
        ctx: RequestContext,
        permission: str,
        *,
        node_ids: list[UUID] | None = None,
        task_id: UUID | None = None,
        creator_id: UUID | None = None,
        assignee_ids: list[UUID] | None = None,
    ) -> bool:
        check: dict[str, Any] = {"permission": permission}
        if node_ids:
            check["nodeIds"] = [str(n) for n in node_ids]
        if task_id:
            check["taskId"] = str(task_id)
        if creator_id:
            check["creatorId"] = str(creator_id)
        if assignee_ids:
            check["assigneeIds"] = [str(a) for a in assignee_ids]
        headers = {"X-Request-Id": ctx.request_id}
        if ctx.bearer_token:
            headers["Authorization"] = f"Bearer {ctx.bearer_token}"
        try:
            resp = await self._http.post(
                f"{self._base}/internal/v1/w/{ctx.workspace_id}/authz/check",
                json={"userId": str(ctx.user_id), "checks": [check]},
                headers=headers,
            )
            resp.raise_for_status()
            answers = resp.json()
            return answers[0] is True  # anything but a literal true is a "no"
        except (httpx.HTTPError, ValueError, IndexError, TypeError) as exc:
            raise DependencyUnavailable("Permission service did not answer") from exc

    async def require(self, ctx: RequestContext, permission: str, **resource: Any) -> None:
        """Raise Forbidden unless allowed. Use cases call this first, before touching data."""
        if not await self.check(ctx, permission, **resource):
            raise Forbidden(f"Missing permission: {permission}")
