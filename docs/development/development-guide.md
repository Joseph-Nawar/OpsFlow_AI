# Development Guide

## Status of this guide

This repository contains the M0A documentation baseline, the M0B minimal Python/FastAPI backend, the M0C PostgreSQL/SQLAlchemy/Alembic/Docker foundation, the M0D minimal React/TypeScript/Vite frontend foundation, the M0E developer-workflow/CI foundation, and the M0F independent Phase 0 audit. M1A added the authoritative Phase 1 domain contract and implementation plan; M1B–M1E added and verified the supporting domain records, immutable Order aggregate, state-machine and retry/reopen behavior, and scenario hardening. The independent M1F audit and final Phase 1 closeout are complete, so Phase 1 is complete. The [Phase 0 audit record](../audits/phase-0-audit.md) and [Phase 1 audit record](../audits/phase-1-audit.md) preserve the closeout evidence. Commands below are explicitly separated into verified M0B–M0E checks and still-planned later-milestone workflows.

## Working principles

- Keep the production-grade portfolio project understandable and locally demonstrable.
- Implement only the current milestone or phase and avoid future-phase scaffolding.
- Prefer explicit domain behavior over hidden prompt behavior or speculative abstractions.
- Keep AI, workflow orchestration, deterministic business logic, and external side effects behind clear boundaries.
- Use synthetic data and safe test doubles by default.

## Source-of-truth order

1. The active user request or milestone/phase brief defines current scope.
2. `docs/roadmap/project-roadmap.md` defines approved product and engineering scope.
3. `docs/architecture/system-overview.md` defines the two authority boundaries.
4. `docs/architecture/domain-model.md` defines the Phase 1 domain contract.
5. This guide defines repository conventions and planned workflow.
6. Implemented code and tests define behavior that already exists.

Conflicts must be surfaced and resolved explicitly. A later implementation must not silently change the roadmap’s meaning.

## Branches and commits

Work on the designated milestone or phase branch. Keep commits coherent and narrowly scoped. Before committing:

1. inspect `git status` and the diff;
2. confirm no unrelated files are included;
3. run the applicable checks;
4. review for secrets, generated files, and future-phase leakage;
5. commit with a concise message describing the milestone.

The closeout report must identify the branch, HEAD, commits created, files changed, and working-tree state.

## Planned repository conventions

The intended baseline is Python 3.12 for backend and business logic, `uv` with `pyproject.toml` and `uv.lock` for Python dependency management, FastAPI for HTTP boundaries, Pydantic v2 for typed input/output models, SQLAlchemy 2.x and Alembic for persistence, PostgreSQL as the application store, React/TypeScript/Vite for the review UI, and self-hosted n8n for orchestration. The exact internal folders should be created only when their responsibilities become necessary.

Expected top-level areas are described by the roadmap, including `src/opsflow/`, `web/`, `workflows/n8n/`, `tests/`, `evals/`, `fixtures/`, `migrations/`, `infra/`, and Docker/packaging files. `web/` now exists for M0D; other areas remain absent until an applicable milestone requires them.

## Verified M0B/M0C backend commands

The following commands were run successfully during M0B/M0C against the committed project configuration:

```bash
# Managed backend environment and quality gates
uv sync --frozen --dev
uv run python -c "import opsflow; from opsflow.main import app"
uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
uv run pytest
uv run pytest tests/integration/test_readiness.py -q --no-cov
uv run alembic upgrade head
uv run alembic current
uv build
docker compose config --quiet
docker compose up -d --build
```

`uv run pytest` enforces and reports the configured 80% minimum coverage floor. The complete M0B/M0C suite reports 97.96% coverage. M0C also verified live `/health` and `/ready` behavior with PostgreSQL running, stopped, and restarted.

## Isolated domain verification

With PostgreSQL, Docker, network access, and the API server unavailable, use
the following command to verify the infrastructure-independent domain suite:

```bash
uv run pytest tests/unit/domain -q --no-cov
```

