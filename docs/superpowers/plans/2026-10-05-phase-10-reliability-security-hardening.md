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
bounded timing. M10C may pin `pip-audit==2.10.1` as a CI/developer-only tool;
it must not become an application runtime dependency. No mandatory paid
service or runtime dependency is planned.

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
- `/health` and `/ready` remain unauthenticated; `/ready` remains database-only.
- Core order reads use server-resolved human development view access; structured
  `POST /v1/orders` uses only the existing orchestration/service bearer. These
  fixed tokens are a local/demo development boundary, not production identity,
  OAuth, SSO, session management, or internet-facing IAM.
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

The current Phase 7 claim commits `PROCESSING` and
`ORDER_PROCESSING_STARTED`; parsing/provider work and later persistence happen
outside that transaction, and Phase 7 has no durable lease/fencing token. A
matching redelivery that sees bare `PROCESSING` or `EXTRACTED` must therefore
continue to stand down unless M10B has proved stale ownership safely. M10B must
not make every such redelivery resumable.

Before selecting schema columns or timeout values, inspect and record all Phase
7 parser/processing/provider timeouts, n8n intake request timeout and
initial-plus-two transport retries, configured Phase 7 business-data provider
timeout, relevant database operation bounds, and the longest valid single
intake execution. If these do not define a defensible total maximum, define a
bounded total execution budget first. The recovery lease must exceed that
complete budget. The likely minimal mechanism is a durable bounded intake
execution lease plus fencing token; whether that requires a small migration is
an M10B evidence decision, not an M10A implementation decision. Do not build a
generic worker framework or reuse the M9B sync state machine.

### Expected files and areas

- `src/opsflow/orchestration/claims.py` and
  `src/opsflow/application/orchestration.py`: make a committed intake claim
  recoverable after a later persistence failure, with one durable owner,
  bounded stale recovery, and fail-closed ordinary duplicate behavior. A stale
  token must be rejected when it attempts to persist after a newer owner has
  taken over.
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

The implementation must prove: active ownership cannot be reclaimed; stale
ownership can be recovered after the defined bound; stale workers cannot
persist over a newer owner; normal duplicates stand down; human Retry
generations remain intact; source/fingerprint mismatches do not create a
second graph; and n8n does not gain business retry state.

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

1. Add failing PostgreSQL concurrency tests for a committed Phase 7 claim
   followed by database loss after claim and after extraction/provider work.
   Assert the next same-identity delivery cannot stand down invisibly and
   cannot execute concurrently with an active owner.
2. Inspect and record the actual Phase 7/n8n/provider/database timing bounds;
   define a bounded total execution budget if the current path has no
   defensible maximum. Only then add failing tests for active duplicate
   stand-down, stale lease recovery, stale-token persistence rejection, source
   or fingerprint mismatch, ordinary duplicate delivery, and human Retry
   generation consumption.
3. Add a table-driven failure classification test for document failure, AI
   timeout/unavailable, AI invalid output, business provider failure,
   validation facts changed, provider configuration, provider invalid response,
   reconciliation conflict, lease exhaustion, and lost receipt persistence.
   The test must name exactly one retry owner and whether automatic retry is
   allowed.
4. Implement the smallest durable change that makes the tests pass. If a
   lease/fence migration is required, justify its columns, indexes, bounds,
   compatibility with existing rows, and rollback/readiness behavior. Keep
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
- the new PostgreSQL tests for concurrent active duplicates, stale lease
  recovery, stale-token persistence rejection, database loss after claim,
  database loss after extraction/provider work, ordinary stand-down, human
  Retry, and source/fingerprint mismatch
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
- The selected lease/fence bound is derived from measured/declared complete
  intake execution limits; active owners cannot be reclaimed and stale tokens
  cannot persist after takeover.
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
- `src/opsflow/api/orders.py` and auth dependencies: require existing
  server-resolved human `require_view_access` for `GET /v1/orders`,
  `GET /v1/orders/{order_id}`, and `GET /v1/orders/{order_id}/audit`; require
  only the existing orchestration/service bearer for `POST /v1/orders`. Keep
  `/health` and `/ready` probeable and unauthenticated. Do not add a human role
  or accept browser actor/role claims.
- `src/opsflow/main.py` and route classes: standardize safe validation and
  unexpected-error responses without echoing input/provider diagnostics.
