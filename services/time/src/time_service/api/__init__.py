"""HTTP ONLY. Routes, request/response schemas, auth dependencies.

Each route: build the context, open ONE transaction, call ONE use case, map the result to a response.
NO business logic here. If you are writing an `if` about the business, it belongs in domain/ or usecases/.
May import: usecases, domain, repo, clients, common (including common.web, FastAPI)."""
