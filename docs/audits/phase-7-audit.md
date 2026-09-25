# Phase 7 Independent Audit

## Audit identity

- Repository: Joseph-Nawar/OpsFlow_AI
- Phase: Phase 7 — n8n Workflow Orchestration
- Audit date: 2026-09-25
- Branch: phase/7-n8n-workflow-orchestration
- Main / Phase 6 baseline: `809d201555af1afe5f79c202dfbc2bb259425e6b`
- Whole-phase audited candidate: `6a175ab5cd7cea7f185048082490a6eb1501737f`
- Final remediated candidate: `70abff21c32aadf7f6a99fc025d7b70ac6678689`
- Merge-base: `809d201555af1afe5f79c202dfbc2bb259425e6b`
- Relationship before this audit-artifact commit: 29 ahead / 0 behind
- Final candidate exact-head CI: [run 36138518909](https://github.com/Joseph-Nawar/OpsFlow_AI/actions/runs/36138518909)

M7F first performed a complete whole-Phase-7 read-only audit and collected the
full finding set before remediation. F-001–F-004 were documentation-truth
findings discovered and remediated during earlier passes. The completed
consolidated whole-phase audit identified only F-005. F-005 was remediated in
a two-file candidate, and final differential verification independently
rechecked that defect and all behavior directly affected by the two-file
change. Unchanged previously audited artifacts were not reimplemented or
rewritten, and implementation-session completion reports were not accepted as
sole proof.

## Finding history

- F-001 LOW — stale source orchestration documentation — RESOLVED
- F-002 LOW — stale root README baseline wording — RESOLVED
- F-003 LOW — stale system overview — RESOLVED
- F-004 LOW — stale development guide — RESOLVED
- F-005 MEDIUM — malformed lifecycle-prefix history could grant retry
  ownership — RESOLVED

Final remaining ledger:

- CRITICAL: 0
- HIGH: 0
- MEDIUM: 0
- LOW: 0

## Scope audited

The audit covered the complete Phase 7 scope:

- M7A design and orchestration authority contract;
- M7B authenticated HTTP intake contract;
- M7C idempotent PostgreSQL-backed intake pipeline;
- M7D pinned n8n runtime and version-controlled sandbox workflow;
- M7E selective transport retry, demo seeding, recovery, and sandbox
  hardening;
- M7F independent audit and remediation process.

## Architecture and authority

AI interprets unstructured information; deterministic software decides.
Python owns business policy, validation, lifecycle transitions, persistence,
retry authority, and external side-effect contracts. n8n transports the
document, calls the authenticated backend, performs bounded transport retry,
and routes the backend-returned state. The workflow contains no Code or
Function node, AI node, database node, or business-authority operation.

## Authentication and intake

The orchestration route fails closed for missing or invalid service
credentials, compares configured credentials safely, and resolves the actor on
the server. Request metadata and document handling remain bounded, errors are
safe and non-diagnostic, and raw document bytes are not persisted as a Phase 7
queue or workflow artifact.

## Idempotency and execution claims

Phase 2 creation remains the authority for unique-key creation, replay, and
fingerprint conflict. The locked persisted order plus audit-generation history
is a separate execution authority; n8n has no secondary idempotency store.

The final fail-closed claim invariant requires every history interpreted beyond
the special `RECEIVED` initial-claim case to begin exactly:

`ORDER_RECEIVED` → `ORDER_PROCESSING_STARTED`

Missing, reordered, incomplete, or duplicated lifecycle-prefix histories are
invalid and return `STAND_DOWN`. The existing parser continues to validate
failure phases, retry requested/restored pairing, generation consumption,
sequential generations, mixed PROCESSING-to-EXTRACTED histories, and terminal
histories.

## Human retry authority

The existing reviewer-authorized retry command restores PROCESSING or
EXTRACTED state and records the restoration generation; it does not execute
work. Matching redelivery consumes the restored generation once. Duplicate
redelivery stands down, and ownership is decided under the persisted order
lock.

## Processing, extraction, and validation pipeline

The service composes the existing Phase 2 creation, Phase 3 document
processing, Phase 4 structured extraction, and Phase 5 deterministic
validation authorities. A normal path creates or replays the order, claims
execution, processes and extracts the document, validates deterministic
business facts, and routes to `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, or a
persisted operational failure.

An EXTRACTED retry reconstructs Phase 3 and Phase 4 from the same raw
redelivery while remaining EXTRACTED until validation. The immutable
extraction snapshot is committed once after successful reconstruction.

## Failure classification and atomicity

Typed provider, document, and business-data failures are classified by type and
lifecycle position. Retryable and final failure transitions use fixed safe
descriptions and do not expose provider text, source content, or diagnostics.
Failure state and audit events persist in one transaction with state rechecks;
SQLAlchemy failures propagate after rollback without a false success result.

## EXTRACTED reconstruction

EXTRACTED retry ownership is tied to the current lifecycle position and the
latest relevant restored generation. The same source identity and event
identity are required for redelivery. Reconstruction does not create a second
`ORDER_EXTRACTION_COMPLETED` event or duplicate immutable snapshot.

## HTTP and ambiguity semantics

The backend exposes bounded `201`, `200`, `202`, `409`, `422`, and `503`
outcomes. Business states such as `FAILED_RETRYABLE`, `PROCESSING`, and
`EXTRACTED` are normal authoritative HTTP responses, not transport failures.
Post-claim persistence ambiguity is explicit: if a claim or human-retry resume
marker commits and a later persistence step becomes unavailable, matching
redelivery can stand down rather than falsely reclaiming execution.

## n8n runtime and workflow

The verified runtime is pinned to n8n `2.40.5`. The version-controlled
workflow uses a finite standard-node graph with one initial request and at most
two retries. It retries only true HTTP Request connection/node errors and
HTTP `503`, with two one-second waits. It does not use native Retry On Fail.
Statuses `401`, `409`, `422`, generic `500`, `2xx FAILED_RETRYABLE`, `202
PROCESSING`, and `202 EXTRACTED` do not retry. Exhaustion returns a bounded
visible `503 UNAVAILABLE` response.

n8n does not choose lifecycle destinations, invoke reviewer retry, approve or
reject orders, validate business data, call Gemini, or perform ERP/CRM work.

## Identity preservation

Retry attempts preserve the original binary document and source identity,
including SHA-256, filename, MIME type, `document_type`, `message_id`, and the
caller-owned event ID forwarded as `Idempotency-Key`.

## Demo and recovery tooling

The deterministic PROCESSING and EXTRACTED `FAILED_RETRYABLE` demo seeds use
the real application-service path rather than direct persistence mutation.
The accepted sandbox fixture and clean-clone workflow handoff use synthetic
data, local credentials, and no live provider requirement.

## PostgreSQL concurrency evidence

The PostgreSQL integration surface proves initial ownership, duplicate
stand-down, one-owner processing and extracted retry generations, concurrent
loser behavior, atomic failure persistence, reconstruction, and the approved
post-claim ambiguity limitation. Provider work remains outside row-lock
transactions.

## Sandbox and clean-clone evidence

The pinned Compose runtime, sanitized workflow export, local service-auth
relinking,
publish/activation sequence, backend-state routing, bounded retry behavior,
synthetic fixture, and Vite/review handoff were verified against the local
Docker sandbox. Runtime credentials and execution state are not committed.

## Verification evidence

Final candidate CI [36138518909](https://github.com/Joseph-Nawar/OpsFlow_AI/actions/runs/36138518909)
completed successfully:

### Backend

- SUCCESS
- migration head: `0004_phase6_review_revisions`
- 1,304 tests passed
- 92.84% coverage
- Ruff, format, mypy, and package build passed

### Frontend

- SUCCESS
- 68 tests passed
- lint passed
- production build passed

### Workflow and local verification

- targeted claim unit tests: 26 passed;
- affected Phase 7 concurrency/pipeline/transport plus claims tests: 54 passed;
- n8n workflow contract: 6 passed;
- JSON, Compose configuration, and `git diff --check`: passed;
- full-history Gitleaks: 175 commits scanned, zero leaks.

## Privacy and cost posture

The Phase 7 runtime is network-free by default through the accepted fake
provider; Gemini is optional. No live provider, paid service, real customer
data, usable credential, raw uploaded document, or private runtime state is
committed. Secret scanning covers the full repository history.

## Known limitations and future boundaries

- There is no automatic abandoned PROCESSING/EXTRACTED claim reclaim.
- There is no lease, heartbeat, scheduler, reclaimer, or durable raw-document
  queue.
- Authentication remains development-only where applicable; production IAM and
  broader observability/security hardening remain future work.
- Gmail and Slack remain Phase 8 work.
- ERP/CRM remain Phase 9 work.
- No SYNCING executor is implemented.
- The final Phase 7 status closeout remains separate from this audit artifact.

## Final disposition

M7F — PASS

Phase 7 satisfies the approved n8n Workflow Orchestration scope and is ready
for repository status closeout. No Phase 8 functionality is included.
