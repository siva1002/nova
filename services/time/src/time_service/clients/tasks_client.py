"""Client for the TASKS service: 'does this task exist and can this user see it?' (contract: tasks.yaml getTask).

Rules for every cross-service client (docs/adr/0004): 2 s timeout, forward Authorization + X-Request-Id,
fail closed, never import the other service's package. Sprint 3 replaces this call with a local task copy
fed by events; the TasksClient Protocol stays, so use cases do not change.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from common.context import RequestContext
from common.errors import DependencyUnavailable, NotFound
from time_service.domain.models import TaskRef


class HttpTasksClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self._base = base_url.rstrip("/")
        self._http = http  # the shared pooled client (app.state.http): keep-alive, 2 s timeout

    async def get_task(self, ctx: RequestContext, task_id: UUID) -> TaskRef:
        headers = {"X-Request-Id": ctx.request_id}
        if ctx.bearer_token:
            headers["Authorization"] = f"Bearer {ctx.bearer_token}"
        try:
            resp = await self._http.get(f"{self._base}/v1/w/{ctx.workspace_id}/tasks/{task_id}", headers=headers)
        except httpx.HTTPError as exc:
            raise DependencyUnavailable("Tasks service did not answer") from exc
        if resp.status_code in (403, 404):
            raise NotFound("Task not found")  # never reveal "exists but hidden"
        if resp.status_code != 200:
            raise DependencyUnavailable(f"Tasks service returned {resp.status_code}")
        body = resp.json()
        return TaskRef(id=UUID(body["id"]), list_id=UUID(body["homeListId"]))