- `settings.py`, `.env.example`, `.gitignore`, workflow exports, and tests:
  retain secret-safe configuration and document the development-token limit.
- `.github/workflows/ci.yml`, `Makefile`, and a small dependency-policy doc or
  script: add repeatable production-only Python/frontend dependency checks and
  preserve the brace-expansion exception record.
- New/updated tests under `tests/integration/` and `tests/unit/test_settings.py`,
  including sentinel secret/error tests.

### Ratified cap table

Implement these exact resource budgets. The existing 10 MiB document parser
limit remains authoritative; a stricter current field limit remains
authoritative and must not be loosened. Exact boundary values pass and
boundary+1 values fail safely; do not truncate.

| Boundary or field | Maximum |
| --- | ---: |
| Absolute HTTP request body | 12 MiB |
| Orchestration multipart request | 11 MiB |
| Accepted document bytes | 10 MiB, exact Phase 3 limit |
| Ordinary JSON business/review/core command body | 512 KiB |
| Notification result command body: `POST /v1/integrations/notifications/{notification_id}/outcome` | 16 KiB; bodyless claim and unrelated routes are excluded |
| Order/review lines | 200 |
| Source documents on structured core order creation | 8 |
| Metadata pairs per source document | 32 |
| List/query result limit | 100 |
| Ordinary business identifiers, including customer reference, PO number, SKU | 256 characters |
| Filename/name | 255 characters |
| MIME type | 128 characters |
| Message ID | 256 characters |
| Description | 2,048 characters |
| Storage/source reference | 2,048 characters |
| Metadata key | 128 characters |
| Metadata value | 512 characters |
| Evidence quote/text for bounded review display | 4,096 characters |
| Rejection reason | 500 characters |
| Client quantity/price Decimal significant digits | 28 |
| Client quantity/price Decimal fractional digits | 8 |

Apply the source-document count and common string/Decimal policy to every
structured and review transport schema, including alternate routes. Preserve
positive quantity and non-negative price semantics; do not change trusted-price
tolerance or other monetary rules.

### TDD sequence

1. Add failing ASGI/API tests proving oversized JSON and multipart envelopes
   are rejected before order creation, while a document exactly at the current
   10 MiB application limit remains accepted by the transport budget.
2. Add failing exact-boundary/over-boundary schema tests for every cap-table
   field and collection. Assert safe status/code/message and no input echo.
3. Add failing auth tests proving each core read accepts any configured
   REVIEWER/APPROVER/ELEVATED_APPROVER through server-resolved
   `get_operator_context`/`require_view_access`; `POST /v1/orders` accepts only
   the orchestration bearer; a human token cannot create; and an orchestration
   token cannot read/review/approve. Assert `/health` and `/ready` stay public,
   no browser actor/role claim is accepted, and the documentation calls the
   fixed credentials local/demo development authentication only.
4. Add failing error-redaction tests using bearer tokens, provider bodies,
   database URLs, raw document sentinels, and traceback sentinels.
5. Add the minimal middleware/schema/auth/error changes; run existing Phase
   3/4/6/8/9 tests to prevent boundary regressions.
6. Add the dependency policy command/check using the verified pinned tool
   strategy:

   ```sh
   set -o pipefail
   uv export --frozen --no-dev --no-emit-project --format requirements.txt \
     | uvx --from 'pip-audit==2.10.1' pip-audit \
         --requirement /dev/stdin --no-deps --disable-pip --strict
   ```

   This audits the frozen production-only, hashed requirements exported from
   the committed `uv.lock`, excludes `dev`, does not mutate the lockfile, and
   does not install into the runtime image. `--no-deps` and `--disable-pip`
   avoid a second dependency-resolution path; `--strict` fails incomplete
   collection, and `set -o pipefail` propagates an export failure. This
   verified workflow is preferred over claiming that `pip-audit --locked`
   directly audits `uv.lock`.
   Any production Python vulnerability fails by default. A visible exception
   must include vulnerability ID, technical rationale, affected/not-affected
   analysis, and human approval; no `|| true`. Keep
   `npm audit --omit=dev --audit-level=high` and preserve the known
   `brace-expansion@5.0.9` transitive development-only classification unless
   fresh evidence changes it.
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
- The 12 MiB/11 MiB/512 KiB/16 KiB budgets, source-document count of 8,
  collection/string caps, and 28-digit/8-fraction Decimal caps are enforced
  across all applicable structured/review transports without truncation.
