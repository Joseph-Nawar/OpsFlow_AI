# OpsFlow AI Master Project Roadmap

## Project identity

- **Working name:** OpsFlow AI
- **Project type:** Production-grade applied AI business-automation portfolio project
- **Primary use case:** Intelligent B2B purchase-order and operations automation
- **Primary career objective:** Maximize relevance to freelance AI automation/integration demand while strengthening an Applied AI Engineer / ML Engineer portfolio.
- **Complexity budget:** Production-grade portfolio project, not an enterprise platform.

This document is the version-controlled product and engineering source of truth. It converts the approved master roadmap into durable repository guidance without changing its intended meaning.

The current repository milestones are **M0A — Repository Intelligence & Project Specification**, **M0B — Backend Foundation**, **M0C — PostgreSQL, SQLAlchemy, Alembic & Docker**, **M0D — Frontend Foundation**, **M0E — Developer Experience & CI**, and **M0F — Independent Phase 0 Audit**, all `COMPLETE`. **Phase 0 — Product & Engineering Foundation** is `COMPLETE`; **Phase 1 — Domain Model & State Machine** is `COMPLETE` with M1A–M1F complete; **Phase 2 — Persistence & Core API** is `COMPLETE` with M2A–M2F complete; **Phase 3 — Document Ingestion** is `COMPLETE` with M3A–M3F complete; **Phase 4 — Structured AI Extraction** is `COMPLETE` with M4A–M4F complete; **Phase 5 — Deterministic Validation** is `COMPLETE` with M5A–M5F complete; **Phase 6 — Human Review Application** is `COMPLETE` with M6A–M6F `COMPLETE`; **Phase 7 — n8n Workflow Orchestration** is `COMPLETE` with M7A–M7F `COMPLETE`; Phase 8 is `COMPLETE` (M8A–M8F `COMPLETE`); Phase 9 is `COMPLETE` (M9A, M9B, M9C, M9D, M9E, and M9F `COMPLETE`). Previous human-approved implementation SHAs remain recorded for M9B `8f1a25c55f627c3920465e95ffc954434d3aad74`, M9C `1ed8508167c75305553db54906bc5e9af5d89870`, M9D `9f319e9baeb8f6d39fccd578cfa85bda3fcb480f`, and M9E `8b1f6941f2070017724346c4acb93d1d16cfa492`. M9F and Phase 9 technical approval is recorded at `b96364d11da37b61fd6c8bc75c651918cf596ac7`. **Phase 10 — Reliability, Security & Hardening** is `COMPLETE` with M10A `COMPLETE` at approved SHA `ab7cec323e4d45dae57e5d418bc0755175aa0a88`; M10B `COMPLETE` at human-approved technical SHA `765c5030659d6c4d0aebe325b7d35d577766dbfd`; M10C `COMPLETE` at human-approved technical SHA `7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`; M10D `COMPLETE` at human-approved technical SHA `cf0b331864ca2cc5246aa32c7ce12827b79284d0`; M10E `COMPLETE` at human-approved technical SHA `b73d7add25c273b5efac10f86bdd3ebef952d6da`; and M10F `COMPLETE` after final audit disposition on technical remediation SHA `3632dbc46129ca0a074708a88d2698cb3ffcc3a7`. Phase 11 is `IN PROGRESS`; M11A — Evaluation Contract & Benchmark Design is `COMPLETE` with design `APPROVED` at `bde63c54a66486aea8c1e7292887d004bf9e91f4` and implementation plan `APPROVED` at `1e8c152aa072b075f059020ca232889ad2bcfa91`; M11B — Synthetic Ground-Truth Corpus & Scoring Foundation is `COMPLETE` at independently reviewed technical baseline `c5b33dd2c0d71263552ea9085fc6e3f5985ad17d`. M11B completed only the versioned 36-case synthetic corpus, trusted synthetic catalog, corpus integrity/ground-truth contracts, canonical extraction scorer, validation scorer, and result contracts. It did not implement the full evaluation runner, application-level reliability execution, release-gate execution, evaluation database lifecycle, latency benchmark execution, live Gemini evaluation, token/cost calculation, reference result generation, optimization, or the Phase 11 audit. M11C — Correctness, Routing & Reliability Evaluation is `IN PROGRESS` and executes Tasks 5–7 only; it must stop for independent review and human approval before M11D. M11D–M11F remain `NOT STARTED`. Phase 12 is `NOT STARTED`. Independent closeout evidence is recorded in [the Phase 0 audit](../audits/phase-0-audit.md), [the Phase 1 audit](../audits/phase-1-audit.md), [the Phase 2 audit](../audits/phase-2-audit.md), [the Phase 3 audit](../audits/phase-3-audit.md), [the Phase 4 audit](../audits/phase-4-audit.md), [the Phase 5 audit](../audits/phase-5-audit.md), [the Phase 6 audit](../audits/phase-6-audit.md), [the Phase 7 audit](../audits/phase-7-audit.md), and [the final Phase 9 audit disposition](../audits/phase-9-audit.md), as well as the approved [Phase 9 M9A design](../superpowers/specs/2026-09-29-phase-9-erp-crm-integrations-design.md) and [M9B implementation plan](../superpowers/plans/2026-09-30-phase-9-durable-sync-state-claiming-recovery.md). The Phase 1 contract is recorded in [the domain model specification](../architecture/domain-model.md), the Phase 2 design and implementation plan are recorded in [the Phase 2 Persistence & Core API design](../superpowers/specs/2026-09-14-phase-2-persistence-api-design.md) and [the Phase 2 implementation plan](../superpowers/plans/2026-09-14-phase-2-persistence-api.md), the authoritative M3A design is recorded in [the Phase 3 Document Ingestion & Canonical Parsing design](../superpowers/specs/2026-09-14-phase-3-document-ingestion-design.md), the authoritative M4A design is recorded in [the Phase 4 Structured AI Extraction design](../superpowers/specs/2026-09-17-phase-4-structured-ai-extraction-design.md), the authoritative Phase 5 design is recorded in [the Phase 5 Deterministic Validation design](../superpowers/specs/2026-09-17-phase-5-deterministic-validation-design.md), with its execution sequence in [the Phase 5 implementation plan](../superpowers/plans/2026-09-17-phase-5-deterministic-validation.md), the authoritative M6A design and approved implementation plan are recorded in [the Phase 6 Human Review Application design](../superpowers/specs/2026-09-19-phase-6-human-review-application-design.md) and [the Phase 6 implementation plan](../superpowers/plans/2026-09-19-phase-6-human-review-application.md), and the approved Phase 7 design and implementation plan are [the Phase 7 n8n Workflow Orchestration design](../superpowers/specs/2026-09-22-phase-7-n8n-workflow-orchestration-design.md) and [the Phase 7 implementation plan](../superpowers/plans/2026-09-22-phase-7-n8n-workflow-orchestration.md).