`--no-cov` is limited to this targeted domain check because the repository-wide
pytest configuration measures coverage across all `opsflow` modules. It does
not weaken the `>=80%` coverage requirement enforced by the full repository
quality gates, including `make backend-check` and `make check`.

## Verified M0D frontend commands

The following commands were run successfully during M0D from `web/` with Node.js 24.21.0 and npm 11.19.0:

```bash
node --version
npm --version
npm ci
npm run lint
npm run build
npm run dev -- --host 127.0.0.1
```

The development server served the frontend at `http://127.0.0.1:5173/` with HTTP 200. The served page contains the OpsFlow AI foundation content. No browser binary or browser automation tool was available for a visual inspection, so no browser framework was added.

## Verified M0E commands

With PostgreSQL available, the following Make targets were run successfully from the repository root:

```bash
make test
make test-integration
make lint
make format
make typecheck
make backend-check
make frontend-check
make check
make up
make migrate
make down
```

`make format` is intentionally a non-mutating Ruff formatting check. `make up` starts the API and PostgreSQL containers with Compose; `make migrate` applies Alembic migrations; `make down` stops and removes containers while preserving the named database volume.

The local secret scan uses the same pinned open-source Gitleaks container as CI:

```bash
docker run --rm --volume "$PWD:/repo:ro" \
  zricethezav/gitleaks:v8.28.0 \
  git --redact --no-banner --verbose \
  --log-opts="--all --full-history" /repo
```

This scan completed successfully with no leaks found. The CI workflow is [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) and has three read-only jobs: backend, frontend, and secret-scan. Backend CI uses Python 3.12, frozen `uv` dependencies, and a PostgreSQL 16 service; frontend CI uses Node.js 24 and `npm ci`.

## Clean-checkout workflow

The README’s [local development sequence](../../README.md#local-development) is the concise clean-checkout procedure. It installs the committed Python and npm dependencies, creates only the ignored local `.env`, starts PostgreSQL, applies migrations, runs the two development servers, and then runs `make check`. The sequence was verified from a fresh clone of `phase/0-foundation`.

## Still planned or unverified commands

These commands remain planned until their later milestone introduces the corresponding workflow:

```bash
# Focused verification — use the project’s eventual documented test selectors
uv run pytest tests/unit -q
uv run pytest tests/integration -q
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

M0A had no application behavior; M0B adds `/health`; M0C adds database configuration, engine lifecycle, `/ready`, Alembic’s empty baseline, and local PostgreSQL/Docker infrastructure; M0D adds only the static frontend foundation page; M0E adds only developer commands, CI, and secret scanning. M0D intentionally adds no frontend test framework because it has no meaningful application behavior yet. No business tables, review UI, or later-milestone behavior is covered here.

## Documentation conventions

- Use Markdown headings that reflect the document hierarchy.
- Link to repository files with relative links.
- State whether a component is planned, implemented, or verified.
- Keep architecture decisions and phase scope durable and reviewable.
- Use examples only when they clarify a current contract; do not use examples to smuggle in future functionality.

## Security and cost conventions

Never commit `.env` files, API keys, credentials, private customer data, or real business documents. Use `.env.example` only when a future phase needs it and keep values non-secret. Prefer local/open-source infrastructure, free developer environments, adapters, test doubles, and synthetic data. Optional paid AI calls must not become a required development dependency.

## Milestone and phase workflow

Every implementation milestone or phase follows the roadmap’s completion protocol:

1. plan exact scope, files, interfaces, tests, commands, non-goals, and exit criteria;
2. implement minimally on the designated branch;
3. run applicable quality gates and manual verification;
4. provide the required Codex report;
5. perform senior review for architecture, scope, tests, security, and unnecessary complexity;
6. mark the milestone or phase complete only after review passes.

The milestone or phase report must include implementation, architecture decisions, dependencies, tests and results, quality gates, manual verification, deviations, known limitations, and security/cost notes.
