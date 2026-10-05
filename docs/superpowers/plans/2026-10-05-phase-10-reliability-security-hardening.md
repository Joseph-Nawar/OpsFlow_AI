# Phase 10 — Reliability, Security & Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. The repository policy requires one agent working sequentially; do not use subagents or multi-agent workflows.

## Goal

Turn the final Phase 0–9 demo into convincing production-style engineering by
closing only the proven cross-boundary reliability, security, resource-limit,
secret-hygiene, and operational-visibility gaps documented in the [M10A
design](../specs/2026-10-05-phase-10-reliability-security-hardening-design.md).

M10A itself is documentation-only. This plan is the implementation sequence for
the later M10B–M10F milestones. No task in this plan may begin until the human
approves the M10A design, and no task may implement Phase 11 evaluation or
Phase 12 release work.

## Architecture

Preserve the two authority boundaries:

- AI extracts untrusted fields/evidence; deterministic Python code and human
  approval control validation, policy, state, and side effects.
- n8n triggers, transports, schedules, notifies, and routes; Python owns
  persistence, claims, retry classification, state transitions, and provider
  contracts.

Reuse the existing Phase 2 idempotency record, Phase 6 command/ETag contracts,
Phase 7 intake lifecycle, Phase 8 notification lifecycle, and M9B durable sync
coordinator. Do not add a queue, event bus, worker framework, distributed
tracing stack, hosted monitoring, OAuth/SSO, Vault, WAF, Kubernetes, or a
generic policy engine.

The existing identity meanings remain distinct:

- request key/fingerprint and Gmail source identity are authoritative replay
  keys in their respective boundaries;
- document SHA-256 and customer+PO are supporting duplicate/integrity signals;
- Odoo/HubSpot stable identities and M9B receipts are authoritative external
  reconciliation mechanisms;
- request/workflow IDs are correlation-only;
- notification claim tokens and review ETags are delivery/concurrency
  controls, not universal idempotency keys.

## Tech stack and dependency policy

Use Python 3.12, FastAPI, Pydantic, SQLAlchemy/Alembic, PostgreSQL, existing
Docker Compose, self-hosted n8n, existing pytest/Ruff/mypy, and GitHub Actions.
Prefer the standard library for request context, JSON logs, counters, and
bounded timing. A CI-only `pip-audit` tool may be pinned during M10C to audit
locked production Python dependencies; it must not become an application
runtime dependency. No mandatory paid service or runtime dependency is planned.

Preserve the documented `brace-expansion@5.0.9` classification unless fresh
evidence changes it: transitive, development-only frontend tooling, absent from
the production-only audit/bundle, unchanged by Phase 9, and not currently a
production blocker.

## Spec

The authoritative behavior, identity meanings, threat boundaries, failure
matrix, observability contract, security posture, milestone gates, and explicit
Phase 11/12 exclusions are defined in the [M10A design](../specs/2026-10-05-phase-10-reliability-security-hardening-design.md).
The implementation work must satisfy that design and the existing committed
Phase 0–9 contracts. Where implementation evidence contradicts the plan, stop,
record the concrete contradiction, and update the design before changing scope.

## Global constraints

- Work only on the designated Phase 10 milestone branch.
- Keep every implementation commit focused and inspect the diff before commit.
- Do not force-delete, rewrite, squash, or amend Phase 9 history.
- Do not add a `customer_reference + po_number` uniqueness constraint without a
  new approved domain contract.
- Do not make `/ready` depend on Gmail, Slack, Gemini, Odoo, HubSpot, or n8n.
- Do not claim physical exactly-once provider execution, uptime/SLA guarantees,
  production user identity, or public-internet security coverage.
- Automated tests must use fakes and fault injection; normal CI must not call
  live AI/providers or perform external writes.
- Do not log tokens, authorization headers, raw documents/prompts, provider
  bodies, email/Slack payloads, SQL/database URLs, or full exception strings.
- New migrations are allowed only when a demonstrated recovery gap cannot be
  fixed with the existing durable records and transactions.
- Each milestone ends with a clean working tree and the verification result in
  its closeout report.

## M10B — Cross-Boundary Idempotency, Failure Semantics & Recovery Hardening

### Boundary

Own the concrete Phase 7 post-claim database-loss gap, the complete retry-owner
contract, and any proven mismatch between `FAILED_RETRYABLE` and `FAILED_FINAL`.
Do not replace the Phase 7/8/9 state machines or add a second synchronization
lifecycle.

### Expected files and areas

