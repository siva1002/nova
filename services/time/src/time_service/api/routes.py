"""HTTP routes of the time service. Thin: context -> transaction -> ONE use case -> response.

Built so far: create and edit a manual entry (S1-19).
Still to build here (contract first: write contracts/openapi/time.yaml, MVP part, before more code):
  DELETE /v1/w/{ws}/time-entries/{id}       soft delete (deleted_at), own entries only            S1-19
  GET    /v1/w/{ws}/tasks/{id}/time-entries list entries of a task                                 S1-19
  GET    /v1/w/{ws}/time-entries/totals?taskIds=...   hours per task, many at once                 S1-20
  GET    /v1/w/{ws}/time/mine?from=&to=     my entries for a date range, with a total per day      S1-20
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request

from common.clock import SystemClock
from common.context import RequestContext
from common.web import get_ctx, transaction
from time_service.api.schemas import EntryIn, EntryOut, EntryPatch
from time_service.repo.time_repo import TimeRepo
from time_service.usecases.create_entry import create_entry
from time_service.usecases.update_entry import update_entry

router = APIRouter(prefix="/v1/w/{workspace_id}", tags=["time"])
_clock = SystemClock()


@router.post("/time-entries", response_model=EntryOut, status_code=201)
async def post_entry(body: EntryIn, request: Request, ctx: RequestContext = Depends(get_ctx)) -> EntryOut:
    async with transaction(request, ctx) as tx:  # one DB transaction, scoped to this workspace
        entry = await create_entry(
            ctx,
            body.to_cmd(),
            repo=TimeRepo(tx.session),
            tasks=request.app.state.tasks,
            perms=request.app.state.perms,
            events=tx.events,
            clock=_clock,
        )
    return EntryOut.from_domain(entry)  # built AFTER the commit


@router.patch("/time-entries/{entry_id}", response_model=EntryOut)
async def patch_entry(
    entry_id: UUID, body: EntryPatch, request: Request, ctx: RequestContext = Depends(get_ctx)
) -> EntryOut:
    async with transaction(request, ctx) as tx:
        entry = await update_entry(
            ctx,
            entry_id,
            body.to_changes(),
            repo=TimeRepo(tx.session),
            perms=request.app.state.perms,
            events=tx.events,
            clock=_clock,
        )
    return EntryOut.from_domain(entry)
