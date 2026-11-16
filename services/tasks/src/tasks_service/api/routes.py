"""HTTP routes of the tasks service. Routes stay thin: context -> transaction -> ONE use case -> response.

Public routes to build here (see contracts/openapi/tasks.yaml, the source of truth):
  /v1/w/{ws}/tasks, /v1/w/{ws}/tasks/{id}, /tasks/{id}/move, /tasks/{id}/position, /tasks/query
"""

from fastapi import APIRouter

router = APIRouter()
