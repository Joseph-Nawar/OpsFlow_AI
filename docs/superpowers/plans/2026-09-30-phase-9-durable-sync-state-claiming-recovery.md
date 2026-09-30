# Phase 9 M9B — Durable Sync State, Claiming & Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. This repository requires a single implementer; do not use subagents.

**Goal:** Add one durable synchronization intent per approved order, fenced PostgreSQL claiming and recovery, and the authenticated `execute-next` API boundary.

**Architecture:** Python owns the synchronization row, transaction boundaries, leases, retries, bounded failure codes, step selection, and state transitions. M9B implements the real claim-and-execute coordinator behind a narrow provider-free step-executor contract and proves it with deterministic no-network fakes. Production has no configured provider executor in M9B and fails closed before claiming; M9C/M9D later supply Odoo/HubSpot behavior behind the already-tested coordinator. The new row reuses Phase 8's proven persistence and claim principles without adding another status machine or shared integration framework.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x async sessions, Alembic, PostgreSQL, pytest, Ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-09-29-phase-9-erp-crm-integrations-design.md`

## Global Constraints

- Python owns business correctness, durable state, and state transitions; n8n only orchestrates.
- Approval, its audit event, and one `order_syncs` row commit atomically.
- `APPROVED → SYNCING` occurs on the first successful claim; use existing domain states only.
- Execution remains at-least-once; local leases fence writes, and stable receipts survive retry.
- A claim lease lasts five minutes; clean budget yields do not increment `attempt_count`.
- `attempt_count` records retryable outcomes or expired-lease recovery events, not successful claims.
- Keep one row per order and derive synchronization status from the order state, claim/retry fields, and receipts; add no second state machine.
- Do not persist provider response bodies, credentials, email addresses, or stack traces.
- Add only the generic step-executor contract and coordinator needed to run M9B state transitions; do not add Odoo or HubSpot adapters, provider-specific payloads, credentials, addon, external writes, n8n workflows, or M9C–M9F behavior.
- With no executor configured, `execute-next` must return bounded 503 before claim selection or any database mutation. Injected fake executors are test-only and exercise the same coordinator that later provider adapters will use.
- HubSpot/Odoo live setup gates remain unverified; omit `hubspot_pending_operation_ref` until M9D proves it is required.
- Keep mandatory development cost at $0 and use PostgreSQL/fakes only in automated tests.

## Review Focus

1. Approval row, approval audit event, and sync intent must all roll back if any write fails.
2. A concurrent or expired claim must not permit a stale token to write a receipt or state.
3. Human retry from a sync-origin failure increments the retry generation, resets its counter, and preserves prior receipts and the uncertain step.
4. A clean execution-budget yield releases the claim without consuming an attempt or dropping any durable receipt.
5. Invalid or unauthenticated `execute-next` requests must not claim work, mutate state, or expose internal/provider diagnostics.

## Files and Responsibilities

- Create `alembic/versions/0006_phase9_order_syncs.py` for only the M9B table and constraints.
- Modify `src/opsflow/persistence/models.py` and `mappers.py` for the ORM row and validated row mapping.
- Create `src/opsflow/persistence/order_sync_repository.py` for transaction-neutral insert, claim, lock, receipt, failure, and yield operations.
- Create `src/opsflow/order_sync/contracts.py` for bounded step/failure/result values, immutable order-sync/claim/receipt contracts, and the minimal `OrderSyncStepExecutor` protocol; do not add a parallel lifecycle status enum or provider request/response contracts.
- Create `src/opsflow/application/order_sync.py` for atomic intent helpers, claim/recovery transitions, deterministic next-step selection, and `execute_next_order_sync(...)` coordination.
- Modify `src/opsflow/domain/records.py` only if the existing free-form audit event contract needs a bounded constant/type for sync lifecycle events; do not introduce a second event framework.
- Modify `src/opsflow/application/review_commands.py` so approval creates sync intent and human sync retry resets the generation in the existing transaction.
- Modify `src/opsflow/api/orchestration.py` and `src/opsflow/api/orchestration_schemas.py` for one authenticated `POST /v1/orchestration/order-sync/execute-next` boundary using existing service auth and bounded responses.
- Modify `src/opsflow/main.py` only to initialize the single executor seam as unavailable by default; do not create provider runtime configuration.
- Update `docs/roadmap/project-roadmap.md`, the M9A spec status metadata/text, and `docs/development/development-guide.md` to report M9A `COMPLETE`, M9B `IN PROGRESS`, and M9C–M9F `NOT STARTED`.
- Add `tests/unit/order_sync/__init__.py`, focused unit tests under `tests/unit/order_sync/`, and `tests/integration/test_phase9_order_sync_*.py`; extend existing persistence/API tests only where repository patterns call for it.