- `src/opsflow/orchestration/claims.py` and
  `src/opsflow/application/orchestration.py`: make a committed intake claim
  recoverable after a later persistence failure, with one durable owner and
  fail-closed ordinary duplicate behavior.
- `src/opsflow/orchestration/failures.py` and related domain/application
  contracts: make the failure-code/classification table explicit and bounded.
- `src/opsflow/application/order_sync.py` and
  `src/opsflow/order_sync/contracts.py`: review only the existing M9B
  classification and ownership paths; change the catch-all or configuration
  behavior only when a failing test proves a concrete ambiguity or unsafe
  automatic retry.
- `src/opsflow/persistence/models.py`, repositories, and one new Alembic
  migration only if the minimal recovery marker/lease cannot be represented by
  the existing order/audit records. If a schema change is required, it must be
  bounded, indexed, reversible, and preserve existing rows.
- `workflows/n8n/opsflow-sandbox-intake.json`,
  `workflows/n8n/opsflow-gmail-intake.json`, and
  `workflows/n8n/opsflow-order-sync.json`: update only graph-contract tests or
  documentation if Python ownership changes; do not add a business retry loop.
- New/updated tests under `tests/unit/orchestration/`,
  `tests/unit/application/`, `tests/integration/test_phase7_*`, and
  `tests/integration/test_phase9_*`.

### Interfaces to preserve or define

- Intake claim/recovery returns one of the existing bounded outcomes and never
  runs document processing or a provider call without a durable ownership
  decision.
- A repeated delivery with the same source identity is either a safe replay,
  a recoverable stale claim, or a terminal stand-down; it must not create a
  second order/source graph.
- Every processing/provider failure maps to one bounded failure origin,
  retryability, next owner, and observable audit/notification result.
- M9B continues to expose one `execute-next` coordinator, one lease/fence, one
  sync row, and first-missing-step receipt recovery.

### TDD sequence

1. Add failing PostgreSQL integration tests that simulate a committed Phase 7
   claim followed by database failure before extraction completion/failure
   persistence. Assert the next same-identity delivery cannot stand down
   invisibly and cannot execute concurrently with another owner.
2. Add failing tests for database recovery, stale/expired recovery, source or
   fingerprint mismatch, ordinary duplicate delivery, and human Retry
   generation consumption. Preserve the existing tests that prove ordinary
   duplicate stand-down.
3. Add a table-driven failure classification test for document failure, AI
   timeout/unavailable, AI invalid output, business provider failure,
   validation facts changed, provider configuration, provider invalid response,
   reconciliation conflict, lease exhaustion, and lost receipt persistence.
   The test must name exactly one retry owner and whether automatic retry is
   allowed.
4. Implement the smallest durable change that makes the tests pass. Keep
   provider execution outside open database transactions and make all recovery
   writes transactional.
5. Add regression tests for Phase 9 partial synchronization: Odoo receipt then
   HubSpot failure, provider success followed by lost OpsFlow receipt, stable
   replay, stale fencing, and human retry generation reset without losing
   receipts.
6. Refactor only after the new concurrency/replay tests pass; retain bounded
   error codes and existing audit semantics.

### Verification and commit gate

Run, as applicable:

