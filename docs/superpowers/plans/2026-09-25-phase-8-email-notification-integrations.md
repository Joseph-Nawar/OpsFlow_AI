# Phase 8 — Email & Notification Integrations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add sandbox Gmail intake and durable Slack/Gmail notifications while preserving backend-owned order state and bounded delivery recovery.

**Architecture:** Python/FastAPI/PostgreSQL persist notification eligibility, rendered payloads, claims, outcomes, retry timing, and terminal state. n8n 2.40.5 transports Gmail and Slack data through authenticated OpsFlow APIs and never decides business validity or lifecycle transitions. A single `notification_deliveries` table is the only new durable delivery mechanism.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, Alembic, PostgreSQL 16, pytest, n8n Community 2.40.5, React/Vite review UI, Docker Compose, and existing GitHub Actions CI.

**Spec:** [Approved Phase 8 design](../specs/2026-09-25-phase-8-email-notification-integrations-design.md) (`docs/superpowers/specs/2026-09-25-phase-8-email-notification-integrations-design.md`).

## Global Constraints

- Keep the n8n image pinned to `n8nio/n8n:2.40.5`.
- Reuse `POST /v1/orchestration/intakes`; do not add another intake endpoint.
- Add only optional `source_system=GMAIL`; absent `source_system` preserves Phase 7 behavior.
- Bind Gmail identity with `Idempotency-Key: gmail:<raw Gmail message ID>` and persist `("source_system", "GMAIL")` in source metadata.
- Python/PostgreSQL own notification intent, claims, retries, attempt limits, lease recovery, stale-claim rejection, and terminal state.
- n8n owns Gmail/Slack transport and authenticated OpsFlow API calls only.
- Automated tests use local PostgreSQL, fake providers, fixtures, and static workflow contracts; they make no Gmail or Slack network calls.
- Maximum notification delivery claims are 3; each lease is 5 minutes.
- Backend retry delays are 30 seconds after attempt 1 and 120 seconds after attempt 2.
- Accept a Slack `Retry-After` hint only as an integer in `[0, 300]`; the backend schedules `max(base_delay, min(hint, 300))`.
- Do not claim exactly-once external delivery. A provider-accepted send followed by a lost acknowledgement may produce a duplicate notification after lease recovery.
- Notification delivery never changes `OrderState`, creates order audit events, or changes review ETag generation beyond the triggering business event already persisted.
- Create a Gmail approval acknowledgement only when the locked order's source document has persisted Gmail provenance and a raw Gmail message ID.
- Do not implement ERP/CRM work, `SYNCING` execution, or `COMPLETED` confirmation.
- Preserve `$0` mandatory development cost. Add no Kafka, Redis, Celery, generic queue, microservice, managed cloud service, or Kubernetes infrastructure.
- Disable n8n provider-node `Retry On Fail`. One OpsFlow claim can reach at most one native Gmail/Slack provider send in one workflow execution.
- Render Slack top-level `text` to at most 4,000 characters.
- Commit no credentials, OAuth/token values, live email/document content, or n8n execution history.
- Complete internal tasks within a milestone without requesting human review after each small TDD step. Commit and verify the milestone head, then request one consolidated independent review for M8B, M8C, M8D, and M8E. Collect that review's findings and remediate them together, except when a CRITICAL blocker makes continued work unsafe.
- Do not repeat a whole suite or audit when a targeted differential check proves the changed surface; run the milestone and final gates below once at their stated boundaries.

## Review Focus

1. **Provider accepted the send, then the OpsFlow acknowledgement was lost.** `tests/integration/test_phase8_notification_persistence.py::test_lost_ack_reclaim_can_duplicate_only_notification` proves a stale acknowledgement cannot mutate the reclaimed row and order state/audit history remain unchanged. M8E repeats the boundary in sandbox evidence.
2. **Two dispatchers claim concurrently.** `tests/integration/test_phase8_notification_persistence.py::test_concurrent_claimers_get_one_active_owner` uses two PostgreSQL sessions and proves `FOR UPDATE SKIP LOCKED` yields one active token.
3. **Generic Phase 7 `message_id` is mistaken for Gmail provenance.** `tests/integration/test_phase8_gmail_provenance.py::test_generic_message_id_never_creates_gmail_approval_intent` approves a source with `message_id` but no `source_system`; it may create Slack `ORDER_APPROVED`, never Gmail `ORDER_APPROVED`.
4. **Notification insert fails during a business transaction.** `tests/integration/test_phase8_notification_atomicity.py::test_intent_failure_rolls_back_transition_and_event_for_each_trigger` forces the repository flush to fail and proves the state update and triggering audit event roll back for every eligible event path.
5. **A provider node retries within one OpsFlow claim.** `tests/unit/workflows/test_phase8_notification_dispatch_contract.py::test_provider_nodes_send_once_per_claim_without_retry` checks both native provider nodes, `retryOnFail` false, one send node per channel path, and no provider loop, wait, or retry chain.

## Planned File Structure

### New production and runtime files

| Path | Responsibility |
| --- | --- |
| `alembic/versions/0005_phase8_notification_deliveries.py` | Create and reverse the notification delivery table, constraints, foreign keys, and claim index. Set `down_revision = "0004_phase6_review_revisions"`, the verified current head. |
| `src/opsflow/notifications/__init__.py` | Export only the stable notification contracts used across application and API boundaries. |
| `src/opsflow/notifications/contracts.py` | Frozen notification enums and dataclasses; no order-domain types added for delivery state. |
| `src/opsflow/notifications/payloads.py` | Deterministic bounded Slack/Gmail payload rendering and review URL construction. |
| `src/opsflow/notifications/service.py` | Transaction-owning intent, claim, and outcome services plus bounded service errors. |
| `src/opsflow/persistence/notification_repository.py` | Notification row insertion, row locks, claim selection, and updates; all functions leave commit ownership to the service transaction. |
| `src/opsflow/api/notification_schemas.py` | Strict Pydantic request/response schemas with `extra="forbid"`. |
| `src/opsflow/api/notifications.py` | Service-authenticated claim/outcome routes with non-echoing errors. |
| `workflows/n8n/opsflow-gmail-intake.json` | Sanitized Gmail-to-existing-intake workflow using the frozen 2.40.5 standard nodes. |
| `workflows/n8n/opsflow-notification-dispatch.json` | Scheduled one-claim dispatcher; M8D ships the Slack route and M8E adds the Gmail Reply route. |

### Modified production, configuration, tests, and documentation

