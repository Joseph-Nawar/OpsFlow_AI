# Development Guide

## Status of this guide

Phases 0–9 are complete and independently audited. The repository contains the
M0 foundation and CI, the Phase 1 domain/state contract, Phase 2 PostgreSQL
persistence and idempotent core API, Phase 3 document processing, Phase 4
structured extraction, Phase 5 deterministic validation, Phase 6 review
contracts, persistence, commands, and React application, and the complete Phase
7 authenticated orchestration pipeline, pinned local n8n runtime/workflow,
bounded selective retry, recovery/demo hardening, independent audit, and Phase
8 Gmail intake, durable notifications, Slack delivery, Gmail approval replies,
and independent whole-phase audit, and Phase 9 Odoo/HubSpot synchronization,
durable receipts, bounded recovery, and independent whole-phase audit. Phase 9
is `COMPLETE` (M9A–M9F `COMPLETE`; M9F and Phase 9 technical approval at
`b96364d11da37b61fd6c8bc75c651918cf596ac7`). Phase 10 is `COMPLETE` with
M10A `COMPLETE` at approved SHA `ab7cec323e4d45dae57e5d418bc0755175aa0a88`,
M10B `COMPLETE` at human-approved technical SHA
`765c5030659d6c4d0aebe325b7d35d577766dbfd`, M10C `COMPLETE` at human-approved technical SHA `7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`, M10D `COMPLETE` at human-approved technical SHA `cf0b331864ca2cc5246aa32c7ce12827b79284d0`, M10E `COMPLETE` at human-approved technical SHA `b73d7add25c273b5efac10f86bdd3ebef952d6da`, and M10F `COMPLETE` after final audit disposition on technical remediation SHA `3632dbc46129ca0a074708a88d2698cb3ffcc3a7`; Phase 10 is `COMPLETE`.
Phase 11 is `IN PROGRESS`; M11A — Evaluation Contract & Benchmark Design is `COMPLETE`, with design `APPROVED` at `bde63c54a66486aea8c1e7292887d004bf9e91f4` and implementation plan `APPROVED` at `1e8c152aa072b075f059020ca232889ad2bcfa91`; M11B — Synthetic Ground-Truth Corpus & Scoring Foundation is `COMPLETE` at independently reviewed technical baseline `c5b33dd2c0d71263552ea9085fc6e3f5985ad17d`. M11B completed only the versioned 36-case synthetic corpus, trusted synthetic catalog, corpus integrity/ground-truth contracts, canonical extraction scorer, validation scorer, and result contracts. It did not implement the full evaluation runner, application-level reliability execution, release-gate execution, evaluation database lifecycle, latency benchmark execution, live Gemini evaluation, token/cost calculation, reference result generation, optimization, or the Phase 11 audit. M11C — Correctness, Routing & Reliability Evaluation is `COMPLETE` at independently reviewed technical baseline `ce456f2928ed9773f26ec65dfa5776d29dd4e915`; it delivered Tasks 5–7 using active corpus `3.0.0`. M11D–M11F remain `NOT STARTED`. Phase 11 remains `IN PROGRESS`; Phase 12 is `NOT STARTED`. The [Phase 11 implementation plan](../superpowers/plans/2026-10-07-phase-11-evaluation-optimization.md) records M11C scope and local milestone verification. The final M10F audit record is [the Phase 10 audit](../audits/phase-10-audit.md); it preserves the frozen-baseline FAIL and records the final PASS after remediation and targeted independent re-review.
Independent local M11B milestone verification recorded: corpus version `1.0.0`, 36 cases with category split 10/8/4/7/4/3 (normal/edge/security/deterministic violation/duplicate/retry-recovery), format split 9/9/9/9 (EMAIL_BODY/CSV/XLSX/PDF), all 14 routed cases mechanically verified against the real deterministic validation engine, all 36 source artifacts verified through the production document processor, provider-free extraction quality `NOT_APPLICABLE`, no live provider called, and no existing production behavior modified. Evaluation tests: 83 passed; focused regressions: 673 passed; integration: 367 passed; local `make check`: 1,847 passed, 6 skipped, 91.11% coverage; Ruff, format, mypy, Gitleaks, Markdown links, and `git diff --check`: PASS. These are local milestone verification results, not GitHub PR-head CI.
The [Phase 0 audit record](../audits/phase-0-audit.md) through the [Phase 9
audit record](../audits/phase-9-audit.md) preserve closeout evidence.
Commands below distinguish historical verified checks from current or
still-planned later-milestone workflows.

### Phase 11 corrective status amendment

M11B remains `COMPLETE` at its independently reviewed technical baseline, with
the original approved corpus `1.0.0` preserved as historical evidence. M11C
Task 5 exposed an authority contradiction in two intake-recovery expectations;
the corrected corpus was `2.0.0`, approved at amendment SHA
`1bdd3763bd00e73a28a8eacb148f803d03ea7bfe`; only the expected final state of
`retry-email-001` and `retry-csv-001` changed to `READY_FOR_APPROVAL`. No
source bytes changed. At that amendment, M11C remained `IN PROGRESS`, and
evaluation execution used corpus `2.0.0` until the approved amendment below.
M11D–M11F remained `NOT STARTED`; Phase 11 remained `IN PROGRESS`; Phase 12
remained `NOT STARTED`.

### Phase 11 duplicate replay-contract amendment

