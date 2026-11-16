# Developer entry points. Run from the repo root.
# On Windows use Git Bash or WSL for `make`, or run the underlying commands by hand.

COMPOSE = docker compose -f deploy/compose/docker-compose.yml --env-file deploy/compose/.env

.PHONY: setup up migrate down reset logs lint fmt types imports test test-int check contracts

setup:            ## first time: install deps, create the local env file, install git hooks
	uv sync --all-packages
	cp -n deploy/compose/.env.example deploy/compose/.env || true
	uv run pre-commit install

up:               ## start PostgreSQL, Envoy, Mailpit and all services
	$(COMPOSE) up -d --build

migrate:          ## run every service's Alembic migrations (after `make up`, and on every deploy)
	for s in identity access hierarchy tasks time; do $(COMPOSE) run --rm $$s alembic upgrade head || exit 1; done

down:
	$(COMPOSE) down

reset:            ## wipe local data and start clean (destroys the local databases)
	$(COMPOSE) down -v
	$(COMPOSE) up -d --build

logs:
	$(COMPOSE) logs -f --tail=100

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

types:
	uv run mypy libs/common/src services/identity/src services/access/src services/hierarchy/src services/tasks/src services/time/src

imports:          ## the independence rules (see root pyproject.toml)
	uv run lint-imports

test:             ## unit tests only: no Docker needed
	uv run pytest -m "not integration"

test-int:         ## integration tests on a real PostgreSQL (bundled pgserver, or PG_TEST_URL). No Docker needed
	uv run pytest -m integration

contracts:        ## validate the OpenAPI and event contracts
	uv run python contracts/validate.py

check: lint types imports test contracts   ## what CI runs on every PR