- `uv run pytest tests/unit/orchestration tests/unit/application/test_orchestration.py -q --no-cov`
- `uv run pytest tests/integration/test_phase7_concurrency.py tests/integration/test_phase7_failure_matrix.py -q --no-cov`
- `uv run pytest tests/integration/test_phase9_order_sync_claims.py tests/integration/test_phase9_order_sync_api.py tests/integration/test_phase9_order_sync_odoo.py tests/integration/test_phase9_order_sync_hubspot.py -q --no-cov`
- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src/opsflow`
- `git diff --check`

Commit the focused result as:
`fix(reliability): recover claimed work and clarify retry ownership`.

### Acceptance criteria

- A post-claim database interruption is recoverable and visible, with one
  Python owner and no unsafe duplicate execution.
- Ordinary same-input duplicates still stand down/replay safely.
- `FAILED_RETRYABLE` versus `FAILED_FINAL` behavior is explicit and tested;
  human Retry remains the owner where the existing contract requires it.
- M9B receipt recovery and stable provider identities remain intact.
- No n8n workflow gains business-state or provider-effect retry ownership.

## M10C — Security Boundaries, Input Safety & Secret Hygiene

### Boundary

Harden HTTP/resource/auth/error/dependency boundaries that are demonstrably
missing. Preserve Phase 3 parser limits, Phase 4 prompt authority, Phase 6
development roles, Phase 7/9 service auth, and Phase 8/9 provider redaction.

### Expected files and areas

- Add a small ASGI receive/body-limit module under `src/opsflow/` and wire it in
  `src/opsflow/main.py`; keep route-specific document limits as the source of
  truth for accepted document bytes.
- `src/opsflow/api/schemas.py`, `review_schemas.py`, notification/orchestration
  schemas, and domain/application boundary validators: add a reviewed cap table
  for strings, counts, headers, and command bodies without changing business
  semantics.
- `src/opsflow/api/orders.py` and auth dependencies: close the unauthenticated
  core route boundary using existing server-resolved development/service
  credentials. Keep `/health` and `/ready` probeable.
- `src/opsflow/main.py` and route classes: standardize safe validation and
  unexpected-error responses without echoing input/provider diagnostics.
- `settings.py`, `.env.example`, `.gitignore`, workflow exports, and tests:
  retain secret-safe configuration and document the development-token limit.
- `.github/workflows/ci.yml`, `Makefile`, and a small dependency-policy doc or
  script: add repeatable production-only Python/frontend dependency checks and
  preserve the brace-expansion exception record.
- New/updated tests under `tests/integration/` and `tests/unit/test_settings.py`,
  including sentinel secret/error tests.

### Proposed cap table to ratify before implementation

Use the smallest values compatible with current fixtures and provider/domain
contracts. The implementing agent must verify existing fixtures before locking
the values:

- multipart request: existing 10 MiB document limit plus a bounded envelope;
- JSON API body: 512 KiB; notification command body: 16 KiB;
- existing idempotency key 128, message ID 256, filename 255;
- ordinary business identifiers 256 characters, descriptions 2,048,
  storage references 2,048, MIME type 128;
- at most 200 order/review lines and 32 metadata pairs per source document;
- metadata keys 128, values 512, evidence quotes 4,096, rejection reasons 500;
- bounded list/query limits remain at most 100.

If a current contract requires a different value, record the evidence in the
design review and change the table before implementation; do not silently
truncate input.

### TDD sequence

1. Add failing ASGI/API tests proving oversized JSON and multipart envelopes
   are rejected before order creation, while a document exactly at the current
   10 MiB application limit remains accepted by the transport budget.
2. Add failing exact-boundary/over-boundary schema tests for every cap-table
   field and collection. Assert safe status/code/message and no input echo.
3. Add failing auth tests for core order reads/create, orchestration routes,
   review roles, and token overlap. Assert development-auth wording remains
   explicit and no browser actor/role claim is accepted.
4. Add failing error-redaction tests using bearer tokens, provider bodies,
   database URLs, raw document sentinels, and traceback sentinels.
5. Add the minimal middleware/schema/auth/error changes; run existing Phase
   3/4/6/8/9 tests to prevent boundary regressions.
6. Add the dependency policy command/check. It must inspect locked production
   dependencies, keep frontend dev-only advisory classification explicit, and
   fail only on the agreed severity policy rather than arbitrary audit noise.
7. Verify all `text()`/raw SQL uses remain fixed and parameterized; add a small
   source or repository regression guard instead of adding an ORM layer.

### Verification and commit gate

Run:

- `uv run pytest tests/integration/test_phase7_transport.py tests/integration/test_phase8_notification_api.py tests/integration/test_phase9_order_sync_api.py -q --no-cov`
- the new HTTP-limit, auth, error-redaction, and dependency-policy tests
- `uv run pytest tests/unit/test_settings.py tests/unit/extraction/test_gemini.py -q --no-cov`
- `npm audit --omit=dev --audit-level=high --prefix web`
- the pinned Python production dependency audit selected by the review
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/opsflow`
- `git diff --check`
- pinned Gitleaks v8.28.0 against the full history before closeout

Commit as:
`fix(security): bound HTTP inputs and preserve secret-safe boundaries`.

### Acceptance criteria

- Oversized/malformed request bodies and hostile field/count inputs fail closed
  before uncontrolled resource use or order creation.
- Core order access has an explicit existing-token boundary; review and
  orchestration roles remain server-resolved and separate.
- Safe error responses and logs do not expose secret/payload/provider/SQL
  details.
- Existing document parser, prompt, SQLAlchemy, and provider-adapter controls
  remain intact.
- Dependency checks are repeatable at `$0` and the known transitive frontend
  advisory is not “fixed” by an unjustified upgrade.

## M10D — Structured Observability, Correlation & Operational Health

### Boundary

Add only lightweight, allowlisted operational visibility. Do not build a
distributed tracing or hosted monitoring system, and do not turn readiness into
provider health.