Phase 9 closeout records M9B durable order-sync state, claims, fencing, receipts, and retry ownership; M9C Odoo ERP integration; M9D HubSpot Company/Deal integration; M9E thin n8n scheduling; and M9F independent whole-phase audit and remediation closure. Technical approval is recorded at `b96364d11da37b61fd6c8bc75c651918cf596ac7`. The supported replay guarantee is at-most-one logical external record / convergent replay under the documented stable identities and recovery model.

M7A approved the Phase 7 design and implementation plan; M7B completed the authenticated orchestration HTTP/transport boundary; M7C completed the real idempotent intake pipeline with HTTP/PostgreSQL integration; M7D completed the pinned local n8n runtime, sanitized sandbox workflow, clean import/publish verification, and selective-retry capability decision; M7E completed selective transport retry, deterministic retryable demo seeding, human-retry/redelivery recovery verification, and the complete local sandbox/clean-clone handoff; M7F completed the independent whole-Phase-7 audit and final remediation verification. Phase 7 is COMPLETE.

## 1. Project goal

OpsFlow AI will demonstrate the ability to take a messy real-world business process involving emails, documents, structured business data, external SaaS applications, AI models, deterministic business rules, human approvals, and system failures—and turn it into a reliable automated workflow.

The system will receive purchase orders from email, PDF, XLSX, and structured forms; extract relevant order information with AI; validate the extraction against trusted business data; detect exceptions; route uncertain or invalid orders to humans; and safely synchronize approved orders with business systems such as an ERP and CRM.

The project is intended to demonstrate n8n automation, AI/LLM integrations, business workflow automation, structured document processing, FastAPI/Python backend development, CRM/ERP integrations, APIs and webhooks, human-in-the-loop AI, reliability and failure handling, and production AI evaluation.

## 2. Architecture principles

### AI interprets; deterministic software decides

The LLM may extract customer name, PO number, dates, SKU, quantities, prices, notes, and useful evidence. It may not decide whether a customer is valid, inventory is sufficient, a price is acceptable, an order is duplicated, an order should be executed, or an external mutation should occur. Those decisions belong to deterministic application code and explicit human-approval policies.

### n8n orchestrates; Python owns business logic

n8n is for triggers, email intake, SaaS integrations, workflow sequencing, notifications, and simple routing. Python/FastAPI owns document processing, AI extraction, validation, policies, persistence, state transitions, auditability, and external integration abstractions.

## 3. High-level system flow

```text
Email / PDF / XLSX / Form -> n8n -> OpsFlow API -> document processing
-> structured AI extraction -> deterministic validation -> business rules
-> valid: ready for approval
-> exception: human review
-> approval -> Odoo ERP / HubSpot CRM / Gmail confirmation -> Slack -> audit log
```

This is a phased target. A component is not considered implemented merely because it appears in this diagram.

## 4. Technology baseline

The intended stack is:

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic.
- **Data:** PostgreSQL.
- **Automation:** self-hosted n8n Community Edition.
- **Frontend:** React, TypeScript, Vite.
- **AI:** provider-neutral abstraction; Gemini as the initial development provider; deterministic fake provider for tests; optional OpenAI adapter later.
- **Document handling:** pypdf, openpyxl, CSV/plain-text parsing; OCR only if a later measured requirement justifies it.
- **Business integrations:** Odoo Community, HubSpot developer/test environment, Gmail API, Slack API.
- **Engineering:** Docker Compose, pytest, Ruff, mypy, GitHub Actions, secret scanning, structured logging.

M0B verifies the Python/FastAPI backend subset required for its milestone, M0C verifies the database and container subset required for its milestone, M0D verifies only the minimal React/TypeScript/Vite/ESLint frontend environment, and M0E verifies the local developer command interface, CI quality gates, and secret scanning. The remaining baseline items are planned, not installed or verified here.

