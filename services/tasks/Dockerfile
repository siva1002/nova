# Image for the tasks service. Build context = repo ROOT (see deploy/compose/docker-compose.yml).
# Contains ONLY this service, libs/common and their pinned dependencies (uv.lock).
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.31 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY libs/common libs/common
COPY services/tasks services/tasks
RUN uv sync --frozen --no-dev --package tasks-service

FROM python:3.12-slim
RUN useradd --system --uid 10001 app
WORKDIR /app/services/tasks
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
# Migrations are a separate step:  docker compose run --rm tasks alembic upgrade head
CMD ["uvicorn", "tasks_service.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
