"""Client for the HIERARCHY service: seed the first space of a new workspace
(contract: contracts/openapi/hierarchy.yaml, operationId seedWorkspace, built in task S1-11).

This is the single place where access WRITES to another service, and it is allowed only because the
endpoint is idempotent (docs/adr/0004): calling it twice creates nothing twice, so a retry is always safe.

Rules for every cross-service client: the shared pooled httpx client (2 s timeout), forward Authorization
and X-Request-Id, fail closed with DependencyUnavailable, never import the other service's package.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from common.errors import DependencyUnavailable
from common.logging import request_id_var


class HttpHierarchyClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = http

    async def seed_workspace(self, workspace_id: UUID, owner_user_id: UUID, bearer_token: str | None) -> None:
        headers = {}
        if request_id := request_id_var.get():
            headers["X-Request-Id"] = request_id  # the same id follows the request into hierarchy's logs
        if bearer_token:
            headers["Authorization"] = f"Bearer {bearer_token}"
        try:
            resp = await self._http.post(
                f"{self._base}/internal/v1/w/{workspace_id}/seed",
                json={"ownerUserId": str(owner_user_id)},
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise DependencyUnavailable("Hierarchy service did not answer") from exc
        if resp.status_code >= 300:
            # Includes 404 while hierarchy does not have the endpoint yet: the workspace stays 'provisioning'.
            raise DependencyUnavailable(f"Hierarchy service returned {resp.status_code}")