## Tasks

### Task 1: Add the durable order-sync schema and mapper

**Files:**
- Create `alembic/versions/0006_phase9_order_syncs.py`
- Modify `src/opsflow/persistence/models.py`
- Modify `src/opsflow/persistence/mappers.py`
- Modify `tests/unit/persistence/test_models.py`
- Modify `tests/unit/persistence/test_mappers.py`
- Create `tests/integration/test_phase9_order_sync_migrations.py`

**Interfaces:**
- Produce `OrderSyncModel` with `order_id` as primary key/FK, paired nullable claim fields, `attempt_count`, `retry_generation`, `next_attempt_at`, bounded Odoo/HubSpot receipts, optional association timestamp, nullable `in_flight_step`, paired/bounded failure fields, and timestamps. Constrain `attempt_count` to `0..3` inclusive; constrain `retry_generation` to nonnegative values without an upper bound.
- Produce `OrderSyncStep`, `OrderSyncFailureCode`, and `ExecuteNextKind` enums using only the values and classifications in the approved spec. Do not add a persisted sync status. Do not add a Company-ID unique index or an unverified HubSpot operation-handle column.
- Produce immutable `OrderSync` (all persisted fields), `OrderSyncClaim(order_id, claim_token, claim_expires_at)`, and step-specific receipt contracts: `OdooOrderReceipt(sale_order_id, sale_order_name)`, `HubSpotCompanyReceipt(company_id)`, `HubSpotDealReceipt(deal_id)`, and `HubSpotAssociationReceipt(confirmed_at)`.
- Produce `order_sync_from_model(row: OrderSyncModel) -> OrderSync` and `order_sync_to_model(sync: OrderSync) -> OrderSyncModel` with repository-style defensive contract validation.
- Define the receipt union as those four receipt types; avoid raw provider response or generic JSON fields.
- Define one narrow `OrderSyncStepExecutor` protocol that accepts an order identity and the next approved `OrderSyncStep`, returning only that step's bounded receipt/result or a bounded `OrderSyncFailureCode` plus optional retry delay. It carries no provider URL, payload, credential, or account-specific API shape.
- Migration `0006_phase9_order_syncs` must be a child of `0005_phase8_notification_deliveries`; follow existing named-constraint/index conventions.

- [ ] **Step 1: Write failing schema and mapper tests** named `test_order_sync_mapper_round_trips_receipts_and_bounded_codes` and `test_order_sync_model_rejects_invalid_claim_and_counter_values`. Assert exact columns, named checks for paired claim fields, attempt/retry counters, bounded step and failure values, order FK/primary key, partial uniqueness for non-null Odoo sale-order and HubSpot Deal receipt IDs only, and round-trip/rejection behavior.
- [ ] **Step 2: Run those focused tests and migration test to verify the expected missing-model/revision failures.**

Run: `uv run pytest tests/unit/persistence/test_models.py tests/unit/persistence/test_mappers.py tests/integration/test_phase9_order_sync_migrations.py -q --no-cov`

Expected: focused failures because M9B's row, mapping, and migration do not exist yet; no unrelated collection or environment error.

- [ ] **Step 3: Implement the model, mapper, and one Alembic revision.** Keep the pending HubSpot operation handle absent until the live setup gate proves it is required.
- [ ] **Step 4: Verify clean and incremental migration paths using the isolated migration-test database.** Test `base → head`; separately migrate a database at `0005`, preserve an existing Phase 8 notification/order row through `0006`, then downgrade only to `0005` and re-upgrade. Downgrading `0006` drops the new `order_syncs` table and its M9B data, so use downgrade only in the disposable migration-test database before Phase 9 sync data exists; never use destructive reset/downgrade as a substitute for a correct upgrade or point these tests at the development database.