| Path | Responsibility in this plan |
| --- | --- |
| `src/opsflow/persistence/models.py` | Add `NotificationDeliveryModel` to the existing SQLAlchemy base. |
| `src/opsflow/persistence/mappers.py` | Add explicit conversion between `NotificationDelivery` and its ORM row. |
| `src/opsflow/settings.py` | Add validated `review_base_url` / `OPSFLOW_REVIEW_BASE_URL` using current Pydantic settings conventions. |
| `.env.example` | Give the local UI URL example only; no credential values. |
| `docker-compose.yml` | Pass the review URL to the API container. |
| `src/opsflow/orchestration/contracts.py` | Add optional `source_system` to the intake command while keeping existing constructors backward compatible. |
| `src/opsflow/orchestration/transport.py` | Validate the optional Gmail source identity tuple before processing upload bytes. |
| `src/opsflow/api/orchestration.py` | Add optional multipart `source_system` and pass it to the existing handler. |
| `src/opsflow/application/orchestration.py` | Persist Gmail provenance metadata through the existing idempotent create/fingerprint path. |
| `src/opsflow/orchestration/composition.py` | Carry the validated review base URL to the existing pipeline runtime. |
| `src/opsflow/application/validation.py` | Insert the Slack intent beside its exact route audit event within the existing transaction. |
| `src/opsflow/application/review_revalidation.py` | Insert the Slack intent beside the exact post-correction route event. |
| `src/opsflow/orchestration/failures.py` | Insert the Slack failure intent beside the exact failure event. |
| `src/opsflow/application/review_commands.py` | Insert approval Slack intent and provenance-gated Gmail intent beside `ORDER_APPROVED`. |
| `src/opsflow/api/review.py` | Pass app-configured review URL into revalidation and approval services. |
| `src/opsflow/main.py` | Compose and register the notification routes with existing session and service-token seams. |
| `README.md`, `docs/roadmap/project-roadmap.md` | Keep current phase/milestone status aligned at each milestone commit. |
| `docs/architecture/system-overview.md`, `docs/development/development-guide.md` | At M8B start, replace only stale “next/not started” Phase 8 status prose with the in-progress boundary; do not duplicate workflow credential instructions. |
| `workflows/n8n/README.md` | Add the Gmail/Slack local credential, import/publish, manual acceptance, cleanup, and clean-clone instructions once the workflows exist. |
| `tests/unit/notifications/test_contracts.py` | Contract invariants and immutable records. |
| `tests/unit/notifications/test_payloads.py` | Exact safe rendered payloads, review URLs, and string/serialized-size bounds. |
| `tests/unit/notifications/test_service.py` | Deterministic outcome/backoff and stale-claim behavior at the application seam. |
| `tests/unit/persistence/test_notification_mappers.py` | ORM/dataclass round trips. |
| `tests/unit/api/test_notification_schemas.py` | Strict valid/invalid request bodies and bounded fields. |
| `tests/unit/test_settings.py` | Review URL validation and normalization. |
| `tests/integration/test_phase8_migrations.py` | M8B clean upgrade, 0004→0005 upgrade, downgrade/re-upgrade, schema and FK constraints. |
| `tests/integration/test_phase8_notification_persistence.py` | Real PostgreSQL constraints, claim concurrency, lease, outcomes, and retry timing. |
| `tests/integration/test_phase8_notification_atomicity.py` | Event-plus-intent commits, forced-insert rollback, and ETag isolation. |
| `tests/integration/test_phase8_notification_api.py` | Authenticated claim/outcome HTTP status and safe-response matrix. |
| `tests/integration/test_phase8_gmail_provenance.py` | Intake backward compatibility, Gmail identity binding, replay/conflict, and approval eligibility. |
| `tests/unit/workflows/test_phase8_gmail_intake_contract.py` | Gmail workflow JSON/node/connection/provenance/retry contract. |
| `tests/unit/workflows/test_phase8_notification_dispatch_contract.py` | Dispatcher topology, channel routing, credential references, and provider-send limits. |
| `tests/integration/test_phase2_migrations.py`, `tests/integration/test_phase6_persistence.py` | Update “current Alembic head” assertions from `0004_phase6_review_revisions` to `0005_phase8_notification_deliveries`; keep Phase 6 revision-specific checks pinned to 0004. |
| `tests/unit/application/test_validation.py`, `tests/integration/test_phase5_application.py` | Keep existing validation assertions valid with transactional Slack intents and assert only the existing route audit event is added. |
| `tests/unit/application/test_review_revalidation.py`, `tests/integration/test_phase6_revalidation.py` | Preserve review correction semantics and assert notification insertion does not add audit generations. |
| `tests/unit/application/test_review_commands.py`, `tests/integration/test_phase6_commands.py`, `tests/integration/test_phase7_pipeline.py` | Preserve approval state/ETag behavior while validating the new Slack and conditional Gmail intents. |
| `tests/integration/test_phase7_failure_matrix.py` | Preserve failure classification and prove its notification insert shares the event transaction. |
| `tests/unit/orchestration/test_contracts.py`, `tests/unit/orchestration/test_transport.py`, `tests/integration/test_phase7_orchestration_api.py` | Preserve the old multipart schema when source_system is absent and test the new optional field. |
| `tests/unit/workflows/test_n8n_contract.py` | Leave the existing Phase 7 graph assertions intact; add no Gmail behavior to that workflow. |
| `docs/audits/phase-8-audit.md` | Record the M8F whole-phase findings ledger, final zero-finding result, evidence, and limitations after remediation. |

No frontend source file is planned. The current review route is already `/review/:orderId` in `web/src/app/Router.tsx`.

## Implementation Batch and Review Policy

M8B, M8C, M8D, and M8E are four milestone-sized implementation batches. Complete each milestone's internal test-first tasks, run its single consolidated verification gate, commit and push that milestone head, and then request one independent review. Do not request a human review after an internal TDD task or individual file. The reviewer collects all findings for that milestone; implement them in one remediation batch and run differential verification plus affected regressions. Stop before the batch only for a CRITICAL blocker, destructive/security incident, or blocker that prevents meaningful work.

M8F is one whole-phase audit/remediation/closeout process, not a set of scenario-by-scenario mini-milestones. Commit themes are `feat: add durable notification delivery`, `feat: add Gmail intake workflow`, `feat: add Slack notification delivery`, `feat: complete Gmail notification integration`, then `docs: record Phase 8 independent audit` and `docs: close out Phase 8` when M8F reaches those artifacts.

## Milestone M8B — Durable Notification Delivery Core

### Task 1: Notification persistence contract and migration

**Milestone:** M8B