## 5. Cost constraint

The project must remain deployable and demonstrable with **$0 mandatory development cost**. Paid services must not become architectural dependencies. Prefer local infrastructure, open-source software, free developer environments, adapters, test doubles, and synthetic rather than private business data. Optional paid AI testing is a convenience only; AI tests must not require network calls.

## 6. Project-wide engineering rules

### Keep the system understandable

This is a portfolio and learning project, not an enterprise product. Avoid unnecessary abstraction, speculative extensibility, excessive inheritance, excessive interfaces, microservices, Kubernetes, Kafka, complex event buses, and elaborate cloud infrastructure.

### Follow TDD where practical

For deterministic business behavior: write the failing test, confirm failure, implement minimal behavior, run the test, and refactor only when justified.

### Do not weaken tests

Never remove assertions to make tests pass, change expected results to match broken behavior, mark tests skipped without justification, or silently reduce coverage.

### Prefer explicit behavior

Business rules and states must be visible in code rather than hidden inside prompts.

### Control every external side effect

Tests must never create real ERP orders, send real emails, update real CRM records, or unexpectedly consume live AI tokens. Adapters, test doubles, configuration flags, or sandbox accounts must protect these boundaries.

### Commit coherent milestones

Each completed implementation unit should end with applicable tests, lint, type checks, a clear commit message, and a structured Codex report.

## 7. Phase overview and status

| Phase | Name | Primary outcome | Status |
| --- | --- | --- | --- |
| M0A | Repository Intelligence & Project Specification | Durable project context before coding | COMPLETE |
| M0B | Backend Foundation | Minimal Python/FastAPI backend foundation | COMPLETE |
| M0C | PostgreSQL, SQLAlchemy, Alembic & Docker | Minimal database and container foundation | COMPLETE |
| M0D | Frontend Foundation | Minimal React/TypeScript/Vite frontend foundation | COMPLETE |
| M0E | Developer Experience & CI | Reproducible local and CI quality gates | COMPLETE |
| M0F | Independent Phase 0 Audit | Independent audit and closeout evidence | COMPLETE |
| 0 | Product & Engineering Foundation | Clean repository and development environment | COMPLETE |
| 1 | Domain Model & State Machine | Correct business representation | COMPLETE |
| 2 | Persistence & Core API | Durable order intake and retrieval | COMPLETE |
| 3 | Document Ingestion | Deterministic canonical handling of PDF/XLSX/email/CSV inputs | COMPLETE |
| 4 | Structured AI Extraction | Unstructured documents to typed order drafts | COMPLETE |
| 5 | Deterministic Validation | Trusted business-rule engine | COMPLETE |
| 6 | Human Review Application | Usable review and approval interface | COMPLETE |
| 7 | n8n Workflow Orchestration | Real automation workflow | COMPLETE |
| 8 | Email & Notification Integrations | Gmail and Slack integration | COMPLETE |
| 9 | ERP & CRM Integrations | Odoo + HubSpot business-system sync | COMPLETE |
| 10 | Reliability, Security & Hardening | Production-style failure handling | IN PROGRESS |
| 11 | Evaluation & Optimization | Quantitative system evaluation | IN PROGRESS |
| 12 | Portfolio Release | Client-ready public project | NOT STARTED |

### Phase 0 execution milestones

| Milestone | Status |
| --- | --- |
| M0A — Repository Intelligence & Project Specification | COMPLETE |
| M0B — Backend Foundation | COMPLETE |
| M0C — PostgreSQL, SQLAlchemy, Alembic & Docker | COMPLETE |
| M0D — Frontend Foundation | COMPLETE |
| M0E — Developer Experience & CI | COMPLETE |
| M0F — Independent Phase 0 Audit | COMPLETE |

### Phase 1 execution milestones

| Milestone | Status |
| --- | --- |
| M1A — Domain Contract & Implementation Plan | COMPLETE |
| M1B — Supporting Domain Records | COMPLETE |
| M1C — Order Aggregate | COMPLETE |
| M1D — State Machine & Recovery Semantics | COMPLETE |
| M1E — Domain Scenario Verification & Contract Hardening | COMPLETE |
| M1F — Independent Phase 1 Audit | COMPLETE |

### Phase 2 execution milestones

| Milestone | Status |
| --- | --- |
| M2A — Persistence & API Contract | COMPLETE |
| M2B — Relational Schema & Domain Mapping | COMPLETE |
| M2C — Repository & Durable Reads | COMPLETE |
| M2D — Idempotent Order Creation | COMPLETE |
| M2E — Core `/v1/orders` API & Hardening | COMPLETE |
| M2F — Independent Phase 2 Audit & Closeout | COMPLETE |

### Phase 3 execution milestones

| Milestone | Status |
| --- | --- |
| M3A — Canonical Ingestion Contract | COMPLETE |
| M3B — Canonical Models, Validation & Text/CSV | COMPLETE |
| M3C — XLSX Parsing | COMPLETE |
| M3D — PDF Parsing | COMPLETE |
| M3E — Unified Processor & Robustness | COMPLETE |
| M3F — Independent Phase 3 Audit & Closeout | COMPLETE |

### Phase 4 execution milestones