Corpus `1.0.0` is the historical M11B-approved corpus. Corpus `2.0.0` is the
approved recovery-authority correction at amendment SHA
`1bdd3763bd00e73a28a8eacb148f803d03ea7bfe`. M11C real-path duplicate execution
showed that Phase 2 creation replay and Phase 7 intake execution expose distinct
dispositions. Corpus `2.0.0` encoded them in one ambiguous field; approved corpus
`3.0.0` splits those expectations without changing production behavior, source
documents, or source SHA-256 values. The corpus `3.0.0` amendment is approved at
`7184efb9589445d16e354decd486f28bc90ac09b`; all further Phase 11 evaluation
execution uses corpus `3.0.0`. At that amendment, M11C remained
`IN PROGRESS`; M11D–M11F remained `NOT STARTED`; Phase 11 remained
`IN PROGRESS`; Phase 12 remained `NOT STARTED`.

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

Expected top-level areas are described by the roadmap, including `src/opsflow/`, `web/`, `workflows/n8n/`, `tests/`, `evals/`, `fixtures/`, `migrations/`, `infra/`, and Docker/packaging files. `src/opsflow/`, `web/`, `tests/`, migrations, the Phase 2–6 capabilities, and the Phase 7–9 `workflows/n8n/` area now exist. Phase 8 is `COMPLETE` (M8A–M8F `COMPLETE`); Phase 9 is `COMPLETE` (M9A–M9F `COMPLETE`; technical approval at `b96364d11da37b61fd6c8bc75c651918cf596ac7`). M10A is `COMPLETE` at approved SHA `ab7cec323e4d45dae57e5d418bc0755175aa0a88`; M10B is `COMPLETE` at human-approved technical SHA `765c5030659d6c4d0aebe325b7d35d577766dbfd`; M10C `COMPLETE` at human-approved technical SHA `7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`; M10D `COMPLETE` at human-approved technical SHA `cf0b331864ca2cc5246aa32c7ce12827b79284d0`; M10E `COMPLETE` at human-approved technical SHA `b73d7add25c273b5efac10f86bdd3ebef952d6da`; M10F `COMPLETE` after final audit disposition on technical remediation SHA `3632dbc46129ca0a074708a88d2698cb3ffcc3a7`; Phase 10 is `COMPLETE`; other future areas remain absent until an applicable milestone requires them.

## Historical verified M0B/M0C backend commands

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

## Focused Phase 3 document verification

With PostgreSQL, Docker, the API server, AI providers, and internet access
unavailable, use the following command to verify the document-processing
subsystem:

```bash
uv run pytest tests/unit/documents -q --no-cov
```

This focused suite is infrastructure-independent. Complete GitHub Backend CI
continues to run the PostgreSQL-backed Phase 2 integration tests alongside the
document-processing tests.

## Historical verified M0D frontend commands

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

## Historical verified M0E commands

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

This scan completed successfully with no leaks found. The CI workflow is [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) and has four read-only jobs: backend, frontend, production dependency-security, and secret-scan. Backend CI uses Python 3.12, frozen `uv` dependencies, and a PostgreSQL 16 service; frontend CI uses Node.js 24 and `npm ci`. The dependency-security job audits frozen production-only Python dependencies with pinned `pip-audit==2.10.1` and frontend production dependencies with `npm audit --omit=dev --audit-level=high`.

## Clean-checkout workflow

The README’s [local development sequence](../../README.md#local-development) is the concise clean-checkout procedure. It installs the committed Python and npm dependencies, creates only the ignored local `.env`, starts PostgreSQL, applies migrations, runs the two development servers, and then runs `make check`. The sequence was verified from a fresh clone of `phase/0-foundation`.

## Phase 11 evaluation commands

Both evaluation commands require a one-time dedicated PostgreSQL database. The
database guard compares its name with the normal and configured migration-test
database names, verifies the live connection, clears only the application
tables in the dedicated evaluation database, and preserves Alembic metadata.
The command does not create the database.

For a local Compose PostgreSQL service, create the evaluation database once and
apply the current schema to that database:

```bash
docker compose up -d postgres
docker compose exec -T postgres createdb -U opsflow opsflow_evaluation
OPSFLOW_DATABASE_URL=postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_evaluation uv run alembic upgrade head
export OPSFLOW_EVALUATION_DATABASE_URL=postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_evaluation
```

Run the complete provider-free corpus with:

```bash
make evaluate
```

This mode needs no Gemini configuration and makes no provider calls. Generated
JSON and Markdown files are ignored under `evals/results/`.

Live Gemini evaluation is a separate, potentially billable command. Configure
the existing `OPSFLOW_GEMINI_API_KEY`, `OPSFLOW_GEMINI_MODEL`, and finite
positive `OPSFLOW_GEMINI_TIMEOUT_SECONDS` settings, then explicitly run:

```bash
make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1
```

Live mode validates its opt-in and provider configuration before database
cleanup or case execution. It uses the real Gemini adapter and fake downstream
integrations. It is not part of normal CI. No command publishes generated
results as references automatically.

## Testing approach

For deterministic business behavior, follow the red-green-refactor loop where practical:

1. write a focused failing test;
2. confirm the failure is for the expected reason;
3. implement the smallest behavior that satisfies the test;
4. run the focused test and the relevant broader suite;
5. refactor only when the behavior remains covered and the change is justified.

Tests must not remove assertions, change expected results to suit broken behavior, or skip coverage without an explicit reason. Live AI calls and real external side effects must never be hidden in ordinary automated tests.

### Destructive migration test isolation

Integration tests that downgrade Alembic revisions require an explicit
`OPSFLOW_MIGRATION_TEST_DATABASE_URL` naming a PostgreSQL database whose name
differs from `OPSFLOW_DATABASE_URL`. If it is unset, those tests skip; they
never fall back to the configured development database. CI provisions a
separate migration-test database, and migration subprocesses and schema
assertions use that same URL.

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
