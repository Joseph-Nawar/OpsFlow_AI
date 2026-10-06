.PHONY: test test-integration lint format typecheck backend-check frontend-check dependency-audit frontend-audit security-audit check up down migrate

UV ?= uv
NPM ?= npm
COMPOSE ?= docker compose

# PostgreSQL must already be available for the full suite and integration tests.
test:
	$(UV) run pytest

test-integration:
	$(UV) run pytest tests/integration -q --no-cov

lint:
	$(UV) run ruff check .

# This is intentionally a non-mutating formatting check.
format:
	$(UV) run ruff format --check .

typecheck:
	$(UV) run mypy src/opsflow

backend-check: lint format typecheck test
	$(UV) build

frontend-check:
	$(NPM) --prefix web ci
	$(NPM) --prefix web test -- --run
	$(NPM) --prefix web run lint
	$(NPM) --prefix web run build

dependency-audit:
	./scripts/audit-production-dependencies.sh

frontend-audit:
	$(NPM) audit --omit=dev --audit-level=high --prefix web

security-audit: dependency-audit frontend-audit

check: backend-check frontend-check

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

migrate:
	$(UV) run alembic upgrade head