### Expected files and areas

- New standard-library modules under `src/opsflow/observability/` for request
  context, structured events, redaction, duration measurement, and process-local
  counters/histograms.
- `src/opsflow/main.py` middleware/handlers and route boundaries for
  `X-Request-ID`, bounded workflow-execution correlation, response correlation,
  safe request outcome logs, `/metrics`, and a separate integration-health view.
- Existing orchestration, notification, extraction/provider, and order-sync
  seams for order/provider/step/failure/duration events; do not log payloads.
- `tests/unit/observability/`, readiness/API integration tests, and provider
  diagnostic tests.

### Interfaces

- Request context exposes request ID and optional workflow ID to application
  code without making either an auth or idempotency input.
- Event emission accepts only a bounded event name and allowlisted scalar
  fields; redaction occurs before serialization.
- Metrics registry provides bounded counters and duration buckets and can be
  read without changing business state.
- Integration-health output distinguishes configured/unconfigured, healthy,
  unavailable, and not-checked; active checks are explicit, timeout-bounded,
  and never required by `/ready`.

### TDD sequence

1. Add failing tests for generated/supplied request IDs, bounded workflow IDs,
   response header behavior, and correlation through a synthetic intake.
2. Add failing redaction tests with tokens, raw documents, prompts, provider
   bodies, SQL URLs, email/Slack payloads, and long exception values.
3. Add failing metrics tests for request outcomes, provider duration, retry
   count, sync step outcome, and bounded failure labels.
4. Add failing readiness/health tests proving database-only readiness remains
   unchanged when providers are absent or unavailable.
5. Implement the standard-library layer and instrument only the justified
   boundaries. Record Gemini usage only when the provider exposes trustworthy
   metadata; otherwise assert `unavailable`.
6. Refactor duplicate instrumentation only after event and metric tests pass.

### Verification and commit gate

Run:

- `uv run pytest tests/integration/test_readiness.py -q --no-cov`
- the new observability/redaction/metrics/integration-health tests
- provider and order-sync diagnostic tests that assert no raw details leak
- `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/opsflow`
- `git diff --check`

Commit as:
`feat(observability): add bounded correlation and operational telemetry`.

### Acceptance criteria

- Synthetic requests and provider failures produce machine-readable, bounded,
  correlated events with duration and safe failure fields.
- `/ready` remains a database-only readiness decision.
- Optional LLM usage is truthful and provider-evidence-based; absent usage is
  not estimated.
- Metrics are local, small, and useful; no hosted or paid infrastructure is
  introduced.

## M10E — Adversarial Resilience & Whole-System Failure Drills

### Boundary

Exercise the existing system-wide contracts with fakes and controlled database
faults. Live sandbox services are explicit opt-in only and must never run in
normal CI.

### Expected files and areas

- New bounded fault-injection helpers under `tests/fixtures/` or the existing
  test helper areas; keep them provider-free and deterministic.
- New `tests/integration/test_phase10_failure_drills.py` plus focused unit tests
  for replay/fault combinations.
- Existing fake extraction, business-data, notification, Odoo, and HubSpot
  adapters; existing PostgreSQL integration fixture and migration isolation.
- Clean-clone instructions/checks in `docs/development/` only if needed to make
  Phase 10 reproducibility explicit.

### Required scenarios

Exercise each design-matrix row at least once:

- duplicate intake/redelivery and duplicate storms within a bounded synthetic
  count;
- malformed, corrupt, oversized, and prompt-injection documents;
- LLM timeout, unavailable, malformed, invalid schema, and lost response;
- PostgreSQL unavailable before creation, during transaction, after claim, and
  after an external receipt where the existing M9B model permits it;
- Gmail and Slack rejected send, timeout, lost outcome, lease recovery, and
  attempt-three finalization;
- Odoo timeout/commit-then-timeout, invalid response, bad configuration, and
  replay;
- HubSpot timeout/invalid response, wrong portal, company/deal partial sync,
  and recovery after Odoo success;
- stale intake/sync/notification claims and restored dependencies;
- repeated n8n graph invocations without a provider/business duplicate.

### TDD/verification sequence

1. Write scenario assertions before fault helpers: business/HTTP result,
   durable state, sole retry owner, external-effect possibility, replay result,
   and observable signal.
2. Add the smallest deterministic fault controls to fakes/fixtures; do not
   monkeypatch production code in a way that bypasses the transaction boundary.