- Core order access has the exact existing-token boundary: human view access
  for the three reads and orchestration service auth for structured creation;
  review and orchestration roles remain server-resolved and separate.
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
- Metrics registry provides bounded counters and duration buckets with only
  fixed dimensions: route class/name, HTTP status/status class, provider,
  operation, state, retry outcome, and bounded failure code. It never labels
  request/workflow/order/customer/PO/filename/actor/email/raw-exception data;
  process-local reset on restart is documented.
- Integration-health output is passive and human-view-protected. It
  distinguishes configured/unconfigured, healthy/unavailable from the last
  observed real operation, and not-checked/no observation yet, with bounded
  last failure code/time where justified. It never actively calls Gemini,
  Gmail, Slack, Odoo, HubSpot, or n8n. `/ready` remains database-only.

### TDD sequence

1. Add failing tests for generated/supplied request IDs, bounded workflow IDs,
   response header behavior, and correlation through a synthetic intake.
2. Add failing redaction tests with tokens, raw documents, prompts, provider
   bodies, SQL URLs, email/Slack payloads, and long exception values.
3. Add failing metrics tests for request outcomes, provider duration, retry
   count, sync step outcome, and bounded failure labels.
4. Add failing readiness/health tests proving database-only readiness remains
   unchanged when providers are absent or unavailable, diagnostics require
   existing human view access, and no diagnostic request calls a provider.
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
- Metrics are local, small, and useful, use only bounded dimensions, reset on
  restart by design, and never use high-cardinality identifiers as labels; no
  hosted or paid infrastructure is introduced.

### M10D implementation record — human-approved closeout

The candidate implementation uses the standard library only: pure-ASGI
request correlation outside the existing streaming body limiter, one
allowlisted JSON event logger, fixed process-local counters/histograms, and
human-view-only `/v1/operations/metrics` and `/v1/operations/integrations`
diagnostics. Provider observations are attached at the existing Gemini,
Phase 9 executor, and authenticated notification-outcome seams. `/ready` is
unchanged and database-only. The installed `google-genai==2.24.0` Interaction
object supplies trustworthy `usage` counts, so optional non-negative input,
output, and total counts are exposed without estimation. The four n8n
workflows use `={{ $execution.id }}` only as a stable diagnostic header on
OpsFlow API calls; no workflow business-state or retry ownership was added.
M10E/M10F, Phase 11, and Phase 12 remain outside this implementation.

#### Independent review remediation and human-approved closeout

The initial candidate was `424ba74b91b3fae13721e7eb93f20a3dad9ad3f5`.
Independent review recorded three MEDIUM findings: M10D-01 (forged workflow
metadata and non-availability order-sync failures could alter passive health),
M10D-02 (the trusted-data Odoo seam was not observed and Phase 9 provider
metrics were incomplete), and M10D-03 (notification events omitted provider
and order correlation). RED regressions reproduced each finding before the
fix.

The remediation keeps n8n health passive and truthful: only a successful
authenticated workflow-bound response can mark n8n healthy, and inbound
failures never mark it unavailable. Odoo/HubSpot provider health uses the
explicit operational failure set `PROVIDER_ERROR`, `PROVIDER_TIMEOUT`,
`PROVIDER_UNAVAILABLE`, `PROVIDER_RATE_LIMIT`, and
`PROVIDER_INVALID_RESPONSE`; configuration, pending/rejected, business/data,
reconciliation, and worker-state outcomes leave prior health unchanged.
`OdooERPAdapter.get_validation_data()` is one logical
`ODOO_LOOKUP` provider operation. Phase 9 Odoo/HubSpot steps add exactly one
provider counter and duration observation while retaining one
`order_sync_step_outcome` event and no duplicate provider event. Notification
events now include only the safe provider/channel and order UUID.