**Files:**
- Create: `alembic/versions/0005_phase8_notification_deliveries.py`
- Create: `src/opsflow/notifications/__init__.py`
- Create: `src/opsflow/notifications/contracts.py`
- Create: `src/opsflow/persistence/notification_repository.py`
- Modify: `src/opsflow/persistence/models.py`
- Modify: `src/opsflow/persistence/mappers.py`
- Test: `tests/unit/notifications/test_contracts.py`
- Test: `tests/unit/persistence/test_notification_mappers.py`
- Test: `tests/integration/test_phase8_migrations.py`
- Modify test: `tests/integration/test_phase2_migrations.py`
- Modify test: `tests/integration/test_phase6_persistence.py`

**Interfaces:**
- Consumes: `Base`, `OrderModel`, and `AuditEventModel` from `opsflow.persistence.models`; the Phase 7 `AuditEvent` ID and order ID; existing `AsyncSession` patterns.
- Produces: frozen `NotificationChannel`, `NotificationKind`, `NotificationStatus`, `NotificationOutcomeKind`, `NotificationFailureCode`, `NotificationDelivery`, `NotificationClaim`, `NotificationOutcome`, and `NotificationOutcomeResult`. The repository exports `insert_notification_delivery(session, delivery)`, `finalize_expired_last_attempts(session)`, `claim_one_eligible_notification(session)`, and `get_notification_delivery_for_update(session, notification_id)`; these functions flush but never commit.

- [ ] First M8B action: update the current-status passages in `README.md`, `docs/roadmap/project-roadmap.md`, `docs/architecture/system-overview.md`, and `docs/development/development-guide.md` to show Phase 8 `IN PROGRESS`, M8A `COMPLETE`, M8B `IN PROGRESS`, and M8C–M8F `NOT STARTED`. Keep these status edits inside the M8B batch; no review is requested for them separately.
- [ ] Write unit tests proving enum values, frozen dataclass assignment rejection, JSON-object payload acceptance, rejection of list/scalar payloads, and compact UTF-8 serialized JSON size exactly at and one byte over 16 KiB.
- [ ] Run `uv run pytest tests/unit/notifications/test_contracts.py -q` and `uv run pytest tests/unit/persistence/test_notification_mappers.py -q`; confirm the new contracts/mappers are absent before implementation.
- [ ] Add `NotificationDeliveryModel` with UUID primary key, `order_id` FK to `orders.id`, `trigger_audit_event_id` FK to `audit_events.id`, ordinary string `channel`/`kind`/`status`, JSONB `payload`, integer `attempt_count`, nullable UUID claim token, nullable timezone-aware claim expiry, non-null timezone-aware `next_attempt_at`, `String(256)` provider reference, `String(64)` failure code, and timezone-aware created/updated fields.
- [ ] Add migration revision `0005_phase8_notification_deliveries` with `down_revision = "0004_phase6_review_revisions"`; include `CHECK` constraints for `SLACK|GMAIL`, all four approved kinds, all four statuses, `attempt_count BETWEEN 0 AND 3`, `jsonb_typeof(payload) = 'object'`, provider/failure-code bounds, and the exact claimed-token/expiry pair invariant. Add `UNIQUE(trigger_audit_event_id, channel, kind)`, cascading order/event foreign keys, server timestamps/defaults, and `ix_notification_deliveries_claim_eligibility(status, next_attempt_at, claim_expires_at)`. Enforce the 16 KiB serialized payload limit in contracts/service code, not with PostgreSQL's JSONB storage byte size.
- [ ] Constrain non-null `last_failure_code` to `RATE_LIMITED`, `AUTHENTICATION_FAILED`, `PERMISSION_DENIED`, `TARGET_NOT_FOUND`, `PROVIDER_UNAVAILABLE`, `TIMEOUT`, `DELIVERY_REJECTED`, or `UNKNOWN_FAILURE`; reject values longer than 64 characters. Provider references are nullable and at most 256 characters.
- [ ] Map the row explicitly in `persistence/mappers.py`; copy the JSON object at persistence/return boundaries so stored payload content is not mutated after intent creation.
- [ ] Add migration/schema tests for valid rows; invalid status/channel/kind/failure code; scalar/list payload rejected by the DB; attempt counts -1 and 4 rejected; CLAIMED without either claim field rejected; non-CLAIMED with either field rejected; missing order/event FKs rejected; order/event deletion cascade behavior; duplicate event/channel/kind rejected; string bounds; and index/constraint names.
- [ ] Test a clean `base → head` upgrade and `0004 → 0005` upgrade. Because existing Phase 5/6 integration tests exercise downgrade, test `0005 → 0004 → 0005` and prove pre-existing Phase 6 rows survive. Update `test_phase2_migrations.py` and the head assertion in `test_phase6_persistence.py` to expect 0005 while keeping the Phase 6 revision identity at 0004.
- [ ] Run the targeted contract, mapper, and migration tests and directly affected Phase 6 migration regression; commit these files only as part of the final M8B milestone commit.

### Task 2: Backward-compatible Gmail provenance on existing intake

**Milestone:** M8B

**Files:**
- Modify: `src/opsflow/orchestration/contracts.py`
- Modify: `src/opsflow/orchestration/transport.py`
- Modify: `src/opsflow/api/orchestration.py`
- Modify: `src/opsflow/application/orchestration.py`
- Test: `tests/integration/test_phase8_gmail_provenance.py`
- Modify test: `tests/unit/orchestration/test_contracts.py`
- Modify test: `tests/unit/orchestration/test_transport.py`
- Modify test: `tests/integration/test_phase7_orchestration_api.py`

**Interfaces:**
- Consumes: `OrchestrationIntakeCommand`, `build_intake_command`, `CreateSourceDocumentInput.metadata`, the existing order fingerprint, and current multipart route.
- Produces: optional `OrchestrationIntakeCommand.source_system: str | None = None`; `build_intake_command(..., source_system: str | None = None)`; one unchanged `POST /v1/orchestration/intakes` route with optional `source_system` form field.