3. Run the complete provider-free M10E matrix against isolated PostgreSQL.
4. Run the repository quality gates and inspect logs/metrics for secret/payload
   leakage.
5. If a real provider boundary must be proved, provide an explicit opt-in
   command and sandbox-only cleanup; do not make it a default test or CI job.
6. Verify a clean clone can install, migrate, run the provider-free matrix,
   validate workflow exports, and run the documentation/link/secret checks.

### Verification and commit gate

Run:

- `uv run pytest tests/integration/test_phase10_failure_drills.py -q --no-cov`
- all relevant Phase 7/8/9 integration tests
- `make check`
- `docker compose config --quiet`
- clean-clone setup and provider-free verification commands
- pinned full-history Gitleaks scan and changed-content scan
- relative Markdown-link validation and `git diff --check`

Commit as:
`test(resilience): add bounded whole-system fault drills`.

### Acceptance criteria

- Every required failure scenario has deterministic expected state and one
  retry owner.
- No tested failure causes duplicate unsafe execution, invalid automatic
  execution, silent corruption, secret exposure, or undetected inconsistent
  state.
- Normal CI remains free of unexpected provider calls/writes and mandatory cost
  remains `$0`.
- Clean-clone verification is reproducible.

## M10F — Independent Phase 10 Audit & Closeout

### Boundary

Perform a fresh review by a separate audit pass/person when available. The
audit must not simply quote M10B–M10E implementation reports.

### Expected files and areas

- `docs/audits/phase-10-audit.md` as the durable audit record.
- Final roadmap, README, development guide, architecture overview, design,
  plan, CI, migration, test, and Git/history review.

### Audit checklist

- threat model matches actual trust boundaries;
- cross-boundary idempotency and identity meanings are correct;
- one retry owner per failure and correct retryable/final semantics;
- input/resource limits and prompt/data authority boundaries are tested;
- development auth is not described as production identity;
- secrets, errors, logs, workflow exports, tests, and history are clean;
- dependency policy and the brace-expansion classification are evidence-based;
- structured logs, correlation, latency, usage, metrics, and health semantics
  are bounded and useful;
- `/ready` remains core database readiness;
- M10E fault-injection and clean-clone evidence exists;
- no unresolved Critical/High/Medium finding remains;
- Phase 11 and Phase 12 remain outside the implementation;
- human approval is recorded before Phase 10 is marked complete.

### Verification and commit gate

Run the full applicable repository gates, including `make check`,
`git diff --check`, relative Markdown-link validation, pinned full-history
Gitleaks, dependency audits, migration/clean-clone checks, and the complete
M10E fault matrix. Commit the audit as:
`docs(audit): close Phase 10 hardening review`.

Only after the independent audit and human approval may the roadmap change
Phase 10 to `COMPLETE` and M10F to `COMPLETE`.

## Review focus

Reviewers should pay particular attention to:

- whether the M10B change repairs a real post-claim database failure without
  making ordinary duplicate redelivery unsafe;
- whether every retry has one owner and whether n8n remains thin;
- whether stable external identities/receipts are reused rather than replaced;
- whether input caps are bounded without truncation or unsupported business
  assumptions;
- whether development bearer tokens are described honestly and core routes
  fail closed;
- whether logs/metrics are allowlisted and useful without payload leakage;
- whether `/ready` remains independent of external integrations;
- whether dependency changes are justified by a concrete audit requirement;
- whether tests are network/provider-safe by default;
- whether the implementation quietly introduces Phase 11 benchmarks or Phase
  12 release work.

## M10A verification and documentation commit

M10A itself must run only documentation/repository checks:

- status and branch/worktree checks against the verified starting SHA;
- a repository-local Markdown relative-link validator;
- `git diff --check`;
- pinned Gitleaks v8.28.0 changed-content scan;
- lightweight status/reference searches proving Phase 9 is complete, Phase 10
  is in progress with M10A complete, and Phases 11–12 are not started;
- no application test suite and no live provider scenario.

Commit the M10A result as:
`docs(phase10): define reliability security hardening plan`.

## M10A acceptance criteria

- Actual Phase 0–9 implementation, tests, migrations, workflows, settings, CI,
  Compose, and final audit records were inspected.
- Every Phase 10 roadmap requirement appears in the design gap matrix.
- Threat and failure models match actual boundaries and identify one retry owner.
- Existing sufficient controls are explicitly preserved.
- M10B–M10F have observable gates and no production Phase 10 behavior is
  implemented by M10A.
- No mandatory cost or unsupported enterprise architecture is introduced.
- Documentation status and architecture prose are consistent.