Run: `uv run pytest tests/integration/test_phase9_order_sync_migrations.py -q --no-cov` with `OPSFLOW_MIGRATION_TEST_DATABASE_URL` already configured to a separate PostgreSQL database.

Expected: all schema/constraint assertions pass; Alembic ends at `0006_phase9_order_syncs`; existing `0005` data survives the forward migration.

### Task 2: Make approval intent and sync retry atomic

**Files:**
- Create `src/opsflow/persistence/order_sync_repository.py`
- Modify `src/opsflow/application/order_sync.py`
- Modify `src/opsflow/application/review_commands.py`
- Create `tests/integration/test_phase9_order_sync_atomicity.py`
- Extend `tests/integration/test_phase6_commands.py` only for observable approval/retry behavior.

**Interfaces:**
- `insert_order_sync_intent(session: AsyncSession, order_id: UUID, created_at: datetime) -> None` flushes one `order_syncs` row without committing.
- Approval invokes that helper after the `ORDER_APPROVED` audit event inside its existing PostgreSQL transaction.
- The limit of three automatic retry/expired-lease events applies within each retry generation. For `FAILED_RETRYABLE` with `failure_origin=SYNCING`, human `retry_order` calls `Order.retry()`, increments the nonnegative, unbounded `retry_generation`, resets `attempt_count` to `0` and `next_attempt_at` to immediate eligibility, clears claim ownership, and preserves every receipt and `in_flight_step` in that same transaction.
- Retry origins `PROCESSING` and `EXTRACTED` retain existing behavior and do not require a sync row.
- Emit the existing bounded audit events for approval, sync start/resume, sync failure, and completion using the established `AuditEvent` record and repository; do not add provider detail to descriptions.

- [ ] **Step 1: Write failing PostgreSQL tests** named `test_approval_commits_exactly_one_sync_intent`, `test_sync_intent_failure_rolls_back_approval_and_audit`, `test_duplicate_sync_intent_is_rejected`, and `test_sync_retry_resets_generation_without_losing_receipts`. Assert intent+audit+order atomicity and sync-origin retry preservation/reset.
- [ ] **Step 2: Run only the new focused tests and confirm failures match the absent intent/retry behavior.**

Run: `uv run pytest tests/integration/test_phase9_order_sync_atomicity.py -q --no-cov`

- [ ] **Step 3: Add the intent repository helper and extend approval/retry within existing transaction scopes.** Do not add a second approval transaction or change review authorization/ETag behavior.
- [ ] **Step 4: Re-run the focused tests, then existing Phase 6 command and Phase 8 approval-atomicity tests.**

Run: `uv run pytest tests/integration/test_phase9_order_sync_atomicity.py tests/integration/test_phase6_commands.py tests/integration/test_phase8_notification_atomicity.py -q --no-cov`

Expected: all tests pass against PostgreSQL; simulated insert errors leave no approved order, approval event, or sync intent; sync retry retains earlier receipts.

### Task 3: Implement fenced claiming, bounded retries, receipts, and yield

**Files:**
- Modify `src/opsflow/persistence/order_sync_repository.py`
- Modify `src/opsflow/application/order_sync.py`
- Create `tests/integration/test_phase9_order_sync_claims.py`
- Create or extend `tests/unit/order_sync/test_contracts.py`