- [ ] Write transport/API tests proving the field is optional and absent callers still construct the same Phase 7 command and OpenAPI request fields remain optional.
- [ ] Run the targeted orchestration contract, transport, and API tests and confirm the new `GMAIL` cases fail before implementation.
- [ ] Add a narrow transport validator: absent source system leaves `message_id` and any valid legacy idempotency key untouched; present value must equal `GMAIL`, have a nonblank raw `message_id`, and have `Idempotency-Key == f"gmail:{message_id}"`; invalid/unsupported combinations return the existing bounded 422 intake response.
- [ ] In `execute_orchestration_intake`, set metadata to `(("source_system", "GMAIL"),)` only for the validated Gmail command, otherwise preserve `()`. Keep the raw `message_id`, filename, content hash, request fingerprint, and existing Phase 7 claim pipeline unchanged.
- [ ] Add real-PostgreSQL/HTTP tests for legacy caller unchanged; valid Gmail metadata; missing/blank message ID; mismatched Gmail key; unsupported source system; generic message ID with no Gmail metadata; same Gmail identity/filename/bytes replay; changed selected bytes under the same Gmail key returns 409 and creates no second order; and a Gmail ID whose prefixed key exceeds the existing 128-character header limit returns bounded 422 before order creation.
- [ ] Run these tests plus `tests/integration/test_phase7_orchestration_api.py`, `tests/integration/test_phase7_pipeline.py`, and directly affected unit transport/contract tests; commit with the M8B head only.

### Task 3: Deterministic payloads, URL settings, and atomic event insertion

**Milestone:** M8B

**Files:**
- Create: `src/opsflow/notifications/payloads.py`
- Create: `src/opsflow/notifications/service.py`
- Modify: `src/opsflow/settings.py`
- Modify: `.env.example`
- Modify: `docker-compose.yml`
- Modify: `src/opsflow/orchestration/composition.py`
- Modify: `src/opsflow/application/validation.py`
- Modify: `src/opsflow/application/review_revalidation.py`
- Modify: `src/opsflow/application/review_commands.py`
- Modify: `src/opsflow/orchestration/failures.py`
- Modify: `src/opsflow/application/orchestration.py`
- Modify: `src/opsflow/api/review.py`
- Test: `tests/unit/notifications/test_payloads.py`
- Test: `tests/unit/test_settings.py`
- Test: `tests/integration/test_phase8_notification_atomicity.py`
- Modify test: `tests/unit/application/test_validation.py`
- Modify test: `tests/integration/test_phase5_application.py`
- Modify test: `tests/unit/application/test_review_revalidation.py`
- Modify test: `tests/integration/test_phase6_revalidation.py`
- Modify test: `tests/unit/application/test_review_commands.py`
- Modify test: `tests/integration/test_phase6_commands.py`
- Modify test: `tests/integration/test_phase7_failure_matrix.py`
- Modify test: `tests/integration/test_phase7_pipeline.py`

**Interfaces:**
- Consumes: immutable `NotificationDelivery`/`NotificationChannel`/`NotificationKind`, existing order/source metadata, route audit objects, validation issues, and current settings/runtime injection.
- Produces: `build_review_url(base_url: AnyHttpUrl | str, order_id: UUID) -> str`; `render_slack_payload(kind, order, issues, review_base_url) -> dict[str, object]` returning exactly `text`, `order_id`, `state`, `summary`, and `review_url`; `render_gmail_approval_payload(order, raw_message_id) -> dict[str, object]` returning only `message_id` and deterministic `body`; `create_notification_intent(session, *, order, event, channel, kind, review_base_url, issues=()) -> None`. Slack includes only the server-generated order UUID as its reference; summaries use fixed text or issue counts, not extraction text. The Gmail body is exactly `Your purchase order has been approved for processing.` The insert helper uses `event.id`, appends a PENDING row, enforces the serialized 16 KiB cap, and never commits.

- [ ] First write payload, Settings, and PostgreSQL atomicity tests. Payload cases assert exact REVIEW_REQUIRED, APPROVAL_READY, PROCESSING_FAILED, Slack ORDER_APPROVED, and Gmail ORDER_APPROVED values; deterministic `http://localhost:5173/review/<uuid>` URL; Unicode/long-string bounds; no raw extraction/email/provider data; and truthful reply body exactly “Your purchase order has been approved for processing.” Atomicity cases inject intent persistence failures at all seven trigger variants and assert the business transition and audit event roll back.
- [ ] Write Settings tests for absolute HTTP/HTTPS only; reject relative URLs, other schemes, username/password, query, and fragment; normalize a configured base by stripping its trailing slash before URL construction and reject base URLs longer than 2,048 characters; verify the default is the local review origin and the resulting URL appends exactly one `/review/<canonical-uuid>` path separator.
- [ ] Run the targeted Settings/payload tests and atomicity tests; confirm invalid URLs, overlong Slack text, unsafe payload cases, and missing atomic intent behavior fail before their implementations.
- [ ] Add `review_base_url` to `Settings`, expose `OPSFLOW_REVIEW_BASE_URL=http://localhost:5173` in `.env.example`, pass it through the API service in Compose, and copy its normalized value into the existing `OrchestrationRuntime`. Pass that value from `api/review.py` to approval/revalidation services; do not add a new dependency-injection framework.
- [ ] Implement `render_slack_payload` as fixed templates keyed by `NotificationKind`; include only server-generated order UUID, authoritative state, safe summary, and review URL. Use these summaries: REVIEW_REQUIRED = `"{n} validation issue(s) require review."`; APPROVAL_READY = `"Order is ready for approval."`; PROCESSING_FAILED = `"Order processing failed; operator review may be required."`; ORDER_APPROVED = `"Order approved for processing."`. Build `text` as `"{summary} Order {order_id}; state {state}. {review_url}"`. If rendered top-level `text` exceeds 4,000 Unicode code points, retain its first 3,999 code points and append one ellipsis so the final value is exactly 4,000 characters. Render Gmail body exactly as `Your purchase order has been approved for processing.` and retain the raw persisted Gmail message ID separately; never claim external synchronization or completion.
- [ ] Within `validation.validate_order()`'s existing `session.begin()` transaction, retain the actual `AuditEvent` objects, insert each existing event, then create exactly one Slack intent from the same `ORDER_NEEDS_REVIEW` or `ORDER_READY_FOR_APPROVAL` event ID.
- [ ] Within `review_revalidation.save_and_revalidate()`'s final locked transaction, reuse the event returned by `_audit_events()` and create exactly one Slack intent beside `ORDER_REMAINS_NEEDS_REVIEW` or `ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION`.
- [ ] Within `persist_orchestration_failure()`'s current transaction, assign the `ORDER_PROCESSING_FAILED` or `ORDER_VALIDATION_FAILED` event object once, insert it, and use its ID for the Slack `PROCESSING_FAILED` intent.
- [ ] Within `approve_order()`'s current lock and transaction, reuse its actual `ORDER_APPROVED` event for Slack. Add a Gmail intent only if the locked order's source document metadata contains `("source_system", "GMAIL")` and its `message_id` is nonblank. A generic message ID alone creates no Gmail intent.
- [ ] Add PostgreSQL atomicity tests for all seven triggering event variants: assert a business transition/event and its required intent commit together; inject a repository insert/flush failure on each path and assert the transition and audit event roll back. Verify approval creates one Slack row and only eligible Gmail rows under the same audit event ID.
- [ ] Compare review ETags after the triggering event/intent transaction with ETags after claim/outcome changes; prove delivery-table writes add no audit event and do not alter the order review generation.
- [ ] Adapt focused existing application unit tests to fake `create_notification_intent` at their unrelated unit seam; retain assertions on transition/event behavior. Integration tests use PostgreSQL and assert the actual new intent.
- [ ] Run the targeted payload/settings tests, atomicity tests, and the directly affected Phase 5/6/7 tests listed above. Commit with the M8B head only.