The minor metrics-endpoint wording issue was resolved by describing the
endpoint as a bounded process-local snapshot without claiming exclusion from
later HTTP completion accounting. No migration, dependency, lockfile,
workflow, or M10E/M10F change was introduced. The targeted independent
re-review returned `PASS` with no unresolved High or Medium findings. Human
approval records M10D `COMPLETE` against technical SHA
`cf0b331864ca2cc5246aa32c7ce12827b79284d0`. At M10D closeout, M10E–M10F
were `NOT STARTED`; M10E is now `IN PROGRESS` and M10F remains `NOT STARTED`,
while Phase 10 remains `IN PROGRESS`.

## M10E — Adversarial Resilience & Whole-System Failure Drills

**Status:** M10E `IMPLEMENTED — PENDING HUMAN REVIEW`; M10F `NOT STARTED`; Phase 10 `IN PROGRESS`; Phases 11–12 `NOT STARTED`.

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

### M10E implementation record — candidate closeout

The candidate adds 12 executable provider-free scenario tests plus one explicit
retry-owner matrix assertion, covering 18 bounded failure rows across intake
duplicates and conflicts, document and prompt authority, provider failures,
PostgreSQL loss and fencing, notification attempts, Odoo/HubSpot replay,
repeated n8n invocation, and M10D diagnostic non-leakage. Existing Phase 2–9
helpers provide the real PostgreSQL transactions, durable claims, receipt
recovery, and state-machine assertions; no generic chaos framework or live
provider path was added.

One real defect was found and repaired: an unavailable PostgreSQL connection
before Phase 7 creation could escape as raw `ConnectionRefusedError` instead of
the existing bounded orchestration `503`. Commit `38ad89f` treats raw socket
`OSError` connection failures as persistence failures at the existing Phase 7
boundaries, preserving transaction and retry ownership semantics. The RED
drill is retained in `test_database_unavailable_before_claim_is_bounded_and_provider_free`;
the full M10E matrix is green.

Verification used disposable PostgreSQL databases and provider fakes only. The
candidate passed the integration suite, repository quality gates, dependency
audit, migration/Compose checks, Markdown-link validation, and pinned
Gitleaks scans. A future drill can still fail visibly if PostgreSQL remains
unavailable; M10E does not claim infinite retries or exactly-once physical
execution. M10E is `IMPLEMENTED — PENDING HUMAN REVIEW`; M10F remains
`NOT STARTED`, and Phase 10 remains `IN PROGRESS`.

### M10E independent-review remediation record

The initial candidate was `2397244fc594c8a6986bd84b86fd998bf70e3dd9`.
Independent review recorded:

- M10E-01 MEDIUM — the focused matrix did not directly cover the complete
  approved corrupt-document, Gemini-adapter, Gmail/Slack, Odoo, HubSpot, and
  repeated n8n-equivalent scenario set;
- M10E-02 MEDIUM — retry-owner rows were prose-only and included an ambiguous
  invalid-response owner;
- M10E-03 MEDIUM — failure observability leak checks did not inspect the full
  required sentinel set in both structured events and metric snapshots.

The remediation expands the focused matrix to 21 executable provider-free
scenario tests plus one matrix assertion and 34 explicit rows. It reuses the
existing Phase 2–9 helpers and real PostgreSQL/adapter seams for corrupt PDF
and XLSX handling, Gemini SDK faults, both Gmail and Slack lost outcomes and
attempt bounds, Odoo and HubSpot transport/configuration/response/replay
faults, repeated intake/notification/order-sync calls, and failure-path
structured-event/metric non-leakage. The test-only retry-owner vocabulary is
fixed and exact: `CALLER_TRANSPORT`, `PHASE7_STALE_RECOVERY`, `HUMAN_RETRY`,
`NOTIFICATION_LIFECYCLE`, `M9B_COORDINATOR`,
`M9B_STABLE_IDENTITY_RECOVERY`, or `NONE`, with explicit durable state and
external-effect possibility per row.

The accepted production repair `38ad89f9defc3d7f846bbfa20e7f9f34c0c730dc`
was preserved. A new Odoo business-data transport guard passed: raw socket
failure remains the typed provider/business-data failure contract rather than
generic `ORCHESTRATION_UNAVAILABLE`. No additional production defect was
found; production files remain unchanged.

