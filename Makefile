# RailRoute Optimizer — common developer commands. Run `make help`.
SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend/web

.PHONY: help setup infra-up infra-down migrate backend frontend lint typecheck test \
        test-integration test-e2e test-live purge check format

help: ## Show this help
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

setup: ## Install backend (uv) and frontend (npm) dependencies
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm ci

infra-up: ## Start PostgreSQL + Redis containers
	docker compose up -d postgres redis

infra-down: ## Stop containers (data volumes are kept)
	docker compose down

migrate: ## Apply database migrations (runs as the schema-owning role)
	cd $(BACKEND) && uv run alembic upgrade head

backend: ## Run the API with auto-reload on :8000
	cd $(BACKEND) && uv run uvicorn app.asgi:app --reload --port 8000 --no-proxy-headers

frontend: ## Run the Next.js dev server on :3000
	cd $(FRONTEND) && npm run dev

format: ## Auto-format backend code
	cd $(BACKEND) && uv run ruff format . && uv run ruff check --fix .

lint: ## Lint backend and frontend
	cd $(BACKEND) && uv run ruff format --check . && uv run ruff check .
	cd $(FRONTEND) && npm run -s lint

typecheck: ## Type-check backend (mypy --strict) and frontend (tsc)
	cd $(BACKEND) && uv run mypy
	cd $(FRONTEND) && npm run -s typecheck

test: ## Unit + API tests (no RailKit key, no infrastructure needed)
	cd $(BACKEND) && uv run pytest
	cd $(FRONTEND) && npm run -s test

test-integration: ## PostgreSQL/Redis tests (requires TEST_DATABASE_URL and TEST_REDIS_URL)
	cd $(BACKEND) && uv run pytest -m integration

test-e2e: ## Playwright end-to-end tests (builds the frontend; starts API + web itself)
	cd $(FRONTEND) && npm run build && npx playwright test

purge: ## Apply the data-retention policy (add ARGS="--dry-run" to preview)
	cd $(BACKEND) && uv run python -m app.cli purge $(ARGS)

test-live: ## Live RailKit contract tests — SPENDS REAL QUOTA (docs/09 §5)
	cd $(BACKEND) && RUN_LIVE_RAILKIT_TESTS=true uv run pytest tests/live -m live -v -s

check: lint typecheck test ## Everything CI runs without infrastructure