### Task 4: Claim/outcome service, authenticated API, and M8B status closeout

**Milestone:** M8B

**Files:**
- Create: `src/opsflow/api/notification_schemas.py`
- Create: `src/opsflow/api/notifications.py`
- Modify: `src/opsflow/notifications/service.py`
- Modify: `src/opsflow/persistence/notification_repository.py`
- Modify: `src/opsflow/main.py`
- Modify status: `README.md`, `docs/roadmap/project-roadmap.md`, `docs/architecture/system-overview.md`, `docs/development/development-guide.md`
- Test: `tests/unit/notifications/test_service.py`
- Test: `tests/unit/api/test_notification_schemas.py`
- Test: `tests/integration/test_phase8_notification_persistence.py`
- Test: `tests/integration/test_phase8_notification_api.py`
- Modify test: `tests/integration/test_phase8_notification_atomicity.py`

**Interfaces:**
- Consumes: repository inserts and frozen contracts from Tasks 1–3; `get_orchestration_actor`, `SessionDependency`, and existing `create_app` composition.
- Produces: `claim_next_notification(session) -> NotificationClaim | None`; `record_notification_outcome(session, notification_id, outcome) -> NotificationOutcomeResult`; POST `/v1/integrations/notifications/claim`; POST `/v1/integrations/notifications/{notification_id}/outcome`.

- [ ] Write schema/service tests for all allowed outcome shapes and failure codes, strict integer Retry-After, unknown extra fields, arbitrary provider body rejection, and one JSON 200 outcome response.
- [ ] Run the targeted unit tests and notification API tests to verify claim/outcome routes and service operations are not yet registered.
- [ ] Implement claim in one short `session.begin()` transaction: first mark expired `CLAIMED` rows at attempt 3 as `FAILED_FINAL`; select one eligible `PENDING` row with due `next_attempt_at` or expired `CLAIMED` row with attempts remaining ordered by `next_attempt_at`, `created_at`, `id` using `with_for_update(skip_locked=True)`; increment once; set `CLAIMED`, new `uuid4()` token, database time + exactly five minutes, and `updated_at=func.now()`; flush, exit the transaction so it commits, and return one immutable claim. Return `None` when no row is eligible. Use database time for ownership/expiry and explicit past/future timestamps in tests; never sleep five minutes.
- [ ] Implement `record_notification_outcome` under a locked row transaction. Require `CLAIMED`, exact current token, and unexpired lease. DELIVERED clears claim fields and stores only a bounded provider reference. FAILED with attempts 1/2 clears claim fields, records only the allowlisted failure code, and sets `next_attempt_at` from database time plus 30/120 seconds; attempt 3 becomes `FAILED_FINAL`. Update `updated_at=func.now()` on each status/lease/failure transition, including expired-attempt-3 finalization. A Slack hint uses `max(base_delay, min(hint, 300))`; missing/invalid hints use the base delay. Wrong, expired, reclaimed, or already-terminal generations raise one stale-claim error without mutation.
- [ ] Add concurrency integration using two independent PostgreSQL sessions released simultaneously; exactly one receives the row and a unique active token. Add deterministic tests for 204/no work, claim attempt increments, lease recovery/token rotation, expired attempt 3 finalization, success, attempt 1/2 retries, attempt 3 failure, attempt 3 expiry, stale token after reclaim, wrong token, already-delivered outcome, and retry time/hint boundaries.
- [ ] Define strict Pydantic schemas: `NotificationClaimResponse` has notification ID, channel, kind, payload object, attempt number, claim token, and expiry; `NotificationOutcomeRequest` has claim token, `DELIVERED|FAILED`, optional bounded provider reference, required allowlisted failure code for FAILED, and optional strict integer retry hint 0–300. DELIVERED forbids failure-only fields; FAILED forbids a provider reference. `NotificationOutcomeResponse` returns only notification ID, status, attempt count, next-attempt timestamp, provider reference, and failure code.
- [ ] Register both routes under an API router. Reuse `get_orchestration_actor` and request `SessionDependency`; claim returns 200 or bodyless 204; outcome returns 200 JSON. Map bad bearer to existing 401; unknown ID to 404 `NOTIFICATION_NOT_FOUND`; stale/wrong/expired token to 409 `STALE_NOTIFICATION_CLAIM`; malformed bodies to a fixed non-echoing 422 using a route wrapper modeled on the existing `_OrchestrationRoute`; SQLAlchemy failure to fixed 503. Do not include provider text or payload values in error bodies.
- [ ] Include the router in `main.create_app`; do not add a review-user credential or database/AI provider to n8n or app composition.
- [ ] Test OpenAPI paths and schemas; missing/incorrect service bearer is 401, configured `orchestration:n8n` bearer works, review-user token fails, claim 200/204 mapping is correct, outcome 200 and 404/409/422/503 shapes are bounded, and provider diagnostics/unknown fields never appear in response text.
- [ ] At M8B closeout, change the four status documents listed in Task 1 to M8A `COMPLETE`, M8B `COMPLETE`, Phase 8 `IN PROGRESS`, M8C–M8F `NOT STARTED`. This is part of the M8B milestone commit, not a separate review cycle.
- [ ] Run the single consolidated M8B gate: targeted notification unit/PostgreSQL/API tests; Gmail provenance tests; affected Phase 6/7 command, pipeline, failure, auth, and transport regressions; `uv run alembic upgrade head` and `uv run alembic current`; `uv run ruff check .`; `uv run ruff format --check .`; `uv run mypy src/opsflow`; `uv run pytest`; `uv build`; `npm --prefix web ci`; `npm --prefix web test -- --run`; `npm --prefix web run lint`; `npm --prefix web run build`; `docker compose config --quiet`; prospective Gitleaks directory scan; `git diff --check`; then commit and push the M8B head and confirm exact-head GitHub CI is green.
- [ ] Produce one M8B closeout report with migration head, API/auth matrix, event-intent atomicity evidence, claim/backoff/lease evidence, ETag regression evidence, secret/cost note, commit SHA, and clean branch state. Return for one consolidated independent M8B review; gather all findings before remediation.