**Interfaces:**
- `claim_next_order_sync(session: AsyncSession) -> OrderSyncClaim | None` selects one eligible approved/syncing order using the database clock, `FOR UPDATE SKIP LOCKED`, and a random fencing token with a five-minute lease.
- A first claim transitions `APPROVED → SYNCING` and audits the start in that same transaction. Reclaiming an expired lease records one retryable lease outcome; exhaustion transitions `SYNCING → FAILED_RETRYABLE`, stores `WORKER_LEASE_EXHAUSTED`, clears ownership, and preserves receipts/uncertain step.
- `persist_order_sync_receipt(session: AsyncSession, order_id: UUID, claim_token: UUID, receipt: OrderSyncReceipt) -> OrderSync` and failure/yield operations require the latest unexpired claim. Company receipt IDs may be shared across sync rows; Odoo order IDs and HubSpot Deal IDs may not.
- `record_order_sync_failure(session: AsyncSession, order_id: UUID, claim_token: UUID, step: OrderSyncStep, code: OrderSyncFailureCode, retry_after: timedelta | None = None) -> OrderSync` records bounded outcomes and retry schedule.
- `begin_order_sync_step(session: AsyncSession, order_id: UUID, claim_token: UUID, step: OrderSyncStep) -> OrderSync` persists the step checkpoint before a future provider call, after validating the current unexpired claim and required preceding receipts. M9B implements the durable operation only; it does not call a provider.
- `yield_order_sync_claim(session: AsyncSession, order_id: UUID, claim_token: UUID) -> OrderSync` releases ownership for clean budget yield without incrementing `attempt_count` or changing receipts/step.
- `complete_order_sync(session: AsyncSession, order_id: UUID, claim_token: UUID) -> OrderSync` transitions `SYNCING → COMPLETED` only when all four receipts are present, writes the completion audit event, and clears the current claim atomically. It is a provider-free persistence/application operation.
- `execute_next_order_sync(session: AsyncSession, executor: OrderSyncStepExecutor, ...) -> OrderSyncExecutionResult` claims at most one eligible order, selects/resumes the first missing durable step, checkpoints before calling the executor outside a database transaction, persists each successful receipt before continuing, and completes only after all four receipts are durable. It stops at the injected total budget by releasing the claim without consuming an attempt; exceptions/outcomes are reduced to the approved bounded failure model. The executor is mandatory for this function; the HTTP route checks for its absence before calling it.
- Automatic retry/expired-lease events are limited to three per generation, with 30-second then 120-second base delays and no retry before provider `Retry-After`. The generation counter itself is nonnegative and unbounded. Permanent errors pause for operator correction or use the approved `FAILED_FINAL` path; do not add domain states.
- `yield_order_sync_claim(...)` releases ownership and makes the row immediately eligible without incrementing `attempt_count`, changing order state, or clearing any receipt/in-flight step.

- [ ] **Step 1: Write failing unit/PostgreSQL tests** named `test_non_approved_order_cannot_be_claimed`, `test_first_claim_transitions_approved_to_syncing_and_audits`, `test_concurrent_claims_have_one_owner`, `test_active_lease_is_not_stolen`, `test_stale_token_cannot_mutate_sync`, `test_expired_lease_rotates_token_and_counts_one_recovery`, `test_terminal_sync_is_not_claimed_again`, `test_third_retryable_outcome_moves_order_to_failed_retryable`, `test_permanent_reconciliation_failure_moves_order_to_failed_final`, `test_budget_yield_after_receipt_preserves_checkpoint_without_counting_attempt`, `test_retry_after_never_shortens_base_delay`, `test_step_checkpoint_requires_preceding_receipts`, `test_next_step_is_first_missing_receipt`, `test_completion_requires_all_four_receipts`, and `test_all_receipts_complete_sync_exactly_once`. Assert receipt persistence and first-missing-step resume behavior against PostgreSQL rows; parameterize the first-missing-step test across each of the four durable receipts.
- [ ] **Step 2: Run the focused tests and verify they fail for the expected missing claim/recovery behavior.**

Run: `uv run pytest tests/unit/order_sync tests/integration/test_phase9_order_sync_claims.py -q --no-cov`

- [ ] **Step 3: Implement the smallest repository/service operations required by those behaviors.** Keep external calls out of transactions; no provider adapter is present in M9B.
- [ ] **Step 4: Re-run focused unit and PostgreSQL tests, including independent-session concurrency and lease recovery.**

Expected: one live owner per sync row; active leases are not stolen; expired/stale tokens cannot mutate state or receipts; only failure/expiry events consume the three-outcome budget; clean yields preserve receipts and do not exhaust a generation; terminal/completed work is ineligible.

### Task 4: Add the one authenticated execute-next API boundary

**Files:**
- Modify `src/opsflow/api/orchestration.py`
- Modify `src/opsflow/api/orchestration_schemas.py`
- Modify `src/opsflow/main.py`
- Create `tests/integration/test_phase9_order_sync_api.py`

