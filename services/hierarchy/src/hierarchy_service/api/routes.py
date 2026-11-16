"""HTTP routes of the hierarchy service. Routes stay thin: context -> transaction -> ONE use case -> response.

Public routes to build here (see contracts/openapi/hierarchy.yaml, the source of truth):
  /v1/w/{ws}/{tree,spaces,folders,lists,nodes,...}, /internal/v1/w/{ws}/seed
"""

from fastapi import APIRouter

router = APIRouter()