The reproducible clean-clone record for M10F is: use
`git clone --no-local --branch phase/10-reliability-security-hardening
<local-repository> <temporary-clone>`, check out the exact remediation SHA,
write only a synthetic ignored `.env`, start a newly named disposable
PostgreSQL/database, run `uv sync --frozen` and `npm ci --prefix web`, validate
`docker compose config --quiet`, apply and inspect Alembic in the isolated
database, run `uv run pytest tests/integration/test_phase10_failure_drills.py
-q --no-cov`, run `uv run pytest tests/unit/workflows/test_n8n_contract.py -q
--no-cov`, run the standard-library relative-Markdown checker from the M10E
plan, run `make security-audit` and pinned Gitleaks changed/full-history scans,
then
stop/remove the disposable database and delete the temporary clone. The clone
receives no original `.env`, database, SDD workspace, generated files, caches,
or credentials.

This remediation preserves the original candidate and the earlier M10E
production finding: raw PostgreSQL `ConnectionRefusedError` before claim was
fixed by `38ad89f`. M10E remains `IMPLEMENTED — PENDING HUMAN REVIEW`; M10F
remains `NOT STARTED`; Phase 10 remains `IN PROGRESS`.

The first pushed remediation run reported two Gitleaks false positives for
synthetic idempotency identities in immutable commit `be8322e`. The follow-up
renamed the current test variables and added only exact historical
commit/file/rule/line fingerprints to `.gitleaksignore`; current-file and
full-history scans pass without broad suppression.

### M10E final focused-coverage remediation

The targeted re-review of remediation
`13e5dbe69962b1cd8b897dccfdf77fa8f59bcc28` identified M10E-04 MEDIUM: the
declared Odoo transport-timeout case and the Gmail/Slack rejected and timeout
rows lacked complete executable focused evidence.

The final test-only change keeps the 34-row matrix unchanged and adds the
missing production-boundary cases to its existing composed tests:

- `OdooERPAdapter.get_validation_data()` receives an `httpx.ReadTimeout`
  through `MockTransport` and is asserted to produce
  `PROVIDER_UNAVAILABLE`, without raw timeout text, with `M9B_COORDINATOR` as
  the documented retry owner.
- The real notification claim/outcome persistence boundary is exercised for
  `GMAIL` and `SLACK`, each with `DELIVERY_REJECTED` and `TIMEOUT`, using the
  current claim token. Each remains bounded at attempt one, stores the exact
  failure code, clears the claim, and leaves the order state unchanged.

Existing Odoo 503/unavailable, malformed-response, configuration, and
stable-identity lost-response drills remain. Existing notification rate-limit,
lost-outcome, stale-claim, lease-recovery, attempt-three, and no-fourth-attempt
drills remain. A review of every `FAILURE_DRILLS` row confirms each declared
category has executable focused evidence in
`tests/integration/test_phase10_failure_drills.py` or an explicitly invoked
Phase 2–9 production-boundary assertion helper; no rows were added merely to
inflate the matrix.

No production behavior changed. The accepted `38ad89f` PostgreSQL repair and
all M10B–M10D behavior remain unchanged. The original candidate
`2397244fc594c8a6986bd84b86fd998bf70e3dd9`, first remediation
`13e5dbe69962b1cd8b897dccfdf77fa8f59bcc28`, M10E-01/02/03 findings and
dispositions, and the earlier Phase 7 `ConnectionRefusedError` finding/fix
remain in the record. M10E remains `IMPLEMENTED — PENDING HUMAN REVIEW` and
M10F remains `NOT STARTED`.

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
  is in progress with M10A complete at approved SHA
  `ab7cec323e4d45dae57e5d418bc0755175aa0a88`, and Phases 11–12 are not
  started;
- no application test suite and no live provider scenario.

Commit the M10A result as:
`docs(phase10): ratify hardening boundaries`.

## M10A acceptance criteria

- Actual Phase 0–9 implementation, tests, migrations, workflows, settings, CI,
  Compose, and final audit records were inspected.
- Every Phase 10 roadmap requirement appears in the design gap matrix.
- Threat and failure models match actual boundaries and identify one retry owner.
- Existing sufficient controls are explicitly preserved.
- M10B–M10F have observable gates and no production Phase 10 behavior is
  implemented by M10A.
- No mandatory cost or unsupported enterprise architecture is introduced.
- Documentation status and architecture prose are consistent, including the
  ratified core-route authentication, resource caps, stale-ownership contract,
  passive integration health, bounded metrics labels, and pinned dependency
  audit strategy.