**Interfaces:**
- Add only `POST /v1/orchestration/order-sync/execute-next`, protected by existing `get_orchestration_actor` service authentication.
- Response schema is strict and bounded: a permitted result value, optional OpsFlow order ID, and authoritative order state. No provider IDs, raw errors, or secrets are returned. An unavailable executor uses the existing bounded error envelope, not a fabricated work result.
- Production/default M9B has no provider executor configured. The endpoint returns a bounded 503 before invoking the coordinator, claim query, or any state mutation; this keeps approved intents durable and avoids a stranded five-minute lease.
- When the executor is injected (only in deterministic tests during M9B), the endpoint invokes the real M9B `execute_next_order_sync` coordinator. Integration tests drive the database claim, step checkpoint, fake execution, receipt persistence, failure/yield, resume, and completion paths through this same route/service seam without network access.
- Use a single optional executor seam stored in `app.state`; `main.py` initializes it as unavailable. M9C/M9D later configure the real Odoo/HubSpot step behavior behind this existing seam and do not introduce claim, lease, checkpoint, or retry machinery. No request body is required and no missing-executor fallback may claim sync work.

- [ ] **Step 1: Write failing integration tests** named `test_execute_next_route_is_registered`, `test_execute_next_requires_service_authentication` (missing, wrong, and review-user bearer cases), `test_missing_executor_returns_503_without_claiming`, `test_execute_next_with_fake_executor_claims_and_records_receipt`, `test_execute_next_resumes_at_company_after_odoo_receipt_and_hubspot_failure`, `test_budget_yield_after_receipt_keeps_attempt_count`, `test_completed_order_is_not_executed_again`, and `test_parallel_execute_next_requests_have_one_owner`. Assert the bounded error envelope, authoritative state/results, committed receipts and step, and fake executor call sequence; all provider fakes are deterministic and no-network.
- [ ] **Step 2: Run the new API tests and verify the expected missing-route failures.**

Run: `uv run pytest tests/integration/test_phase9_order_sync_api.py -q --no-cov`

- [ ] **Step 3: Add the strict response model, authenticated route, and single runtime handler seam.** Wire the route to the real M9B coordinator when a fake or later real executor is configured; fail closed before claim when it is absent. Do not add a second claim endpoint, background worker, n8n workflow, provider configuration, or live provider call.
- [ ] **Step 4: Re-run the focused API suite and existing Phase 7 authentication/Phase 8 API tests.**

Run: `uv run pytest tests/integration/test_phase9_order_sync_api.py tests/integration/test_phase7_auth.py tests/integration/test_phase8_notification_api.py -q --no-cov`

Expected: the only new path is `POST /v1/orchestration/order-sync/execute-next`; authentication and no-executor 503 are verified before state mutation, while injected-fake requests exercise the genuine claim/checkpoint/receipt/recovery coordinator without network/provider writes.

### Task 5: Update canonical M9 status and run completion checks

**Files:**
- Modify `docs/roadmap/project-roadmap.md`
- Modify `docs/development/development-guide.md`
- Modify `docs/superpowers/specs/2026-09-29-phase-9-erp-crm-integrations-design.md` M9A status metadata and its status-only review note

- [ ] Update M9A to `COMPLETE`, M9B to `IN PROGRESS`, and M9C–M9F to `NOT STARTED` in canonical status text. Keep Phase 9 `IN PROGRESS`; do not mark M9B or Phase 9 complete.
- [ ] Reread the implementation diff for the M9A–M9F boundaries and verify no Odoo/HubSpot call, adapter, addon, second endpoint, worker, or n8n workflow was added.
- [ ] Run all project completion checks: `make check`, `make test-integration`, `uv run alembic upgrade head`, `uv run alembic current`, migration tests with `OPSFLOW_MIGRATION_TEST_DATABASE_URL` set to a separate PostgreSQL database, `git diff --check`, and the pinned Gitleaks command documented in `docs/development/development-guide.md` over changed tracked files.
- [ ] Verify both incremental migration from `0005_phase8_notification_deliveries` and clean `base → head`; preserve development database state throughout.
- [ ] Commit coherent M9B changes only after all required checks pass and push `phase/9-erp-crm-integrations`.

## Approval / execution method

The repository's `AGENTS.md` prohibits subagents, so the execution method is Native single-agent implementation using `superpowers:executing-plans`. M9B owns the actual durable claim/lease/retry/checkpoint/resume and request coordinator, proven through deterministic fake execution. Production/default configuration remains fail-closed: absent an executor, the route returns bounded 503 before claim or mutation. M9C/M9D add provider-specific step behavior behind the tested coordinator; they do not introduce its recovery foundation.