## Milestone M8C — Gmail Intake Workflow

### Task 5: Add and verify the deterministic Gmail intake workflow

**Milestone:** M8C

**Files:**
- Create: `workflows/n8n/opsflow-gmail-intake.json`
- Create: `tests/unit/workflows/test_phase8_gmail_intake_contract.py`
- Modify: `workflows/n8n/README.md`
- Modify: `README.md`, `docs/roadmap/project-roadmap.md` for M8C status only.
- Regression reference, unchanged: `workflows/n8n/opsflow-sandbox-intake.json`, `tests/unit/workflows/test_n8n_contract.py`.

**Interfaces:**
- Consumes: M8B's optional Gmail source form field and `/v1/orchestration/intakes`; Phase 7's authenticated `OpsFlow Orchestration` credential and exact bounded retry graph; verified n8n Gmail Trigger 1.4, HTTP Request 4.5, Switch 3.4, If 2.3, Edit Fields 3.5, and Move Binary Data 1.1.
- Produces: one inactive/sanitized Gmail intake workflow with no Code/AI/DB node; one contract test enforcing node versions, source selection, multipart mapping, retry identity, credentials-by-name, and state routing.

- [ ] Write the contract test first; assert frozen node IDs/types/versions, connections, Simplify off, attachment download on with `attachment_` prefix, dedicated label filter, bearer credential reference, `source_system=GMAIL`, `message_id`, exact key expression, canonical document types/MIME values, and the no-Code/no-AI/no-DB boundary.
- [ ] Run `uv run pytest tests/unit/workflows/test_phase8_gmail_intake_contract.py -q` and confirm it fails because the Phase 8 workflow does not exist.
- [ ] Inspect the local 2.40.5 node package for the built-in HTML node's exact installed version and pin that version in the workflow and contract test; do not infer the version from current online documentation.
- [ ] Build the standard-node graph: Gmail Trigger polls only `OpsFlow/Intake`; Edit Fields/expression reads only binary keys starting `attachment_`; case-insensitively exclude binary `mimeType` beginning `image/`; classify case-insensitive filename suffixes `.pdf` → `PDF`/`application/pdf`, `.xlsx` → `XLSX`/`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`, and `.csv` → `CSV`/`text/csv`; fail visibly before HTTP when supported candidate count exceeds one; dynamically pass the one selected binary under multipart field `document`; otherwise prefer parser text, convert HTML to visible text with the verified HTML node only when text is absent, normalize CRLF/CR to LF, NFC-normalize, trim outer whitespace, preserve remaining line order and quoted/signature text, and convert body text to `email-body.txt` / `text/plain` / `EMAIL_BODY` using Move Binary Data 1.1.
- [ ] Keep unsupported attachments out of the count. With no supported binary, send non-empty normalized body; with empty body, route to visible `NO_SUPPORTED_SOURCE`; multiple supported attachments route to `AMBIGUOUS_SUPPORTED_ATTACHMENTS` without an OpsFlow request. Never select by attachment order.
- [ ] Configure the existing intake URL and form parts without storing mailbox credentials in JSON. Set `message_id` from the Gmail message's raw `$json.id`, send optional `source_system=GMAIL`, and exact `gmail:<message_id>` Idempotency-Key. Route only the response state's `body.state`/response field to the existing named operator outcomes; unexpected state remains visible and safe.
- [ ] Retain Phase 7's manual transport retry policy only around OpsFlow HTTP: one initial request plus at most two attempts for connection/node transport errors or exact HTTP 503, with one-second waits; preserve the same message ID, idempotency key, document bytes/type/name across attempts. Do not retry a 2xx lifecycle response, 401/409/422/500, or any provider action.
- [ ] If the standard 2.40.5 expression graph cannot enumerate `attachment_*` keys and dynamically transfer the selected binary safely, stop M8C and capture the exact node expression, input item, and observed failure. Request review of that specific limitation. Only after explicit approval may the workflow use at most one deterministic transport-only Code node; do not add it preemptively or permit business-state, AI, database, or credential access.
- [ ] Contract-test exactly one supported file, every canonical MIME/type mapping, body-only fallback metadata, image exclusion, ambiguity/no-source branch ending before the API, identity preservation across all three HTTP attempts, response-state routing, no provider credential, no live data, and no execution history. Validate JSON with `python -m json.tool workflows/n8n/opsflow-gmail-intake.json`.
- [ ] Import the inactive workflow into the local 2.40.5 editor, relink only the named local credentials, configure a dedicated test mailbox with custom scopes `https://www.googleapis.com/auth/gmail.readonly` and `https://www.googleapis.com/auth/gmail.send`, verify recognized node versions/connections, publish and test the production trigger URL, then verify the exported file remains sanitized. Testing-mode authorizations expire after seven days, so record the reauthorization step; never use a personal mailbox.
- [ ] Run one dedicated Gmail sandbox matrix: labeled vs unlabelled; PDF, XLSX, CSV; text-only; unsupported attachment plus body; multiple supported files; signature image plus one supported file; image/unsupported-only with empty text; same message replay; changed selected bytes conflict; exact source_system/message_id/key; and byte-for-byte multipart attachment mapping. Record only synthetic pass/fail evidence; delete test execution data and retain no live body, attachment, headers, or mailbox export.
- [ ] Update `workflows/n8n/README.md` with scope creation, dedicated sandbox mailbox, custom Gmail scopes, label setup, import/publish, outcome mapping, and execution-data cleanup. Update M8C status in README/roadmap to complete, with M8D–M8F not started.
- [ ] Run the consolidated M8C gate: workflow contract, JSON validation, targeted Gmail provenance tests, Phase 7 orchestration/workflow regression, n8n import/publish, manual mailbox matrix, Gitleaks, clean diff, exact-head push CI. Write one M8C closeout report and request one independent M8C review; collect all findings before one remediation batch.

## Milestone M8D — Slack Notification Delivery

### Task 6: Add the one-claim Slack dispatcher path

**Milestone:** M8D

**Files:**
- Create: `workflows/n8n/opsflow-notification-dispatch.json`
- Create: `tests/unit/workflows/test_phase8_notification_dispatch_contract.py`
- Modify: `workflows/n8n/README.md`
- Modify: `README.md`, `docs/roadmap/project-roadmap.md` for M8D status only.

