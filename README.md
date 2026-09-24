# OpsFlow AI

OpsFlow AI is a production-grade portfolio project for reliable B2B purchase-order and operations automation. It is designed to demonstrate how messy inputs such as email, PDF, XLSX, and forms can move through AI-assisted extraction, deterministic validation, human review, and safe synchronization with business systems.

The project is intentionally sized as a portfolio project, not an enterprise platform. The goal is a clear, credible, locally demonstrable system that shows applied AI, workflow automation, backend engineering, integrations, reliability, and evaluation.

## Current status

**M0A — Repository Intelligence & Project Specification**, **M0B — Backend Foundation**, **M0C — PostgreSQL, SQLAlchemy, Alembic & Docker**, **M0D — Frontend Foundation**, **M0E — Developer Experience & CI**, and **M0F — Independent Phase 0 Audit** are `COMPLETE`. Phase 0 is `COMPLETE`. Phase 1 is `COMPLETE`; **M1A — Domain Contract & Implementation Plan**, **M1B — Supporting Domain Records**, **M1C — Order Aggregate**, **M1D — State Machine & Recovery Semantics**, **M1E — Domain Scenario Verification & Contract Hardening**, and **M1F — Independent Phase 1 Audit** are `COMPLETE`. Phase 2 is `COMPLETE`; **M2A — Persistence & API Contract**, **M2B — Relational Schema & Domain Mapping**, **M2C — Repository & Durable Reads**, **M2D — Idempotent Order Creation**, **M2E — Core /v1/orders API & Hardening**, and **M2F — Independent Phase 2 Audit & Closeout** are `COMPLETE`. Phase 3 is `COMPLETE`; **M3A — Canonical Ingestion Contract**, **M3B — Canonical Models, Validation & Text/CSV**, **M3C — XLSX Parsing**, **M3D — PDF Parsing**, **M3E — Unified Processor & Robustness**, and **M3F — Independent Phase 3 Audit & Closeout** are `COMPLETE`. Phase 4 is `COMPLETE`; **M4A — Extraction Contract & Design**, **M4B — Typed Models, Prompt Renderer & Fake Provider**, **M4C — OrderExtractor & Response Hardening**, **M4D — Gemini Provider**, **M4E — Cross-Format & Adversarial Robustness**, and **M4F — Independent Phase 4 Audit & Closeout** are `COMPLETE`. Phase 5 is `COMPLETE`; **M5A — Deterministic Validation Contract & Design**, **M5B — Trusted Business Data, Policy & Rule Engine**, **M5C — Extraction Snapshot Persistence**, **M5D — Validation Application Service & Atomic Routing**, **M5E — Rule Matrix, Integration & Adversarial Hardening**, and **M5F — Independent Phase 5 Audit & Closeout** are `COMPLETE`. Phase 6 is `COMPLETE`; **M6A — Human Review Contract & Design**, **M6B — Review Persistence, Authorization & Read Model**, **M6C — Human Correction & Deterministic Revalidation**, **M6D — Approval, Rejection & Retry Commands/API**, **M6E — React Review Application & Cross-Boundary Hardening**, and **M6F — Independent Phase 6 Audit & Closeout** are `COMPLETE`. Phase 7 is `IN PROGRESS`; **M7A — Orchestration Contract & Design**, **M7B — Orchestration Service Authentication & HTTP Contract**, **M7C — Idempotent Intake Pipeline**, and **M7D — n8n Runtime & Version-Controlled Sandbox Workflow** are `COMPLETE`, while M7E–M7F are `NOT STARTED`. Phases 8–12 remain `NOT STARTED`.

M6A closed with approved design and implementation-plan artifacts. M6B completed the review foundation: immutable review/operator contracts, canonical review serialization, migration `0004_phase6_review_revisions` with immutable revision persistence, server-derived development authorization, synthetic runtime composition, strong read-side ETags, and review queue/detail/reference-data GET APIs. M6C provides narrow `NEEDS_REVIEW`-only reviewed-data promotion and complete Save & revalidate behavior. Human corrections are persisted as immutable review revisions; `If-Match` is enforced before provider work and again under the final order lock. Provider and deterministic validation run outside database transactions, while final locked checks cover local facts, revision, audit generation, state, and source identity. Invalid corrections preserve the trusted order graph; clean corrections promote only `ValidatedOrderData`. Deterministic review audit events and PostgreSQL atomicity/concurrency coverage are in place through `PUT /v1/review/orders/{order_id}/draft`. M6D completes approval, rejection, and retry commands/API with server-resolved authorization, strong `If-Match` concurrency and audit-generation ABA protection, persisted high-value approval enforcement, and retry to the recorded failure origin without resuming processing; each lifecycle transition and its audit events commit atomically. M6E delivers the React human-review application and cross-boundary hardening: server-verified development credential access and switching, server-backed queue filtering and pagination, distinct AI provenance, untrusted human draft, trusted order, deterministic validation, trusted reference data, revision/audit history, ordered-line editing, Save & revalidate, explicit no-replay stale-screen protection, and backend-authoritative approve/reject/retry actions with frontend tests and CI coverage. M6F completed the independent whole-Phase-6 audit with zero CRITICAL, HIGH, MEDIUM, or LOW findings, and Phase 6 is closed.

