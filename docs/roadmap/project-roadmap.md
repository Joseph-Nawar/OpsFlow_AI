# OpsFlow AI Master Project Roadmap

## Project identity

- **Working name:** OpsFlow AI
- **Project type:** Production-grade applied AI business-automation portfolio project
- **Primary use case:** Intelligent B2B purchase-order and operations automation
- **Primary career objective:** Maximize relevance to freelance AI automation/integration demand while strengthening an Applied AI Engineer / ML Engineer portfolio.
- **Complexity budget:** Production-grade portfolio project, not an enterprise platform.

This document is the version-controlled product and engineering source of truth. It converts the approved master roadmap into durable repository guidance without changing its intended meaning.

The current repository milestones are **M0A — Repository Intelligence & Project Specification**, **M0B — Backend Foundation**, **M0C — PostgreSQL, SQLAlchemy, Alembic & Docker**, **M0D — Frontend Foundation**, **M0E — Developer Experience & CI**, and **M0F — Independent Phase 0 Audit**, all `COMPLETE`. **Phase 0 — Product & Engineering Foundation** is `COMPLETE`; **Phase 1 — Domain Model & State Machine** is `COMPLETE` with M1A–M1F complete; **Phase 2 — Persistence & Core API** is `IN PROGRESS` with M2A complete, M2B in progress, and M2C–M2F not started; Phases 3–12 remain `NOT STARTED`. Independent closeout evidence is recorded in [the Phase 0 audit](../audits/phase-0-audit.md) and [the Phase 1 audit](../audits/phase-1-audit.md), the Phase 1 contract is recorded in [the domain model specification](../architecture/domain-model.md), and the Phase 2 design and implementation plan are recorded in [the Phase 2 Persistence & Core API design](../superpowers/specs/2026-09-14-phase-2-persistence-api-design.md) and [the Phase 2 implementation plan](../superpowers/plans/2026-09-14-phase-2-persistence-api.md).

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
- **Document handling:** PyMuPDF, openpyxl, CSV/email parsing, Tesseract OCR where required.
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
| 2 | Persistence & Core API | Durable order intake and retrieval | IN PROGRESS |
| 3 | Document Ingestion | Reliable handling of PDF/XLSX/email inputs | NOT STARTED |
| 4 | Structured AI Extraction | Unstructured documents to typed order drafts | NOT STARTED |
| 5 | Deterministic Validation | Trusted business-rule engine | NOT STARTED |
| 6 | Human Review Application | Usable review and approval interface | NOT STARTED |
| 7 | n8n Workflow Orchestration | Real automation workflow | NOT STARTED |
| 8 | Email & Notification Integrations | Gmail and Slack integration | NOT STARTED |
| 9 | ERP & CRM Integrations | Odoo + HubSpot business-system sync | NOT STARTED |
| 10 | Reliability, Security & Hardening | Production-style failure handling | NOT STARTED |
| 11 | Evaluation & Optimization | Quantitative system evaluation | NOT STARTED |
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
| M2B — Relational Schema & Domain Mapping | IN PROGRESS |
| M2C — Repository & Durable Reads | NOT STARTED |
| M2D — Idempotent Order Creation | NOT STARTED |
| M2E — Core `/v1/orders` API & Hardening | NOT STARTED |
| M2F — Independent Phase 2 Audit & Closeout | NOT STARTED |

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

**Objective:** Convert incoming documents into a canonical representation before AI processing.

V1 inputs are email body/plain text, PDF, XLSX, and CSV. Optional OCR is added only for scanned fixtures when required. The common representation includes extracted text, useful structured sheet/cell content, metadata, source reference, SHA-256 document hash, MIME type, and warnings.

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

The work queue displays review, approval-ready, and failed/retryable orders. Detail view shows source document, extraction, validation issues, trusted reference data, and audit history. Operators may edit permitted fields, approve, reject, and retry where appropriate. Field edits record previous/new values, actor, and timestamp; approval/rejection create audit events.

Prioritize clarity, speed, obvious exception reasons, transparent AI output, and visible trusted data. Test queue/detail rendering, validation display, edit/approve/reject flows and error states, plus backend authorization, state constraints, edit rules, and audit creation. Exit: the full review process works without manual API tooling.

### Phase 7 — n8n Workflow Orchestration

**Objective:** Introduce the workflow layer relevant to freelance automation work.

The sandbox workflow triggers intake, creates the order, processes the document, extracts, validates, and branches on result. n8n handles triggers, OpsFlow calls, SaaS connections, notifications, simple routing, and suitable retries; the business-rule engine remains in Python. Export workflows as version-controlled JSON under `workflows/n8n/`. n8n-to-OpsFlow communication uses real local/service authentication while secrets stay outside version control.

Test success, backend unavailability, duplicate triggers, malformed payloads, retries, and review/approval branching. Exit: a sandbox order travels through n8n and the backend reliably.

### Phase 8 — Email & Notification Integrations

**Objective:** Move from synthetic triggers to recognizable business integrations.

Gmail detects relevant order email, extracts body/attachment, creates intake, and sends approved/completed confirmation using safe test accounts/data. Slack notifies on review, approval, synchronization failure, and useful completion, with order reference, reason, and safe actionable link. External communication failure must not corrupt order state or duplicate a successful ERP action.

Use mocked adapters in automated tests and manually verify Gmail-to-system, system-to-Gmail, and system-to-Slack sandbox paths. Exit: real external email and collaboration integrations work without coupling core logic to providers.

### Phase 9 — ERP & CRM Integrations

**Objective:** Connect to real business systems beyond sandbox services.

An `OdooERPAdapter` matches the business-data/integration contract for customer/product lookup, inventory, trusted price, approved sales-order creation, and existing-reference lookup. HubSpot supports justified company/contact activity and associated deal/business activity without invented CRM complexity.

Protect writes with approval state, idempotency, timeouts, retries, and persisted external references. Automated tests use fakes/sandbox adapters; manual or integration testing proves actual Odoo and HubSpot developer environments. Test lookups, unavailable products, timeouts, rejection, duplicate create, success, CRM failure after ERP success, and recovery. Exit: an approved order creates/updates meaningful sandbox records exactly once.

### Phase 10 — Reliability, Security & Hardening

**Objective:** Turn a functioning demo into convincing production-style engineering.

Protect intake, processing, approvals, ERP effects, and repeated n8n deliveries with idempotency. Relevant identifiers include request key, source message ID, document SHA-256, customer+PO, and external order reference. Retry only safe failures; distinguish `FAILED_RETRYABLE` from `FAILED_FINAL`; isolate external failures.

Review authentication, authorization, file validation, prompt injection, secret handling, sensitive logging, input/request limits, SQL safety, and dependency vulnerabilities. Add structured logs, request/workflow/order IDs, latency, LLM usage, basic metrics, readiness, and useful integration health. Robustness scenarios include duplicates, malformed/huge files, prompt injection, provider timeout/invalid response, database interruption, ERP/CRM timeout, email/Slack failure, and partial synchronization.

Exit: no known tested failure causes duplicate execution, invalid automatic execution, silent corruption, secret exposure, or undetected inconsistent state.

### Phase 11 — Evaluation & Optimization

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