**Interfaces:**
- Consumes: M8B claim/outcome APIs and Pydantic shapes; Slack payload top-level `text`; n8n Schedule Trigger 1.4, HTTP Request 4.5, Switch 3.4, and native Slack 2.7 node.
- Produces: a one-minute, one-claim-per-execution dispatcher with a tested Slack route and visible 204/unknown/failure branches.

- [ ] Write graph-contract assertions before workflow JSON: one Schedule Trigger, one authenticated claim request, 204 no-work end, channel Switch, exactly one Slack Message/Send node on the Slack route, bounded outcome mapping, and no DB, AI, wait, loopback, review command, or order-state mutation node.
- [ ] Assert the Slack node's n8n `retryOnFail` is explicitly false/absent-as-default according to the frozen 2.40.5 export representation and that `maxTries`/`waitBetweenTries` cannot enable a provider retry. Keep each HTTP claim request to one request per workflow execution.
- [ ] Run `uv run pytest tests/unit/workflows/test_phase8_notification_dispatch_contract.py -q` and verify RED until the dispatch workflow is created.
- [ ] Add Schedule Trigger 1.4 → service-authenticated claim → explicit 204 stop → channel Switch → native Slack 2.7 Message/Send → allowlisted outcome normalization → service-authenticated outcome 200. Keep Gmail branch absent until M8E.
- [ ] Use one configured channel ID/name outside tracked workflow source and a credential reference by local name only. Require bot invitation and only `chat:write`; do not add `chat:write.public`, interactive commands, buttons, or approvals.
- [ ] Pass the pre-rendered top-level `text` unchanged, enforce `<= 4,000` characters in both backend and contract test, and persist only Slack's confirmed message timestamp/reference. Map provider status to the allowlisted failure codes; never send raw provider response/error text. Forward only a parsed integer Retry-After clamped to 0–300; omit it if the 2.40.5 Slack error output does not expose the header.
- [ ] Assert exactly one Slack provider send per claim path, no Wait/retry path to Slack, no `Retry On Fail`, and only one outcome call carrying token and bounded result.
- [ ] Validate JSON and import/publish the workflow in local n8n 2.40.5. Manual Slack sandbox: invited bot in configured sandbox channel; one REVIEW_REQUIRED and one APPROVAL_READY or ORDER_APPROVED message; top-level text <=4,000; review link opens existing UI and still requires operator auth; provider reference equals only confirmed timestamp; DB contains no raw provider response. Do not manufacture a real 429; test bounded hint via local API fixtures, and use fixed backend retry if the header is not exposed.
- [ ] Verify simulated send success then lost outcome acknowledgement: do not retry Slack within that n8n execution; after lease recovery a duplicate Slack message is documented as possible while order state/audit remain unchanged.
- [ ] Update workflow guide and M8D README/roadmap status. Run workflow contracts, M8B API/retry targeted regression, full CI-compatible gates, JSON/Compose checks, Gitleaks, diff check, and exact-head CI. Write one M8D report and request one independent M8D review; collect findings before one remediation batch.

## Milestone M8E — Gmail Reply & Cross-Boundary Hardening

### Task 7: Add Gmail approval reply and complete the sandbox handoff

**Milestone:** M8E

**Files:**
- Modify: `workflows/n8n/opsflow-notification-dispatch.json`
- Modify: `tests/unit/workflows/test_phase8_notification_dispatch_contract.py`
- Modify: `tests/integration/test_phase8_notification_atomicity.py`
- Modify: `tests/integration/test_phase8_notification_persistence.py`
- Modify: `tests/integration/test_phase8_gmail_provenance.py`
- Modify: `workflows/n8n/README.md`
- Modify: `README.md`, `docs/roadmap/project-roadmap.md` for M8E status only.

**Interfaces:**
- Consumes: M8B Gmail `ORDER_APPROVED` claim payload, M8D dispatcher channel switch, original persisted Gmail message ID, native Gmail Message 2.2 Reply operation.
- Produces: one native Gmail Reply route with sender-only/plain-text/no-attachment/no-attribution settings, cross-boundary acceptance evidence, and clean-clone handoff.

- [ ] Extend the existing dispatcher contract test with Gmail branch expectations before changing workflow JSON; prove the branch cannot execute for any non-GMAIL source event.
- [ ] Assert Gmail node `typeVersion=2.2`, Message → Reply, original persisted `message_id`, Reply to Sender Only true, text body, no attachment, attribution disabled, and `retryOnFail` false with no node retry fields/loop. Assert exactly one Gmail provider reply per OpsFlow claim.
- [ ] Add the channel Switch Gmail route to native Gmail Message/Reply → bounded provider-reference normalization → the same authenticated outcome API. Store only the provider-confirmed reply message ID/reference. Provider errors map to the same allowlisted failure enum, never raw provider diagnostics.
- [ ] Prove generic non-Gmail approval creates Slack ORDER_APPROVED only; Gmail-provenance approval creates the separate Gmail row under the same actual ORDER_APPROVED audit event. Prove a Gmail reply failure leaves the order APPROVED and does not append an audit event.
- [ ] Complete the Phase 8 adversarial matrix by subsystem: duplicate intake/replay and changed-byte conflict; source ambiguity/body/inline-image rules; atomic event+intent rollback; one-owner concurrent claim; lease expiry/token rotation; stale/duplicate outcome; attempt 3 expiry/failure; HTTP auth and bounded errors; provider invalid/revoked credentials and safe normalization; ack loss and notification-only duplication; Slack/Gmail single send per claim; review ETag unchanged after delivery; Slack URL still requiring ordinary OpsFlow operator auth; workflow export hygiene; and absent Phase 9 mutation/`SYNCING`/`COMPLETED` behavior.
- [ ] In the synthetic end-to-end clean-clone run, use a fresh checkout; prepare ignored `.env`; start PostgreSQL/API/n8n and Vite; relink dedicated Gmail, Slack, and OpsFlow credentials; create the sandbox `OpsFlow/Intake` label/filter; import and publish both sanitized workflows; send a synthetic PO; verify intake and Slack message; review/approve in the UI; verify sender-only reply in the original Gmail thread with “approved for processing” wording and its outcome acknowledgement; inspect notification records; demonstrate duplicate/retry behavior; and confirm no secrets or execution content are tracked. Do not use real customer data.
- [ ] Update only `workflows/n8n/README.md` for account setup, actual scopes, import/relink/publish, demo flow, evidence capture, and execution cleanup; add no duplicate top-level credential guide. Set M8E complete and M8F in progress in README/roadmap when starting M8F.
- [ ] Run one consolidated M8E/final Phase 8 verification: all Phase 8 targeted tests; affected Phase 6/7 regressions; workflow contracts; full backend suite; frontend tests/lint/build; Ruff lint/format; mypy; Python package build; `docker compose config --quiet`; JSON validation for all `workflows/n8n/*.json`; Gitleaks history/directory scan; `git diff --check`; exact-head push CI; plus recorded manual sandbox/clean-clone evidence. Do not re-run the M8B database audit unless M8E changed that code.
- [ ] Produce one M8E report with adversarial matrix and clean-clone evidence, then request one independent M8E review. Collect all review findings before the one M8F remediation batch; stop only for the critical conditions in the review policy.