| Milestone | Status |
| --- | --- |
| M4A — Extraction Contract & Design | COMPLETE |
| M4B — Typed Models, Prompt Renderer & Fake Provider | COMPLETE |
| M4C — OrderExtractor & Response Hardening | COMPLETE |
| M4D — Gemini Provider | COMPLETE |
| M4E — Cross-Format & Adversarial Robustness | COMPLETE |
| M4F — Independent Phase 4 Audit & Closeout | COMPLETE |

### Phase 5 execution milestones

| Milestone                                              | Status      |
| ------------------------------------------------------ | ----------- |
| M5A — Deterministic Validation Contract & Design       | COMPLETE    |
| M5B — Trusted Business Data, Policy & Rule Engine      | COMPLETE    |
| M5C — Extraction Snapshot Persistence                  | COMPLETE    |
| M5D — Validation Application Service & Atomic Routing  | COMPLETE    |
| M5E — Rule Matrix, Integration & Adversarial Hardening | COMPLETE    |
| M5F — Independent Phase 5 Audit & Closeout             | COMPLETE    |

### Phase 6 execution milestones

| Milestone | Status |
| --- | --- |
| M6A — Human Review Contract & Design | COMPLETE |
| M6B — Review Persistence, Authorization & Read Model | COMPLETE |
| M6C — Human Correction & Deterministic Revalidation | COMPLETE |
| M6D — Approval, Rejection & Retry Commands/API | COMPLETE |
| M6E — React Review Application & Cross-Boundary Hardening | COMPLETE |
| M6F — Independent Phase 6 Audit & Closeout | COMPLETE |

### Phase 7 execution milestones

| Milestone | Status |
| --- | --- |
| M7A — Orchestration Contract & Design | COMPLETE |
| M7B — Orchestration Service Authentication & HTTP Contract | COMPLETE |
| M7C — Idempotent Intake Pipeline | COMPLETE |
| M7D — n8n Runtime & Version-Controlled Sandbox Workflow | COMPLETE |
| M7E — Cross-Boundary Reliability & Demo Hardening | COMPLETE |
| M7F — Independent Phase 7 Audit & Closeout | COMPLETE |

### Phase 10 execution milestones

| Milestone | Status |
| --- | --- |
| M10A — Hardening Contract, Threat Model & Implementation Plan | COMPLETE |
| M10B — Cross-Boundary Idempotency, Failure Semantics & Recovery Hardening | COMPLETE |
| M10C — Security Boundaries, Input Safety & Secret Hygiene | COMPLETE |
| M10D — Structured Observability, Correlation & Operational Health | COMPLETE |
| M10E — Adversarial Resilience & Whole-System Failure Drills | COMPLETE |
| M10F — Independent Phase 10 Audit & Closeout | COMPLETE |

The final M10F audit record is [the Phase 10 audit](../audits/phase-10-audit.md). It preserves the frozen-baseline FAIL and records the final PASS after remediation and targeted independent re-review.

### Phase 11 execution milestones

| Milestone | Status |
| --- | --- |
| M11A — Evaluation Contract & Benchmark Design | COMPLETE; design APPROVED at `bde63c54a66486aea8c1e7292887d004bf9e91f4`; implementation plan APPROVED at `1e8c152aa072b075f059020ca232889ad2bcfa91` |
| M11B — Synthetic Ground-Truth Corpus & Scoring Foundation | COMPLETE at independently reviewed technical baseline `c5b33dd2c0d71263552ea9085fc6e3f5985ad17d`; corpus/scoring foundation only; M11C is IN PROGRESS (Tasks 5–7) |
| M11C — Correctness, Routing & Reliability Evaluation | IN PROGRESS; Tasks 5–7 only, then independent review and human approval before M11D |
| M11D — Performance, Token & Cost Evaluation | NOT STARTED |
| M11E — Measurement-Driven Optimization & Regression Comparison | NOT STARTED |
| M11F — Independent Phase 11 Audit & Closeout | NOT STARTED |

## 8. Detailed phases

### Phase 0 — Product & Engineering Foundation

**Objective:** Create a clean repository and development foundation before business features, preventing inconsistent or hard-to-test future work.

**Approved scope:** repository structure; Python project; frontend skeleton; unit/integration/e2e test structure; Docker Compose; PostgreSQL container; local configuration; documentation; CI baseline; coding standards; architecture documentation. The exact internal Python folders are created only when their responsibilities are necessary; dozens of empty modules are not generated.

**Engineering setup:** Python 3.12; dependency management; FastAPI skeleton; pytest; Ruff; mypy; PostgreSQL; SQLAlchemy; Alembic; frontend environment; Docker; `.env.example`; `.gitignore`; secret-safe defaults. Initial infrastructure endpoints are only `GET /health` and `GET /ready`.

**CI:** Ruff, mypy, pytest, backend build/install validation, and frontend lint/build where applicable.

**Tests and exit criteria:** verify imports, health/readiness behavior, database reachability, migrations, frontend build, and clean-checkout CI. Phase 0 completes only when the repository boots locally, quality gates pass, PostgreSQL works, CI succeeds, no secrets are committed, and the README contains reliable setup instructions.

**Explicitly not included:** orders, LLM calls, n8n workflows, Odoo, HubSpot, and document parsing.

