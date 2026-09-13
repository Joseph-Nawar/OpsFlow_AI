# Development Guide

## Status of this guide

This repository currently contains documentation only. Commands in this guide are planned conventions derived from the approved roadmap. They are not verified until the relevant project tooling is introduced and the command is run successfully in this repository.

## Working principles

- Keep the production-grade portfolio project understandable and locally demonstrable.
- Implement only the current phase and avoid future-phase scaffolding.
- Prefer explicit domain behavior over hidden prompt behavior or speculative abstractions.
- Keep AI, workflow orchestration, deterministic business logic, and external side effects behind clear boundaries.
- Use synthetic data and safe test doubles by default.

## Source-of-truth order

1. The active user request or phase brief defines current scope.
2. `docs/roadmap/project-roadmap.md` defines approved product and engineering scope.
3. `docs/architecture/system-overview.md` defines the two authority boundaries.
4. This guide defines repository conventions and planned workflow.
5. Implemented code and tests define behavior that already exists.

Conflicts must be surfaced and resolved explicitly. A later implementation must not silently change the roadmap’s meaning.

## Branches and commits

Work on the designated phase branch. Keep commits coherent and narrowly scoped. Before committing:

1. inspect `git status` and the diff;
2. confirm no unrelated files are included;
3. run the applicable checks;
4. review for secrets, generated files, and future-phase leakage;
5. commit with a concise message describing the milestone.

The closeout report must identify the branch, HEAD, commits created, files changed, and working-tree state.

## Planned repository conventions

The intended baseline is Python 3.12 for backend and business logic, `uv` with `pyproject.toml` and `uv.lock` for Python dependency management, FastAPI for HTTP boundaries, Pydantic v2 for typed input/output models, SQLAlchemy 2.x and Alembic for persistence, PostgreSQL as the application store, React/TypeScript/Vite for the review UI, and self-hosted n8n for orchestration. The exact internal folders should be created only when their responsibilities become necessary.

Expected future top-level areas are described by the roadmap, including `src/opsflow/`, `web/`, `workflows/n8n/`, `tests/`, `evals/`, `fixtures/`, `migrations/`, `infra/`, and Docker/packaging files. They are intentionally absent until an applicable phase requires them.

## Planned commands

These commands are the expected shape of the development workflow after the corresponding tools exist. They are documentation of intent, not verified commands for the current repository.

```bash
# Backend dependency and quality checks — planned after M0B creates pyproject.toml and uv.lock
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
uv run pytest

# Frontend checks — planned after the frontend skeleton exists
cd web
npm ci
npm run lint
npm run build

# Local services and migrations — planned after Docker and PostgreSQL exist
docker compose up --build
alembic upgrade head

# Focused verification — use the project’s eventual documented test selectors
pytest tests/unit -q
pytest tests/integration -q
```

Do not report any command as passing until its output has been observed in the current repository. If a command is not applicable to a documentation-only milestone, record that fact rather than fabricating a result.

## Testing approach

For deterministic business behavior, follow the red-green-refactor loop where practical:

1. write a focused failing test;
2. confirm the failure is for the expected reason;
3. implement the smallest behavior that satisfies the test;
4. run the focused test and the relevant broader suite;
5. refactor only when the behavior remains covered and the change is justified.

Tests must not remove assertions, change expected results to suit broken behavior, or skip coverage without an explicit reason. Live AI calls and real external side effects must never be hidden in ordinary automated tests.

This bootstrap milestone has no application behavior, so it does not invent unit or integration tests. Its verification is repository inspection, Markdown/link validation, roadmap consistency review, secret scanning, and Git-state checks.

## Documentation conventions

- Use Markdown headings that reflect the document hierarchy.
- Link to repository files with relative links.
- State whether a component is planned, implemented, or verified.
- Keep architecture decisions and phase scope durable and reviewable.
- Use examples only when they clarify a current contract; do not use examples to smuggle in future functionality.

## Security and cost conventions

Never commit `.env` files, API keys, credentials, private customer data, or real business documents. Use `.env.example` only when a future phase needs it and keep values non-secret. Prefer local/open-source infrastructure, free developer environments, adapters, test doubles, and synthetic data. Optional paid AI calls must not become a required development dependency.

## Phase workflow

Every implementation phase follows the roadmap’s completion protocol:

1. plan exact scope, files, interfaces, tests, commands, non-goals, and exit criteria;
2. implement minimally on the designated branch;
3. run applicable quality gates and manual verification;
4. provide the required Codex report;
5. perform senior review for architecture, scope, tests, security, and unnecessary complexity;
6. mark the phase complete only after review passes.

The phase report must include implementation, architecture decisions, dependencies, tests and results, quality gates, manual verification, deviations, known limitations, and security/cost notes.