## Milestone M8F — Independent Audit & Closeout

### Task 8: Audit all of Phase 8, remediate once, then close out

**Milestone:** M8F

**Files:**
- Create after the final audit ledger is clear: `docs/audits/phase-8-audit.md`
- Modify for final status: `README.md`, `docs/roadmap/project-roadmap.md`, `docs/architecture/system-overview.md`, `docs/development/development-guide.md`
- Conditional remediation: only exact production/test/workflow paths named by the consolidated findings ledger; do not add unrelated functionality.

**Interfaces:**
- Consumes: M8A approved design, M8A plan, M8B–M8E commits/reports, CI results, sandbox records, and current working tree.
- Produces: one whole-phase findings ledger, at most one consolidated remediation batch unless a CRITICAL blocker requires immediate isolation, final audit artifact, status transition, PR/merge/post-merge evidence.

- [ ] Start one fresh whole-Phase-8 audit covering authority boundaries; source selection/provenance/idempotency; OAuth/Slack security; persistence/constraints; atomic event-intent insertion; payload privacy and bounds; review ETag isolation; claim concurrency/lease; retry exhaustion/stale token; API auth/errors; provider send/reply behavior; native retry disabling; workflow graphs/exports; secret hygiene; failure isolation; sandbox and clean clone; $0 cost posture; Phase 9 boundary; documentation truth; and CI/test quality.
- [ ] Inspect every audit domain and record every finding in one consolidated ledger with severity, exact path/line or behavior, reproduction/evidence, and acceptance criterion. Do not stop on LOW or MEDIUM findings. Stop early only for a CRITICAL issue that makes further inspection unsafe, a destructive/security incident, or a blocker that prevents meaningful remaining audit.
- [ ] If the ledger has findings, implement one consolidated fix batch after discovery is complete. Run differential tests for changed behavior, directly affected Phase 6/7 regressions, the full CI-equivalent checks, secret scans, and `git diff --check`. Re-run discovery only if a fix materially changes architecture or invalidates prior audit evidence.
- [ ] If the final ledger is zero, create `docs/audits/phase-8-audit.md` with domains checked, initial findings, consolidated remediation (or none), final severity counts all zero, CI/SaaS sandbox/clean-clone evidence, limitations including at-least-once notification delivery, cost/security posture, and exact final commit/branch state.
- [ ] Update README and roadmap statuses to Phase 8 `COMPLETE`, M8A–M8F `COMPLETE`, Phase 9 `NOT STARTED`; update architecture/development status prose to identify Phase 8 as completed and Phase 9 as the next boundary. Do not describe ERP/CRM synchronization as implemented.
- [ ] Push the reviewed feature branch, create the Phase 8 PR only after all M8F evidence is complete, wait for PR CI, merge with the repository's merge-commit convention, run post-merge `main` CI, then clean up the feature branch. This future M8F PR does not authorize a PR in the current M8A plan-authoring task.
- [ ] Return one structured Phase 8 closeout report with status, scope/files, milestone evidence, acceptance PASS/FAIL, tests/CI/manual evidence, security/cost notes, deviations/limitations, branch/HEAD/commit list, and clean working-tree state.

## Milestone Verification Gates

| Milestone | One consolidated gate and one review point |
| --- | --- |
| M8B | Migration and repository constraints; notification contracts/payloads; atomicity and rollback; Gmail provenance; concurrent claim/lease/outcome; authenticated API/error matrix; Phase 6/7 regressions; backend/frontend CI checks; build, Compose, secrets, diff; exact pushed HEAD CI. Commit/report, then one review. |
| M8C | Gmail graph contract and JSON; source-provenance/Phase 7 regression; frozen n8n import/publish; complete dedicated-mailbox acceptance matrix; export cleanup; secrets/diff/CI. Commit/report, then one review. |
| M8D | Slack graph single-send contract; bounded result mapping/API retries; one sandbox review-required and ready/approved notification; review-link auth; provider reference/privacy; full CI plus differential verification, secrets/diff. Commit/report, then one review. |
| M8E | Gmail reply single-send contract; entire Phase 8 adversarial matrix; local clean-clone demo; Phase 6/7 regressions; complete CI and manual evidence; secrets/diff and exact pushed HEAD CI. Commit/report, then one review. |
| M8F | One complete independent audit, one consolidated remediation batch if needed, differential verification, final audit artifact, status closeout, PR CI/merge/post-merge CI, and clean branch state. |

## Plan Self-Review

- **Spec coverage:** Tasks 1–4 implement the M8B schema, contracts, settings, payloads, atomic event policy, Gmail provenance, claim/outcome APIs, retries, authentication, and ETag boundary. Task 5 implements Gmail source selection, identity, existing API reuse, routing, and sandbox tests. Task 6 implements Slack claim/dispatch/outcome. Task 7 implements Gmail reply, the complete adversarial matrix, and clean clone. Task 8 implements the full audit/remediation/status/PR closeout. The approved Phase 8 design's non-goals remain explicit in constraints and tests.
- **Review Focus:** Item 1 is tested in Tasks 4 and 7; item 2 in Task 4; item 3 in Tasks 2 and 3; item 4 in Task 3; item 5 in Tasks 6 and 7.
- **Interfaces:** Contract names are introduced in Task 1 and reused unchanged. `review_base_url` flows from `Settings` through `OrchestrationRuntime` and review API calls into payload rendering. Claim/outcome names and HTTP shapes are fixed in Task 4 before M8D/M8E workflows consume them.
- **Migration:** Current Alembic head was verified as `0004_phase6_review_revisions`; the only new revision is `0005_phase8_notification_deliveries` with 0004 as its parent.
- **Pace:** There are eight implementation tasks grouped into five milestone batches; no task is an independent human-review gate. M8B–M8E each have one milestone head review, and M8F is one whole-phase audit/remediation/closeout process.
- **Scope:** The plan adds only Gmail/Slack integration and notification delivery. No ERP, CRM, Phase 9 synchronization, generalized queue, cloud service, or customer-completion behavior is introduced.