This M0A repository-bootstrap milestone was intentionally narrower than the full approved Phase 0 implementation scope: it established project intelligence and documentation before application scaffolding began.

### Phase 1 — Domain Model & State Machine

**Objective:** Define the business model independently from databases, APIs, AI providers, and external systems.

**Core concepts:** `Order` with identifiers, customer reference, PO number, dates, currency, lines, source, and state; `Order Line` with SKU, description, quantity, submitted price, and trusted catalogue price where relevant; `Source Document` with type, name, MIME type, hash, message ID, and storage/reference metadata; `Validation Issue` with rule code, severity, field, expected/actual values, and explanation; and `Audit Event` for important business/system events.

**States:** `RECEIVED`, `PROCESSING`, `EXTRACTED`, `VALIDATED`, `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, `APPROVED`, `SYNCING`, `COMPLETED`, `REJECTED`, `FAILED_RETRYABLE`, `FAILED_FINAL`. Only defined transitions are allowed. Examples include `RECEIVED -> PROCESSING`, `PROCESSING -> EXTRACTED`, `EXTRACTED -> VALIDATED`, `VALIDATED -> NEEDS_REVIEW` or `READY_FOR_APPROVAL`, `READY_FOR_APPROVAL -> APPROVED`, `APPROVED -> SYNCING`, and `SYNCING -> COMPLETED`.

**Invariants and tests:** positive quantities, structurally valid currency codes, immutable completed orders, explicit reopening for rejected orders, and approval before synchronization. Configured supported-currency policy belongs to Phase 5. Unit-test model creation, invalid values, line behavior, valid/illegal transitions, and audit construction. Exit: domain logic works without a database, transitions and invariants are explicit and tested, and domain classes have no infrastructure concerns.

### Phase 2 — Persistence & Core API

**Objective:** Persist domain information safely and expose the first meaningful HTTP API.

Initial tables may include orders, order lines, source documents, validation issues, audit events, and processing-attempt/idempotency records. Initial endpoints are `POST /v1/orders`, `GET /v1/orders`, `GET /v1/orders/{order_id}`, and `GET /v1/orders/{order_id}/audit`, with only review-UI-needed filters. Order creation supports an idempotency key. A fresh database must migrate automatically and remain the authoritative application store.

Test repositories as appropriate; integrate create, retrieve, list, duplicate-request, foreign-key, rollback, and audit persistence behavior against a real PostgreSQL test environment. Keep API and domain models separate.

### Phase 3 — Document Ingestion

**Objective:** Convert supported incoming email/plain-text, PDF, XLSX, and CSV documents into a deterministic canonical representation before AI processing through an internal Python subsystem.

V1 inputs are email body/plain text, PDF, XLSX, and CSV. OCR is deferred and may be considered only after a measured scanned-fixture requirement. The common representation includes extracted text, page/table structure where relevant, metadata, source reference, raw-byte SHA-256 document hash, normalized MIME type, and warnings. Phase 3 adds no HTTP upload route, raw-file persistence, database migration, or parsed-document storage.

Validate MIME/type, size, page/sheet limits, supported types, corruption, and safe failure. Build synthetic fixtures for clean and multi-page PDFs, spreadsheets, email bodies, malformed/unsupported files, and duplicates. Test extraction, limits, MIME mismatch, duplicate hashes, normalization, XLSX, and PDF behavior. Exit: supported documents convert deterministically without an LLM call.

### Phase 4 — Structured AI Extraction

**Objective:** Convert canonical unstructured documents into strict structured order drafts using an LLM.

Introduce an `OrderExtractor`/`LLMProvider`-style abstraction with `FakeProvider` and `GeminiProvider`; an `OpenAIProvider` is optional later. Expected fields include customer name, PO number, order date, requested delivery date, currency, item SKU/description/quantity/submitted price, and notes. Missing information is explicit, not invented. Evidence or provenance may aid review, but confidence must not be called calibrated without evidence.

Prompts are extraction-only, prohibit decisions/tools, define null behavior, treat document instructions as data, and require only the schema. CI uses the fake provider; separate evaluations may call Gemini. Test schema parsing, invalid responses, missing fields, malformed structured output, timeout/failure, prompt-injection fixtures, and multiple lines. Exit: strict schema conversion, safe provider failures, no direct side effects, and network-free deterministic tests.

### Phase 5 — Deterministic Validation

**Objective:** Turn extraction drafts into trusted workflow decisions.

Create a sandbox business-data adapter for customers, products, catalogue prices, and inventory; Odoo later implements the same conceptual contract. Rules cover active/unambiguous customer, present and unique PO, unprocessed document, known SKU, positive/available quantity, consistent item information, required submitted price, configured pricing tolerance, supported currency, valid dates, sensible delivery date, and elevated approval for high-value orders where policy requires it.

Clean orders become `READY_FOR_APPROVAL`; any material issue becomes `NEEDS_REVIEW`. The LLM never decides routing. Use a rule matrix and direct tests for unknown/inactive customers, duplicate POs, invalid SKUs, stock, pricing, quantity, currency, missing data, high value, and multiple violations. Exit: deterministic rules fully control routing and known-invalid orders cannot enter approval-ready state incorrectly.

### Phase 6 — Human Review Application

**Objective:** Provide an operator interface to inspect, correct, approve, or reject orders.

M6A is `COMPLETE` with the approved [human review design](../superpowers/specs/2026-09-19-phase-6-human-review-application-design.md) and [implementation plan](../superpowers/plans/2026-09-19-phase-6-human-review-application.md). M6B is `COMPLETE`: it provides immutable review/operator contracts, canonical review serialization, migration `0004_phase6_review_revisions` with immutable revision persistence, server-derived development authorization, synthetic runtime composition, strong read-side ETags, and review queue/detail/reference-data GET APIs. M6C is `COMPLETE`: it provides narrow `NEEDS_REVIEW`-only reviewed-data promotion and complete Save & revalidate behavior; immutable human review revisions; complete Save `If-Match` enforcement; provider and deterministic engine execution outside database transactions; final locked local-fact, revision, audit-generation, state, and source rechecks; trusted-graph preservation for invalid corrections; clean promotion only from `ValidatedOrderData`; deterministic review audit events; `PUT /v1/review/orders/{order_id}/draft`; and PostgreSQL atomicity/concurrency coverage. M6D is `COMPLETE`: approval, rejection, and retry commands/API use server-resolved role authorization and strong `If-Match` concurrency; persisted high-value warnings require elevated approval; retry restores only the recorded failure origin; and state transitions/audits are atomic, with latest-audit ETag generation preventing retry ABA. M6E is `COMPLETE`: it delivers the React human-review application and cross-boundary hardening, including server-verified development credential access and switching; server-backed queue filtering and pagination; distinct original AI provenance, human-reviewed untrusted draft, trusted persisted order, deterministic validation, trusted reference data, and revision/audit history; ordered-line editing and Save & revalidate; explicit stale-screen reload with no replay; backend-authoritative approve/reject/retry actions; server-controlled high-value approval; safe command-result handling; and frontend automated tests and CI coverage. M6F is `COMPLETE`: the independent whole-Phase-6 audit recorded zero CRITICAL, HIGH, MEDIUM, or LOW findings in [the Phase 6 audit](../audits/phase-6-audit.md).

The review application provides a work queue for review, approval-ready, and failed/retryable orders, with detail inspection, correction, deterministic revalidation, trusted reference data, audit history, and server-authoritative approval, rejection, and retry actions. The independent Phase 6 audit is recorded in [the Phase 6 audit](../audits/phase-6-audit.md), and Phase 6 is closed.

Prioritize clarity, speed, obvious exception reasons, transparent AI output, and visible trusted data. Test queue/detail rendering, validation display, edit/approve/reject flows and error states, plus backend authorization, state constraints, edit rules, and audit creation. Exit: the full review process works without manual API tooling.

### Phase 7 — n8n Workflow Orchestration

**Objective:** Introduce a thin, authenticated n8n workflow boundary while preserving Python as the business authority.

The approved M7A design defines `POST /v1/orchestration/intakes` as a single-document multipart sandbox command. The backend derives source identity, composes the existing Phase 2–5 pipeline, owns idempotency and lifecycle state, and returns a narrow authoritative result. n8n handles the Webhook, multipart transport, bounded transport retries, and a Switch on returned `OrderState`; it does not parse documents, call Gemini, validate business data, approve orders, or mutate trusted state. M7D completed the pinned local runtime and sanitized workflow export under `workflows/n8n/`, with service credentials outside version control; M7E completed the standard-node bounded retry, deterministic retryable seeding, human-retry/redelivery verification, and complete local sandbox/clean-clone handoff; M7F completed the independent whole-Phase-7 audit and final remediation verification recorded in [the Phase 7 audit](../audits/phase-7-audit.md). Phase 7 is COMPLETE.

Test success, backend unavailability, duplicate triggers, malformed payloads, bounded transport retries, persisted retryable/final failures, and review/approval branching. Exit: a sandbox order travels through n8n and the backend reliably, with M7F independent audit evidence.

### Phase 8 — Email & Notification Integrations

**Status:** `COMPLETE`; M8A `COMPLETE`; M8B `COMPLETE`; M8C `COMPLETE`; M8D `COMPLETE`; M8E `COMPLETE`; M8F `COMPLETE`.

The independent whole-phase evidence and findings are recorded in [the Phase 8 audit](../audits/phase-8-audit.md).

**Objective:** Add bounded, recognizable email and collaboration integrations without moving business authority out of OpsFlow.

The completed Phase 8 path accepts labeled Gmail messages through the existing authenticated intake, records durable notification intents atomically with their triggering business events, delivers Slack review/approval/failure notifications, and sends the exact approval-for-processing reply only to the sender of a genuinely Gmail-origin order. Python owns provenance, business state, notification eligibility, claims, retry schedules, leases, and outcomes; n8n performs provider transport. Phase 8 stops at approval-for-processing: it does not synchronize ERP/CRM systems, enter `SYNCING`, or claim order completion.

Automated tests use provider-free contracts and test doubles; dedicated sandbox Gmail/Slack and clean-clone runs verify the external boundaries. External delivery is at-least-once after a lost outcome acknowledgement, while notification failures leave order state and review history unchanged. Exit: audited Gmail intake, Slack delivery, and sender-only Gmail approval replies work without coupling core business logic to providers.

### Phase 9 — ERP & CRM Integrations

**Status:** Phase 9 `COMPLETE`; M9A, M9B, M9C, M9D, M9E, and M9F `COMPLETE`. Earlier human-approved milestone SHAs remain recorded above. M9F and Phase 9 technical approval: `b96364d11da37b61fd6c8bc75c651918cf596ac7`; see the [final audit disposition](../audits/phase-9-audit.md).

**Objective:** Connect to real business systems beyond sandbox services.

An `OdooERPAdapter` matches the business-data/integration contract for customer/product lookup, inventory, trusted price, approved sales-order creation, and existing-reference lookup. HubSpot maintains one Company per trusted Odoo customer and one Deal per OpsFlow order, associated with that Company. Contacts, including Gmail-sender-derived records, are excluded.

Protect writes with approval state, durable synchronization intent, stable provider idempotency keys, bounded retries, and persisted external receipts. Provider execution is at-least-once; the required invariant is at most one logical Odoo order per OpsFlow order, one HubSpot Company per trusted customer reference, and one HubSpot Deal per OpsFlow order. Automated tests use fakes/sandbox adapters; manual or integration testing proves actual Odoo and HubSpot developer environments. Test lookups, unavailable products, timeouts, rejection, duplicate create, success, CRM failure after ERP success, and recovery. Exit: an approved order reaches `COMPLETED` only after confirmed Odoo and associated HubSpot Company/Deal receipts are durable, and replay creates no duplicate logical records.

### Phase 10 — Reliability, Security & Hardening

**Status:** Phase 10 `COMPLETE`; M10A `COMPLETE` at approved SHA `ab7cec323e4d45dae57e5d418bc0755175aa0a88`; M10B `COMPLETE` at human-approved technical SHA `765c5030659d6c4d0aebe325b7d35d577766dbfd`; M10C `COMPLETE` at human-approved technical SHA `7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`; M10D `COMPLETE` at human-approved technical SHA `cf0b331864ca2cc5246aa32c7ce12827b79284d0`; M10E `COMPLETE` at human-approved technical SHA `b73d7add25c273b5efac10f86bdd3ebef952d6da`; M10F `COMPLETE` after final audit disposition on technical remediation SHA `3632dbc46129ca0a074708a88d2698cb3ffcc3a7`.
The authoritative M10A [design](../superpowers/specs/2026-10-05-phase-10-reliability-security-hardening-design.md)
and [implementation plan](../superpowers/plans/2026-10-05-phase-10-reliability-security-hardening.md)
define the hardening boundary. M10B is complete at the approved technical SHA
`765c5030659d6c4d0aebe325b7d35d577766dbfd`; M10C is `COMPLETE` at human-approved technical SHA `7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`; M10D is `COMPLETE` at human-approved technical SHA `cf0b331864ca2cc5246aa32c7ce12827b79284d0`; M10E is `COMPLETE` at human-approved technical SHA `b73d7add25c273b5efac10f86bdd3ebef952d6da`; M10F is `COMPLETE` after final audit disposition on technical remediation SHA `3632dbc46129ca0a074708a88d2698cb3ffcc3a7`.
M10E records provider-free whole-system failure drills in
`tests/integration/test_phase10_failure_drills.py`; M10F records the final
independent audit and remediation disposition in [the Phase 10 audit](../audits/phase-10-audit.md).

Phase 10 closes with M10B durable ownership and fencing, M10C bounded input
and authentication/secret controls, M10D structured diagnostics and passive
health, M10E provider-free whole-system failure evidence, and M10F independent
audit closeout. The project retains its documented limits: local/demo bearer
authentication is not production IAM; metrics are process-local; passive
health is last-observed; notifications are at-least-once; provider execution
is not claimed physically exactly-once; and PostgreSQL unavailability can
still cause a visible bounded recovery failure.

**Objective:** Turn a functioning demo into convincing production-style engineering.

Protect intake, processing, approvals, ERP effects, and repeated n8n deliveries with idempotency. Relevant identifiers include request key, source message ID, document SHA-256, customer+PO, and external order reference. Retry only safe failures; distinguish `FAILED_RETRYABLE` from `FAILED_FINAL`; isolate external failures.

Review authentication, authorization, file validation, prompt injection, secret handling, sensitive logging, input/request limits, SQL safety, and dependency vulnerabilities. Add structured logs, request/workflow/order IDs, latency, LLM usage, basic metrics, readiness, and useful integration health. Robustness scenarios include duplicates, malformed/huge files, prompt injection, provider timeout/invalid response, database interruption, ERP/CRM timeout, email/Slack failure, and partial synchronization.

Exit: no known tested failure causes duplicate execution, invalid automatic execution, silent corruption, secret exposure, or undetected inconsistent state.

### Phase 11 — Evaluation & Optimization

**Status:** Phase 11 `IN PROGRESS`; M11A — Evaluation Contract & Benchmark Design is `COMPLETE`, with design `APPROVED` at `bde63c54a66486aea8c1e7292887d004bf9e91f4` and implementation plan `APPROVED` at `1e8c152aa072b075f059020ca232889ad2bcfa91`; M11B — Synthetic Ground-Truth Corpus & Scoring Foundation is `COMPLETE` at independently reviewed technical baseline `c5b33dd2c0d71263552ea9085fc6e3f5985ad17d`. M11B completed only the versioned 36-case synthetic corpus, trusted synthetic catalog, corpus integrity/ground-truth contracts, canonical extraction scorer, validation scorer, and result contracts; it did not implement the full evaluation runner, application-level reliability execution, release-gate execution, evaluation database lifecycle, latency benchmark execution, live Gemini evaluation, token/cost calculation, reference result generation, optimization, or the Phase 11 audit. M11C — Correctness, Routing & Reliability Evaluation is `IN PROGRESS` and executes Tasks 5–7 only; it must stop for independent review and human approval before M11D. M11D–M11F remain `NOT STARTED`. Phase 12 remains `NOT STARTED`.

**Objective:** Produce quantitative evidence rather than screenshots or anecdotes.

Generate reproducible synthetic normal, edge, and security cases with ground truth for structured output and routing. Measure extraction accuracy/F1/exact match where appropriate, correct routing, invalid pass-through, duplicate prevention, execution, retry recovery, p50/p95 latency, stage duration, token usage, calls/order, and estimated model cost/order.

Optimize only measured bottlenecks such as prompt length, local parsing, batching, unnecessary calls, or expensive OCR/model fallback. Release gates include zero known invalid synthetic orders executed, 100% policy routing for deterministic violations, 100% duplicate blocking, safe malformed-input failure, and no direct LLM side effects. Exit: a reproducible evaluation command generates a quantitative README/case-study report.

### Phase 12 — Portfolio Release

**Objective:** Make the finished system useful for freelance work and remote AI engineering interviews.

Repository quality includes clean README, reproducible setup, architecture/development/evaluation explanations, screenshots, demo data, workflow exports, license, and security/privacy notes. The README should cover business problem, demo, capabilities, architecture, workflow, safety/reliability, evaluation, integrations, stack, setup, tests, and limitations.

Create a concise case study without inventing ROI: show automated processing, accuracy, latency, duplicate protection, exception routing, estimated API cost, and demonstrated manual-step reduction. Produce one clean demo from email through extraction, validation, review, approval, Odoo, HubSpot, confirmation email, and Slack. Prepare technical discussion material on n8n+Python, AI restrictions, idempotency, human-in-the-loop, adapters, provider portability, evaluation, security, and cost.

Before publishing, scan Git history, verify `.env` was never tracked, verify API keys are absent, remove generated/private files, validate license and README links, and verify a clean clone. Exit: the repository is public-ready, CI/evaluation/demo/documentation are polished, and the project is suitable for a freelance proposal.

## 9. Phase completion protocol

The same process applies to every implementation phase:

1. **Phase planning:** define exact scope, files/components, interfaces, tests, commands, non-goals, and exit criteria.
2. **Codex implementation:** work on the designated branch, follow the architecture, keep implementation minimal, use tests, run required checks, and commit coherent work.
3. **Codex report:** include Git branch/HEAD/commits/files, what was added, architecture decisions, dependencies, test commands and results, coverage where relevant, quality gates, manual verification, deviations, limitations, and security/cost notes.
4. **Senior review:** review the report, diff/state, architecture, tests, scope, complexity, security, and future-phase compatibility.
5. **User explanation:** explain what was built, how it works, why it was built, important concepts, and its connection to the project.
6. **Gate:** mark the phase `COMPLETE` only after review passes; otherwise mark `FIX REQUIRED` and issue a focused correction prompt.

## 10. Definition of project success

By the end, OpsFlow should demonstrate:

- **Applied AI:** structured LLM extraction, prompt-safety boundaries, provider abstraction, and measurable evaluation.
- **Backend engineering:** FastAPI, typed models, PostgreSQL, transactions, migrations, state machine, idempotency.
- **Automation:** n8n, webhooks, workflow orchestration, retries, and SaaS connections.
- **Business integrations:** email, Slack, CRM, and ERP.
- **Production engineering:** tests, CI, Docker, observability, error handling, auditability, and security.
- **Human-AI system design:** human approval, uncertainty handling, deterministic safeguards, and clear authority boundaries.
- **Commercial relevance:** a prospective client can see that the engineer can automate a real document/AI/API/software workflow.
- **Career relevance:** a remote Applied AI employer can see the engineer understands reliable AI-enabled production systems beyond model demos.

## 11. Explicit end of scope

Completing Phase 12 means the project is finished. Voice agents, WhatsApp, Arabic localization, autonomous agents, Salesforce, SAP, QuickBooks, cloud Kubernetes deployment, multi-tenancy, billing, and mobile applications are not prerequisites. They may be added only when client demand or career needs justify them.

OpsFlow is not intended to become a startup. Its purpose is to be a high-quality, market-relevant proof that the engineer can deliver real applied AI automation systems.

### Phase 11 corrective status amendment

M11B remains `COMPLETE` at its independently reviewed technical baseline, with
the original approved corpus `1.0.0` preserved as historical evidence. M11C
Task 5 exposed an authority contradiction in two intake-recovery expectations;
the corrected active executable corpus is `2.0.0`, approved at amendment SHA
`1bdd3763bd00e73a28a8eacb148f803d03ea7bfe`; only the expected final state of
`retry-email-001` and `retry-csv-001` changed to `READY_FOR_APPROVAL`. No
source bytes changed. M11C is `IN PROGRESS`, and all further Phase 11
evaluation execution uses corpus `2.0.0`.
M11D–M11F remain `NOT STARTED`; Phase 11 remains `IN PROGRESS`; Phase 12
remains `NOT STARTED`.
