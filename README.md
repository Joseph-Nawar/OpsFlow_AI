# OpsFlow AI

OpsFlow AI is a production-grade portfolio project for reliable B2B purchase-order and operations automation. It is designed to demonstrate how messy inputs such as email, PDF, XLSX, and forms can move through AI-assisted extraction, deterministic validation, human review, and safe synchronization with business systems.

The project is intentionally sized as a portfolio project, not an enterprise platform. The goal is a clear, credible, locally demonstrable system that shows applied AI, workflow automation, backend engineering, integrations, reliability, and evaluation.

## Current status

**M0A — Repository Intelligence & Project Specification**, **M0B — Backend Foundation**, **M0C — PostgreSQL, SQLAlchemy, Alembic & Docker**, **M0D — Frontend Foundation**, **M0E — Developer Experience & CI**, and **M0F — Independent Phase 0 Audit** are `COMPLETE`. Phase 0 is `COMPLETE`. Phase 1 is `COMPLETE`; **M1A — Domain Contract & Implementation Plan**, **M1B — Supporting Domain Records**, **M1C — Order Aggregate**, **M1D — State Machine & Recovery Semantics**, **M1E — Domain Scenario Verification & Contract Hardening**, and **M1F — Independent Phase 1 Audit** are `COMPLETE`. Phase 2 is `IN PROGRESS`; **M2A — Persistence & API Contract**, **M2B — Relational Schema & Domain Mapping**, and **M2C — Repository & Durable Reads** are `COMPLETE`, **M2D — Idempotent Order Creation** is `IN PROGRESS`, and **M2E–M2F** are `NOT STARTED`. Phases 3–12 remain `NOT STARTED`.

The canonical phase tracker and approved scope are in [the project roadmap](docs/roadmap/project-roadmap.md). Independent closeout evidence is recorded in [the Phase 0 audit](docs/audits/phase-0-audit.md) and [the Phase 1 audit](docs/audits/phase-1-audit.md). The approved Phase 1 contract is in [the domain model specification](docs/architecture/domain-model.md), with its implementation sequence in [the Phase 1 plan](docs/superpowers/plans/2026-09-13-phase-1-domain-model.md). The authoritative M2A design is [the Phase 2 Persistence & Core API design](docs/superpowers/specs/2026-09-14-phase-2-persistence-api-design.md), with its execution sequence in [the Phase 2 implementation plan](docs/superpowers/plans/2026-09-14-phase-2-persistence-api.md).

## Architectural guardrails

- **AI interprets unstructured information; deterministic software controls business decisions and side effects.** An LLM may extract fields and evidence, but it may not decide validity, approval, execution, or external mutation.
- **n8n orchestrates workflows; Python owns business logic.** n8n will handle triggers, sequencing, SaaS connections, notifications, and simple routing. Python will own document processing, extraction, validation, policy, persistence, state transitions, auditability, and integration contracts.

The system is expected to evolve toward this flow:

```text
Email / PDF / XLSX / Form
            |
           n8n
            |
       OpsFlow API
            |
  document processing and extraction
            |
 deterministic validation and policy
        /                 \
     valid              exception
       |                   |
 ready for approval    human review
        \                 /
             approval
                |
       ERP / CRM / notifications
                |
             audit log
```

## Intended technology baseline

M0B verified Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings, pytest, Ruff, mypy, and package building. M0C verifies SQLAlchemy 2.x async PostgreSQL access through asyncpg, Alembic, PostgreSQL 16, Docker Compose, and the `/ready` readiness boundary. M0D verifies the minimal Node.js 24/npm React, TypeScript, Vite, and ESLint frontend foundation. M0E verifies the Makefile command interface, GitHub Actions quality gates, and Gitleaks scanning. The remaining roadmap baseline—self-hosted n8n Community Edition, review-application UI, AI providers, document handling, business integrations, and structured logging—remains planned for later milestones.

## Documentation map

- [Architecture overview](docs/architecture/system-overview.md) — authority boundaries and intended system flow.
- [Development guide](docs/development/development-guide.md) — conventions, verified M0B–M0E commands, and planned workflow.
- [Decision records](docs/decisions/README.md) — how durable technical decisions will be recorded.
- [Project roadmap](docs/roadmap/project-roadmap.md) — approved phases, rules, status, and completion protocol.

## Cost and data posture

The project must remain deployable and demonstrable with **$0 mandatory development cost**. Local and open-source infrastructure, free developer environments, adapters, test doubles, and synthetic data are preferred. Optional paid AI testing must remain a convenience rather than an architectural dependency.

Never commit credentials, API keys, private business data, or real customer documents. Use local configuration and synthetic fixtures as later phases are implemented.

## Local development

Prerequisites are Python 3.12 with `uv`, Node.js 24 with npm, Docker Desktop with Compose, GNU Make, and Git.

For a fresh checkout, use this sequence:

```bash
uv sync --frozen --dev
npm --prefix web ci
cp .env.example .env
docker compose up -d postgres
make migrate
```

Run the local development servers in separate terminals:

```bash
uv run uvicorn opsflow.main:app --reload
npm --prefix web run dev
```

Run the quality gates with PostgreSQL available:

```bash
make check
```

`make backend-check` covers Ruff, formatting, mypy, the full pytest suite, and `uv build`. `make frontend-check` repeats `npm ci`, ESLint, and the production build. The integration tests and full backend suite require PostgreSQL; quality targets do not start or destroy infrastructure automatically.

For the containerized API and database lifecycle, use `make up`, `make migrate`, and `make down`. `make down` removes containers and the Compose network but preserves the named database volume.

Verified M0B–M0E commands and still-planned commands are distinguished in the [development guide](docs/development/development-guide.md).