M7C now provides the idempotent intake pipeline: backward-compatible created-versus-replayed Phase 2 disposition, locked execution claims, separate creation and execution authority, exact source/idempotency binding, human-authorized PROCESSING and EXTRACTED retry-generation consumption with same-document Phase 3/4 reconstruction, typed provider/document/business-data failure classification with atomic failed-state persistence, an injectable network-free extraction runtime with optional Gemini, the composed Phase 2–5 application service, the real authenticated FastAPI handler, bounded 401/409/422/503 and 201/200/202 behavior, and PostgreSQL/HTTP evidence for replay, concurrency, retries, reconstruction, business routing, and persistence ambiguity. M7C persists no raw document bytes. If a claim or human-retry resume marker commits and a later persistence operation becomes unavailable, the request returns the safe unavailable boundary and matching redelivery stands down rather than reclaiming execution automatically. M7C does not implement Gmail/Slack, ERP/CRM synchronization, automatic machine retries, lease/heartbeat ownership recovery, or SYNCING execution.

M7D provides the pinned self-hosted n8n Community runtime `n8nio/n8n:2.40.5` as one minimal Compose service with persistent local data, server-side orchestration/review configuration propagation, credential-backed OpsFlow HTTP authentication, a sanitized version-controlled workflow and synthetic fixture, Webhook → OpsFlow HTTP Request → backend-state Switch → response routing for `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, `FAILED_RETRYABLE`, `FAILED_FINAL`, `PROCESSING`, `EXTRACTED`, and a safe default, exact `X-OpsFlow-Event-Id` → `Idempotency-Key` forwarding, clean-clone import/relink/publish instructions, and pinned-runtime evidence freezing Decision B (standard-node-only fallback) for later bounded transport retry. The frozen M7E direction is Never Error plus full HTTP response for status routing, a separate connection-error output, standard Switch/If + Edit Fields + Wait nodes, and maximum two retry attempts after the initial request for connection errors and HTTP 503 only; 401, 409, 422, generic 500, and 2xx `FAILED_RETRYABLE` are excluded while the exact document and event/idempotency identity are preserved. M7D does not yet implement automatic transport retry, retry counters/Wait retry topology, a deterministic retryable demo seed, M7E recovery hardening, Gmail/Slack, ERP/CRM synchronization, SYNCING execution, lease/heartbeat claim recovery, or the final Phase 7 audit; the committed workflow has no automatic retry.

The canonical phase tracker and approved scope are in [the project roadmap](docs/roadmap/project-roadmap.md). Independent closeout evidence is recorded in [the Phase 0 audit](docs/audits/phase-0-audit.md), [the Phase 1 audit](docs/audits/phase-1-audit.md), [the Phase 2 audit](docs/audits/phase-2-audit.md), [the Phase 3 audit](docs/audits/phase-3-audit.md), [the Phase 4 audit](docs/audits/phase-4-audit.md), [the Phase 5 audit](docs/audits/phase-5-audit.md), and [the Phase 6 audit](docs/audits/phase-6-audit.md). The approved Phase 1 contract is in [the domain model specification](docs/architecture/domain-model.md), with its implementation sequence in [the Phase 1 plan](docs/superpowers/plans/2026-09-13-phase-1-domain-model.md). The authoritative Phase 2 design is [the Phase 2 Persistence & Core API design](docs/superpowers/specs/2026-09-14-phase-2-persistence-api-design.md), with its execution sequence in [the Phase 2 implementation plan](docs/superpowers/plans/2026-09-14-phase-2-persistence-api.md). The authoritative M3A design is [the Phase 3 Document Ingestion & Canonical Parsing design](docs/superpowers/specs/2026-09-14-phase-3-document-ingestion-design.md). The authoritative M4A design is [the Phase 4 Structured AI Extraction design](docs/superpowers/specs/2026-09-17-phase-4-structured-ai-extraction-design.md). The authoritative Phase 5 design is [the Phase 5 Deterministic Validation design](docs/superpowers/specs/2026-09-17-phase-5-deterministic-validation-design.md), with its execution sequence in [the Phase 5 implementation plan](docs/superpowers/plans/2026-09-17-phase-5-deterministic-validation.md). The authoritative M6A design is [the Phase 6 Human Review Application Contract & Design](docs/superpowers/specs/2026-09-19-phase-6-human-review-application-design.md), with its approved execution sequence in [the Phase 6 implementation plan](docs/superpowers/plans/2026-09-19-phase-6-human-review-application.md). The approved Phase 7 n8n Workflow Orchestration design is [the Phase 7 n8n Workflow Orchestration design](docs/superpowers/specs/2026-09-22-phase-7-n8n-workflow-orchestration-design.md), with its [approved implementation plan](docs/superpowers/plans/2026-09-22-phase-7-n8n-workflow-orchestration.md); M7B completed the authenticated HTTP/transport boundary, M7C completed the idempotent intake pipeline with HTTP/PostgreSQL integration, and M7D completed the pinned local n8n runtime, sanitized sandbox workflow, import/publish verification, and retry-capability decision; cross-boundary retry/recovery hardening remains M7E and is `NOT STARTED`.

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

M0B verified Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings, pytest, Ruff, mypy, and package building. M0C verifies SQLAlchemy 2.x async PostgreSQL access through asyncpg, Alembic, PostgreSQL 16, Docker Compose, and the `/ready` readiness boundary. M0D verifies the minimal Node.js 24/npm React, TypeScript, Vite, and ESLint frontend foundation. M0E verifies the Makefile command interface, GitHub Actions quality gates, and Gitleaks scanning. Document handling, AI extraction/provider infrastructure, and the React human-review application are now implemented through Phases 3, 4, and 6. Remaining later-phase baseline work includes n8n orchestration, external business integrations, and production-style observability/security hardening.

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
