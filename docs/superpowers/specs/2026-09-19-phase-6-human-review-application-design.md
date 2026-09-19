# Phase 6 — Human Review Application Contract & Design

## Document control

- **Repository:** `Joseph-Nawar/OpsFlow_AI`
- **Phase:** Phase 6 — Human Review Application
- **Current milestone:** M6A — Human Review Contract & Design
- **Design status:** Authoritative Phase 6 design specification; no Phase 6 implementation is authorized by this document alone
- **Design date:** 2026-09-19
- **Branch:** `phase/6-human-review-application`
- **Starting main SHA:** `5ac96d96da72be185b3b7cc9b24ad33fb72d7849`
- **Starting relationship:** the branch starts exactly at the verified `origin/main` commit; Phase 5 is fully merged and independently audited

This is a documentation and design milestone. It creates no production source,
migration, dependency, frontend component, HTTP endpoint, test, or
implementation-plan artifact. The design is intentionally limited to M6A and
does not claim that any Phase 6 runtime behavior exists yet.

## Status at the M6A baseline

The verified starting repository records Phase 0 through Phase 5 as
`COMPLETE`, including M5F — Independent Phase 5 Audit & Closeout. M6A begins
Phase 6, so truthful status for this branch is:

| Scope | Status |
| --- | --- |
| Phase 0–5 | `COMPLETE` |
| Phase 6 | `IN PROGRESS` |
| M6A — Human Review Contract & Design | `IN PROGRESS` |
| M6B — Review Persistence, Authorization & Read Model | `NOT STARTED` |
| M6C — Human Correction & Deterministic Revalidation | `NOT STARTED` |
| M6D — Approval, Rejection & Retry Commands/API | `NOT STARTED` |
| M6E — React Review Application & Cross-Boundary Hardening | `NOT STARTED` |
| M6F — Independent Phase 6 Audit & Closeout | `NOT STARTED` |
| Phase 7–12 | `NOT STARTED` |

## Governing sources

This specification is governed by:

1. [`AGENTS.md`](../../../AGENTS.md)
2. [Project roadmap](../../roadmap/project-roadmap.md)
3. [System overview](../../architecture/system-overview.md)
4. [Phase 1 domain model](../../architecture/domain-model.md)
5. [Phase 5 independent audit](../../audits/phase-5-audit.md)
6. [Phase 5 deterministic validation design](2026-09-17-phase-5-deterministic-validation-design.md)
7. [Phase 5 implementation plan](../plans/2026-09-17-phase-5-deterministic-validation.md)
8. The approved M6A request and locked architectural decisions

The current implementation remains authoritative. This document extends the
existing contracts only where the Phase 6 review workflow requires a new
immutable review record, application command, read model, or browser boundary.
It does not silently rewrite Phase 1 state semantics or Phase 5 snapshot,
validation, promotion, or audit behavior.

## 1. Purpose, outcome, and authority boundary

Phase 6 provides a browser-based operator workflow for three bounded queues:

- orders requiring human review;
- orders ready for approval;
- retryable failures awaiting an operator retry request.

An operator can inspect the order, original extraction and evidence, current
validation issues, current trusted reference data, the effective human review
draft, revision history, and the existing audit history. A permitted reviewer
can correct a `NEEDS_REVIEW` draft and save it through deterministic
revalidation. A permitted approver can approve an eligible order. A permitted
operator can reject an eligible order or request retry for a retryable failure.

The core invariant is:

> AI interprets; deterministic software validates; humans may correct or
> authorize; the UI never bypasses domain or application rules.

The authority boundaries are:

| Information or action | Authoritative owner | Phase 6 treatment |
| --- | --- | --- |
| Original AI interpretation | Immutable Phase 5 `ExtractionDraft` snapshot | Read-only original values, notes, evidence, source identity, and snapshot metadata |
| Human-corrected business values | Immutable Phase 6 `review_revisions` rows | Latest revision is the effective editable draft; past revisions cannot be changed or deleted |
| Current trusted business order | Phase 1 `Order` and ordered `OrderLine` graph | Read-only in review resources; changed only by the deterministic reviewed-data promotion path |
| Current validation outcome | Existing `validation_issues` rows | Replaced atomically by the deterministic revalidation operation |
| Current external reference values | Existing `BusinessDataProvider` contract | Separate volatile read; never part of the stable review-detail ETag |
| Lifecycle legality | Phase 1 `Order` operations and application services | Every mutation uses a legal domain operation and a final locked state check |
| Operator identity and role | Server-resolved immutable `OperatorContext` | Never accepted from request bodies or arbitrary client claims |
| Audit history | Existing `audit_events` persistence and `GET /v1/orders/{order_id}/audit` | Reused; review detail does not duplicate the history |

The browser renders and submits values. It does not determine route,
approval eligibility, high-value authority, revision numbers, old values,
trusted identities, state transitions, or audit actors. All such decisions are
made by Python application services under the final database transaction.

## 2. End-to-end flow

The Phase 6 workflow is:

```text
Bearer credential
        ↓ server-resolved OperatorContext
React queue → review detail read
                    ├── immutable original extraction/evidence
                    ├── effective ReviewDraft
                    ├── current trusted Order graph
                    ├── current validation issues
                    ├── current trusted reference-data read
                    └── existing audit-history read
                              ↓
          Save & revalidate / approve / reject / retry
                              ↓
             application authorization + If-Match check
                              ↓
       provider and pure ValidationEngine outside final transaction
                              ↓
          lock order → recheck state/revision/facts
                              ↓
             immutable revision/issues/state/audit writes
                              ↓
                         one commit
```

The final transaction contains no AI, provider, network, or browser operation.
Provider and validation work are performed before it; the order lock and
fresh local-fact/revision/state checks protect the final write.

Phase 6 does not invoke n8n, Gmail, Slack, Odoo, HubSpot, an ERP mutation, a
CRM mutation, stock reservation, or any other external side effect. Retry only
restores the recorded failure origin. Later orchestration is responsible for
resuming processing.

## 3. Existing state semantics and Phase 6 legal operations

The Phase 1 `OrderState` enum remains unchanged. Phase 6 does not add a review
state, an approval-level state, or a reopened state.

### 3.1 Human correction and revalidation

Editing is legal only while the locked order is `NEEDS_REVIEW`.

The effective review draft is composed with the original immutable source
identity, notes, and evidence and then passed through the existing Phase 5
deterministic `ValidationEngine`. The Phase 5 `ExtractionDraft` snapshot is
never mutated.

The state routes are:

```text
invalid correction:
NEEDS_REVIEW → VALIDATED → NEEDS_REVIEW

clean correction:
NEEDS_REVIEW → VALIDATED → READY_FOR_APPROVAL
```

The first route is a legal use of the existing state machine even though the
final state is unchanged. It records the new immutable revision and the new
current validation issues, while preserving the trusted order business graph.
The second route promotes only the `ValidatedOrderData` returned by the
existing engine, then reaches `READY_FOR_APPROVAL` through legal transitions.

The existing `Order.promote_validated_data()` operation remains intentionally
limited to `EXTRACTED`. Phase 6 must use a separate narrow operation,
conceptually `Order.promote_reviewed_data()`, that is legal only for
`NEEDS_REVIEW`, accepts only complete validated data plus application-created
line IDs, preserves order identity and source documents, and revalidates the
resulting Phase 1 `Order`/`OrderLine` invariants. It must not accept an
unvalidated `ReviewDraft`, raw request fields, or a `ValidationResult` with no
promotable data.

Invalid correction values therefore remain in the immutable review revision
and current issues only. They never become an invalid `OrderLine`, trusted
customer reference, trusted PO, trusted date, trusted currency, or trusted
order field. A clean correction replaces the trusted graph only with the
engine's trusted `ValidatedOrderData`, including trusted customer/product
identities and catalogue prices.

### 3.2 Approval

Approval is legal only from `READY_FOR_APPROVAL`.

The persisted `HIGH_VALUE_APPROVAL_REQUIRED` warning is the durable Phase 5
signal. There is no `approval_level` column. An ordinary `APPROVER` may not
approve an order carrying that warning. An `ELEVATED_APPROVER` may approve it.
Both roles may approve an ordinary ready order according to the authorization
matrix in Section 8. Approval invokes the existing legal
`READY_FOR_APPROVAL → APPROVED` transition and writes the approval audit event
atomically with that state change.

Approval does not start synchronization. The Phase 1 approval-before-sync
invariant remains authoritative; later workflow work owns `APPROVED → SYNCING`.

### 3.3 Rejection

Rejection is legal only from:

- `NEEDS_REVIEW` for `REVIEWER`;
- `READY_FOR_APPROVAL` for `APPROVER` or `ELEVATED_APPROVER`.

The request contains a trimmed, nonblank rejection reason with a maximum length
of 500 Unicode characters. The server stores the bounded reason in the
`ORDER_REJECTED` audit description and stores the server-resolved actor in the
audit `actor` field. The request cannot select an actor or role.

Rejection invokes the existing legal transition to `REJECTED` and commits the
state plus audit event atomically. Phase 6 exposes no `Order.reopen()` route;
reopening rejected orders is outside the phase even though the domain has that
capability.

### 3.4 Retry

Retry is legal only for `FAILED_RETRYABLE` and only for `REVIEWER`.

The application calls the existing `Order.retry()` operation. The persisted
`failure_origin` determines the only legal destination, which may be
`PROCESSING`, `EXTRACTED`, or `SYNCING`. The client cannot choose a destination
and Phase 6 does not rerun processing, extraction, integrations, or n8n.

The state change and audit records commit atomically. Later orchestration sees
the restored state and resumes the appropriate work.

## 4. Immutable review contract

### 4.1 `ReviewDraft`

`ReviewDraft` is a typed, immutable, untrusted review value. It contains only
the editable business values required to review and revalidate an order:

```text
ReviewDraft
├── customer_name: str | None
├── customer_reference: str | None
├── po_number: str | None
├── order_date: date | None
├── requested_delivery_date: date | None
├── currency: str | None
└── lines: tuple[ReviewLine, ...]

ReviewLine
├── sku: str | None
├── description: str | None
├── quantity: Decimal | None
└── submitted_price: Decimal | None
```

`ReviewDraft` intentionally permits missing, negative, zero, or otherwise
business-invalid quantities/prices and unsupported or malformed business text
where the existing `ExtractionDraft` contract permits it. The deterministic
engine must report those values as validation issues rather than the review
contract forcing them into Phase 1 domain objects. Optional text is either
`null` or a nonblank string, dates are exact `date` values or `null`, and
Decimal values are finite `Decimal` values or `null`. Collections are immutable
tuples in the application contract.

The ordered line collection is a complete editable list. A reviewer may
correct line values and may add, remove, or reorder lines when that is required
to correct the extracted business order. Any newly entered line has no AI
evidence claim; the UI must make that distinction clear. An empty list remains
representable so `ORDER_LINES_REQUIRED` remains a deterministic engine issue.

The following values are not in `ReviewDraft` and cannot be submitted for
editing:

- source SHA-256;
- source document type;
- source name, MIME type, message ID, storage reference, or metadata;
- original extraction notes;
- original extraction evidence;
- snapshot ID, revision number, actor, timestamp, or old values;
- trusted catalogue price, trusted inventory, customer active status, or
  product active status;
- lifecycle state, validation issues, approval role, or audit content.

### 4.2 Effective-draft projection

For a Phase 5-reviewed order, the application identifies the single immutable
Phase 5 extraction snapshot belonging to the order. Normal lifecycle semantics
produce one such snapshot before the order reaches `NEEDS_REVIEW` or
`READY_FOR_APPROVAL`; zero or multiple snapshots for a review case is a safe
persistence-integrity error, not a reason to guess.

The effective draft is projected as follows:

1. With zero review revisions, copy only the editable fields from the original
   `ExtractionDraft` into `ReviewDraft`, preserving line order and values.
2. With one or more revisions, load the highest `revision_number` and use its
   complete canonical `ReviewDraft` payload.
3. Preserve the original snapshot's source identity, notes, and evidence
   alongside the effective draft for every subsequent validation and response.

The latest revision is authoritative because revision numbers are unique per
order, positive, and assigned while holding the order lock. Revision history
is append-only. No update or delete operation exists for a past revision.

### 4.3 Composing a Phase 5 `ExtractionDraft`

Before trusted-data lookup and deterministic revalidation, application code
composes a fresh in-memory `ExtractionDraft`:

- `source_sha256` and `source_document_type` come from the immutable Phase 5
  snapshot and must still agree with the owned source document;
- customer name, customer reference, PO number, order date, requested
  delivery date, currency, and ordered lines come from the effective
  `ReviewDraft`;
- `notes` and `evidence` come unchanged from the immutable original snapshot.

This composition is an untrusted input boundary. It does not copy the draft
into the trusted order graph and does not assert that human values are true
because they are human-entered. The same Phase 5 provider contract,
`ValidationFacts`, explicit policy/context, and pure `ValidationEngine` are
reused; no second validation engine or human-specific rule set is introduced.

## 5. Review revision persistence

### 5.1 Migration and table ownership

M6B will add Alembic migration `0004_phase6_review_revisions` with
`down_revision = 0003_phase5_extraction_snapshots`. It introduces one focused
table, `review_revisions`, and no generic versioning, event-sourcing, field
history, workflow, or retry framework.

The table conceptually contains:

| Column | Type | Nullability and meaning |
| --- | --- | --- |
| `id` | PostgreSQL UUID | Required primary key; application-assigned revision identity |
| `order_id` | PostgreSQL UUID | Required foreign key to `orders.id`, `ON DELETE CASCADE` |
| `extraction_snapshot_id` | PostgreSQL UUID | Required owner snapshot identity, linked with `order_id` |
| `revision_number` | Integer | Required positive, strictly monotonically increasing per-order sequence number |
| `payload` | JSONB | Required complete canonical `ReviewDraft` object |
| `changes` | JSONB | Required ordered list of server-computed actual changes |
| `actor` | Text | Required nonblank server-resolved operator actor, bounded to 128 characters |
| `created_at` | `TIMESTAMPTZ` | Required application-supplied timezone-aware recording time |

The migration defines these ownership and integrity boundaries:

- primary key on `id`;
- unique `(order_id, revision_number)` named
  `uq_review_revisions_order_revision`;
- positive `revision_number` check named
  `ck_review_revisions_revision_positive`;
- `jsonb_typeof(payload) = 'object'` check named
  `ck_review_revisions_payload_object`;
- `jsonb_typeof(changes) = 'array'` check named
  `ck_review_revisions_changes_array`;
- nonblank, bounded actor check named `ck_review_revisions_actor` using
  `length(btrim(actor)) > 0 AND length(actor) <= 128`;
- foreign key `order_id → orders.id ON DELETE CASCADE`;
- composite ownership foreign key
  `(extraction_snapshot_id, order_id) → (extraction_snapshots.id,
  extraction_snapshots.order_id) ON DELETE CASCADE`.

Because PostgreSQL requires a referenced composite key, the same migration
adds a narrow redundant unique constraint on
`extraction_snapshots(id, order_id)`, named
`uq_extraction_snapshots_id_order_id`. It exists only to enforce that a
revision cannot point at another order's extraction snapshot. It is not a
second source of truth and does not make source SHA globally unique.

Deleting an order cascades its review revisions through the owned order and
snapshot records. Application persistence exposes insert and ordered read
operations only; it exposes no revision update or delete operation.

### 5.2 Canonical payload and strict deserialization

`payload` is a complete review draft, not a patch. Its exact JSON-safe shape
is:

```json
{
  "customer_name": null,
  "customer_reference": "CUST-001",
  "po_number": "PO-1001",
  "order_date": "2026-09-01",
  "requested_delivery_date": "2026-09-15",
  "currency": "USD",
  "lines": [
    {
      "sku": "SKU-001",
      "description": "Widget",
      "quantity": "2.5",
      "submitted_price": "10"
    }
  ]
}
```

Canonical serialization is deterministic:

- every top-level and line key is present, including explicit `null` values;
- top-level field order is `customer_name`, `customer_reference`, `po_number`,
  `order_date`, `requested_delivery_date`, `currency`, `lines`;
- line order is the effective draft order and line key order is `sku`,
  `description`, `quantity`, `submitted_price`;
- dates use exact ISO `YYYY-MM-DD` strings;
- finite Decimal values use fixed-point strings with no exponent notation,
  insignificant fractional zeroes removed, and every zero represented as
  `"0"`;
- optional text is preserved exactly after input contract validation; no
  case-folding, trimming, spell correction, or semantic rewriting changes
  business values;
- JSONB object-key order is not used for equality, while array order is
  semantic and preserved;
- no source identity, evidence, notes, actor, timestamp, UUID, provider
  response, prompt, credential, SDK object, or database value is serialized.

Deserialization accepts only the exact object shape, exact scalar types,
canonical dates and Decimal strings, finite values, explicit nulls, and ordered
line arrays. It rejects missing or extra keys, mutable domain collections,
noncanonical numbers/dates, nonblank violations, and any provider or internal
field. It returns an immutable typed `ReviewDraft`.

### 5.3 Server-computed changes

The client submits only the complete candidate `ReviewDraft`. The server
loads the current effective draft and computes changes in deterministic field
order. The client never supplies authoritative old values, revision numbers,
change lists, actors, or timestamps.

Each `changes` item has this canonical shape:

```json
{
  "field_path": "lines[0].submitted_price",
  "old_value": "12",
  "new_value": "10"
}
```

Top-level paths use their field names. Line paths use the zero-based ordered
line index. If line count or order changes, one `lines` change records the
complete old and new canonical line arrays; position-level comparisons are not
invented for ambiguous line identity. Changes are ordered by the fixed
top-level field order, then line index, then the fixed line field order.

The server inserts a revision only when the complete canonical candidate
differs from the effective draft. A no-op Save & revalidate is rejected with a
safe `NO_REVIEW_CHANGES` application error, creates no revision, changes no
issues or state, and creates no audit event. A revision always has at least one
change, and its stored `payload` is the complete candidate draft.

## 6. Revalidation transaction and concurrency contract

### 6.1 Save & revalidate sequence

`PUT /v1/review/orders/{order_id}/draft` is one command named **Save &
revalidate**. It is not an independent draft-save endpoint followed by a
separate validation action.

The application service performs this sequence:

1. Resolve the server-side `OperatorContext` and require `REVIEWER`.
2. Load the order, its owned Phase 5 extraction snapshot, the highest review
   revision, and the effective draft. Read the current review ETag.
3. Require and compare `If-Match`. A missing or mismatched validator stops the
   operation before provider work and returns a safe precondition error.
4. Require `NEEDS_REVIEW`; other states are rejected without mutation.
5. Deserialize the complete request candidate and compute the server-side
   canonical changes from the effective draft. Reject a no-op candidate.
6. Compose an untrusted `ExtractionDraft` from immutable source/evidence and
   candidate business values.
7. Resolve trusted customer/product/catalogue/inventory data through the
   existing `BusinessDataProvider` outside any final database transaction.
8. Read the current OpsFlow-local `ValidationFacts` for the composed draft.
9. Run the existing pure synchronous `ValidationEngine` once, outside any
   database transaction, using the explicit Phase 5 policy and context.
10. Begin the final database transaction and lock the order row with
    `SELECT ... FOR UPDATE`.
11. Recheck order state, source ownership/identity, the owning extraction
    snapshot, latest revision number, and the `If-Match` review state. A stale
    state/revision returns a safe stale-review error and rolls back.
12. Re-read the relevant local `ValidationFacts` inside the final transaction.
    If they differ from the facts used by the engine, abort safely with no
    revision, issue, graph, state, or audit write. The engine is not rerun in
    the transaction.
13. Allocate the next positive revision number under the order lock, insert
    the immutable complete payload and server-computed changes, and replace
    current validation issues with the engine result.
14. If errors remain, preserve the trusted order graph and route through
    `NEEDS_REVIEW → VALIDATED → NEEDS_REVIEW`.
15. If no errors remain, promote only `ValidatedOrderData` through the narrow
    reviewed-data promotion operation, then route through
    `NEEDS_REVIEW → VALIDATED → READY_FOR_APPROVAL`.
16. Insert the deterministic review audit events, then commit once. Return a
    response only after the commit succeeds.

No provider, AI model, network call, or external adapter executes inside the
final transaction. All persistence helpers are transaction-owned and do not
commit independently.

### 6.2 Stale state and facts

The order row lock serializes same-order final writes. The final checks reject
all of these safely:

- the order is no longer `NEEDS_REVIEW`;
- the latest review revision differs from the browser's ETag;
- the immutable source snapshot or source ownership no longer matches;
- OpsFlow-local duplicate/history facts changed after the engine read;
- another transaction already created the expected revision number.

The final transaction rolls back on any such failure. It never overwrites a
newer human correction, applies an invalid draft, or reruns the engine from
inside persistence. A caller may reload the detail and intentionally submit a
new command later.

### 6.3 Atomic writes and trusted graph behavior

One successful revalidation transaction includes the review revision, current
validation-issue replacement, allowed trusted graph promotion, legal state
transitions, and audit events. Any failure rolls back all of them together.

For a result with `ERROR` issues, existing trusted order scalar fields and
trusted lines remain unchanged. The new revision and issues still persist so
the operator can see the attempted correction and continue from its effective
draft. For a clean result, only engine-produced trusted values are promoted;
the human's raw candidate is not treated as trusted merely because it was
submitted by a reviewer.

## 7. Authorization and development authentication

### 7.1 Immutable operator context

The application defines exactly this role enum:

```text
REVIEWER
APPROVER
ELEVATED_APPROVER
```

`OperatorContext` is an immutable application value containing a nonblank,
bounded actor string and exactly one `OperatorRole`. It is created by the
server authentication dependency or injected explicitly by tests. It is not
constructed from request JSON, an arbitrary `X-Actor` header, an arbitrary
`X-Role` header, query parameters, or frontend state.

Authorization checks live in application services and are deny-by-default.
Routers may resolve the context, but a service must still require the
capability before performing a command. Unknown roles, missing context, and
malformed context cannot acquire a capability through fallback behavior.

### 7.2 Lightweight bearer authentication

Phase 6 uses FastAPI's standard bearer-security dependency. Development server
configuration maps one configured bearer credential to one configured actor and
one configured role. The credential is compared by the server; the client
never supplies the role as an authority claim. Missing credentials, unknown
credentials, and invalid configured role values fail safely with `401
Unauthorized`; protected endpoints do not become anonymous by default.

The configuration fields are `review_dev_token`, `review_dev_actor`, and
`review_dev_role`, exposed through the existing `OPSFLOW_` settings prefix as
`OPSFLOW_REVIEW_DEV_TOKEN`, `OPSFLOW_REVIEW_DEV_ACTOR`, and
`OPSFLOW_REVIEW_DEV_ROLE`. The token is optional only in the sense that an
unset token disables authenticated access; it never creates an anonymous
fallback. Any `.env.example` additions made by later implementation contain
empty or descriptive values only and never contain a real token. No secret or
token is committed. Tests may bypass the transport dependency by injecting an
explicit `OperatorContext` into the application service or test app
dependency override.

This is demo/development authentication plumbing. OAuth/OIDC, account
persistence, passwords, refresh tokens, session management, production IAM,
token rotation, and production security hardening belong to Phase 10 and are
not designed or implemented here.

### 7.3 Capability matrix

| Capability | `REVIEWER` | `APPROVER` | `ELEVATED_APPROVER` |
| --- | ---: | ---: | ---: |
| View review resources | Yes | Yes | Yes |
| Save & revalidate `NEEDS_REVIEW` | Yes | No | No |
| Reject `NEEDS_REVIEW` | Yes | No | No |
| Retry `FAILED_RETRYABLE` | Yes | No | No |
| Approve ordinary `READY_FOR_APPROVAL` | No | Yes | Yes |
| Approve high-value `READY_FOR_APPROVAL` | No | No | Yes |
| Reject ordinary or high-value `READY_FOR_APPROVAL` | No | Yes | Yes |

This is a fixed Phase 6 matrix, not a general permissions framework. The
backend computes permitted actions in the detail response from the resolved
context, order state, and persisted high-value warning. The UI may hide or
disable actions for clarity, but every command repeats server authorization
and state checks.

## 8. Stable ETag and optimistic concurrency

Every review-detail response includes a strong HTTP ETag. The ETag is a
lowercase SHA-256 digest in a quoted HTTP entity tag, derived from a canonical
server string containing at least:

```text
review-state-v1 |
order_id |
current_state |
failure_origin-or-null |
latest_review_revision_number-or-null |
latest_review_revision_id-or-null
```

The canonical separators and null spelling are fixed by the application
serializer; the hash is over UTF-8 bytes. Including the revision ID and
failure origin makes the validator sensitive to all Phase 6 mutations while
retaining the required order identity, lifecycle state, and latest revision
presence/number. The ETag does not include current external reference data,
provider output, prompts, credentials, or an audit history that is outside the
review mutation model.

`If-Match` is required for:

- Save & revalidate;
- approve;
- reject;
- retry.

Missing `If-Match` returns `428 Precondition Required` with a safe structured
error. A stale or malformed entity tag returns `412 Precondition Failed`; the
response does not expose SQL, revision payloads belonging to another actor,
provider details, or secrets. The application still locks the order and
rechecks state/revision before every write; ETag is not a replacement for the
transactional guard.

## 9. HTTP contract

The Phase 6 HTTP surface stays narrow and explicit. All review routes require
the resolved bearer operator context.

### 9.1 Queue

`GET /v1/review/orders`

Query parameters:

- `states`: zero or more repeated values from `NEEDS_REVIEW`,
  `READY_FOR_APPROVAL`, and `FAILED_RETRYABLE`; when omitted, all three are
  selected;
- `limit`: integer from 1 through 100, default 50;
- `offset`: integer at least 0, default 0.

The response is a bounded page with `items`, `limit`, `offset`, `total`, and
the selected states. Each item contains order ID, state, failure origin,
customer reference, PO number, order date, requested delivery date, currency,
created-at, current validation-issue count, and a boolean indicating whether
the persisted `HIGH_VALUE_APPROVAL_REQUIRED` warning is present. It contains
no raw source content or provider response.

Ordering is deterministic and operations-oriented: `created_at ASC, id ASC`
within the selected states. The total is filtered by the same selected states.
Pagination is bounded by the API validation contract; a client cannot request
an unbounded queue.

### 9.2 Review detail

`GET /v1/review/orders/{order_id}`

The response is stable database-backed review data plus backend-computed
actions. It contains:

- order identity, state, failure origin, created-at, current trusted scalar
  fields, and current trusted ordered lines;
- the effective `ReviewDraft`, its source snapshot ID, and latest revision
  number or absence;
- latest revision metadata and ordered revision/change history, including
  revision ID, number, actor, created-at, and server-computed field changes;
- source-document metadata: name, type, MIME, SHA-256, message/storage
  references, and safe metadata pairs;
- the original extraction snapshot's immutable source identity, business
  values, lines, notes, and evidence, clearly marked as **original AI
  extraction**;
- current persisted validation issues with rule code, severity, field,
  expected, actual, and explanation;
- a backend-computed operator identity/role summary and action flags for
  `can_edit`, `can_approve`, `can_reject`, and `can_retry`;
- the strong ETag in the HTTP response header and the same opaque ETag value
  in the response envelope for typed frontend state.

The response keeps the following distinctions explicit in both names and UI
labels:

1. **Original AI extraction and evidence** are immutable interpretation and
   provenance. Evidence does not prove a later human-edited value.
2. **Human-reviewed values** are the effective untrusted `ReviewDraft` and
   append-only revision history.
3. **Trusted persisted order data** is the current Phase 1 order graph after
   deterministic promotion, or the unchanged prior graph while review remains
   required.
4. **Deterministic validation issues** are current machine-generated findings,
   not AI confidence claims.

The detail response does not contain provider raw responses, prompts, API keys,
SDK objects, internal SQL, query plans, or hidden authentication material. It
does not embed audit history; clients call the existing audit route below.

For an order without a Phase 5 extraction snapshot, such as a retryable
failure that occurred before extraction persistence, extraction/effective-draft
sections are explicitly `null`, and draft editing/reference-data lookup is not
permitted. The main case can still show the order, failure origin, source
metadata, current issues, actions, and audit link. A persistence integrity
violation involving an expected snapshot is translated to a safe application
error rather than guessed or exposed.

### 9.3 Current trusted reference data

`GET /v1/review/orders/{order_id}/reference-data`

The application loads the current effective review draft and calls the
existing `BusinessDataProvider` with its exact customer identity and ordered
SKU inputs. The response is a separate volatile read labelled **current
trusted reference data** and contains:

- exact customer candidates with trusted reference, name, and active status;
- one product/reference result per effective line position, with SKU,
  description, active status, currency, catalogue price, and available
  quantity, or `null` when no exact trusted product exists.

The response is never included in the stable review-detail ETag and is not
persisted as a review revision. No broad customer/product search or catalogue
API is introduced. Exact correction inputs are sufficient for Phase 6; richer
Odoo-backed search can be considered only in Phase 9.

If the provider is unavailable or returns an invalid contract, the endpoint
returns a safe retryable `503` response with code `REFERENCE_DATA_UNAVAILABLE`
or `REFERENCE_DATA_INVALID` and no raw exception/provider payload. The main
review detail remains loadable, and the UI renders the reference panel as
unavailable with an explicit retry action. If no effective draft exists for a
pre-extraction failure, the endpoint returns a safe `409` response with code
`REVIEW_DRAFT_UNAVAILABLE`.

### 9.4 Save & revalidate

`PUT /v1/review/orders/{order_id}/draft`

Request body is a complete candidate `ReviewDraft` with the exact editable
fields from Section 4.1. It cannot contain a revision number, old value,
change list, actor, evidence, notes, source identity, state, or role.

Success returns `200` with the refreshed review-detail response and a new ETag.
The returned state is `NEEDS_REVIEW` when blocking errors remain or
`READY_FOR_APPROVAL` when the deterministic result has no errors. Warning-only
results, including high-value orders, remain `READY_FOR_APPROVAL` with the
persisted `HIGH_VALUE_APPROVAL_REQUIRED` warning.

The command returns safe structured errors for missing/stale `If-Match`, wrong
state, no actual change, invalid typed payload, provider failure, invalid
trusted data, local-fact staleness, persistence failure, or unexpected
transaction failure. It never returns provider text, SQL, source content, or
credentials.

### 9.5 Approval, rejection, and retry commands

`POST /v1/review/orders/{order_id}/approve`

- empty request body;
- requires `READY_FOR_APPROVAL` and `If-Match`;
- requires `APPROVER` for ordinary orders and `ELEVATED_APPROVER` when the
  persisted high-value warning is present;
- returns `200` with order ID, new state, failure origin, and new ETag;
- atomically persists `APPROVED` and `ORDER_APPROVED`.

`POST /v1/review/orders/{order_id}/reject`

- body `{ "reason": "bounded nonblank operator reason" }`;
- requires `If-Match` and the role/state matrix from Section 3.3;
- returns `200` with order ID, new state, failure origin, and new ETag;
- atomically persists `REJECTED` and `ORDER_REJECTED` with the bounded reason.

`POST /v1/review/orders/{order_id}/retry`

- empty request body;
- requires `REVIEWER`, `FAILED_RETRYABLE`, and `If-Match`;
- returns `200` with order ID, restored state, failure origin cleared, and new
  ETag;
- atomically calls `Order.retry()` and records the retry requested/restored
  audit events;
- does not run resumed processing or any integration.

All command responses use an application-defined safe error envelope with a
stable machine-readable `code` and bounded human-readable `message`. The
existing `GET /v1/orders/{order_id}/audit` route is reused unchanged in
purpose and remains the only audit-history HTTP resource.

## 10. Deterministic human audit behavior

Every successful Phase 6 mutation records the server-resolved actor and
application-supplied timezone-aware timestamps. When one command writes
multiple events, timestamps use the supplied command time plus successive
microseconds, matching the deterministic Phase 5 pattern. Event insertion,
state change, review revision, issue replacement, and trusted promotion share
one transaction.

The event contract is:

| Event type | Exact description | When |
| --- | --- | --- |
| `REVIEW_REVISION_RECORDED` | `Human review revision recorded.` | A non-no-op review revision is inserted |
| `REVIEW_REVALIDATION_COMPLETED` | `Deterministic revalidation completed for the effective human review draft.` | The existing engine completes for a saved candidate |
| `ORDER_REMAINS_NEEDS_REVIEW` | `Deterministic revalidation found blocking issues; human review remains required.` | Revalidation ends in `NEEDS_REVIEW` |
| `ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION` | `Deterministic revalidation passed; order is ready for approval after human correction.` | Clean ordinary correction |
| `ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION` | `Deterministic revalidation passed; elevated approval is required after human correction.` | Clean high-value correction |
| `ORDER_APPROVED` | `Order approved by operator.` | Approval commits |
| `ORDER_REJECTED` | `Order rejected. Reason: {trimmed_reason}` | Rejection commits; `{trimmed_reason}` is the bounded request reason |
| `ORDER_RETRY_REQUESTED` | `Retry requested by operator.` | Retry command commits |
| `ORDER_RETRY_RESTORED` | `Retryable failure cleared; order restored to its recorded failure origin.` | Retry command commits |

The structured revision row, not an audit description, records complete human
field changes. Audit descriptions do not repeat those values. Rejection reason
is the deliberate exception because it is an operator command justification,
not a review-draft field change. No event includes raw provider output, source
document body, prompts, credentials, or SDK objects.

## 11. Frontend architecture

Phase 6 keeps the current React 19, TypeScript, and Vite frontend lightweight.
The later implementation may add only the current stable `react-router`
package and the focused frontend test packages required by Section 12.

### 11.1 Routing and data access

Use React Router Declarative Mode with exactly these application routes:

- `/review` — queue page;
- `/review/:orderId` — review-detail page.

The existing Vite entry remains the composition root. The application uses
ordinary React components and local state, native `fetch`, and a small typed
API module that owns URL construction, response parsing, bearer headers, ETag
storage, and safe error decoding. It does not add Redux, Zustand, TanStack
Query, Tailwind, Material UI, shadcn, a generic design system, or another
frontend state framework.

Vite's development `/v1` proxy forwards to the local FastAPI server. No
development-only CORS layer is added.

### 11.2 Operator access interaction

For local development, the browser provides an access form where the operator
enters the configured development bearer credential. The credential is held in
React session state and may be mirrored only to `sessionStorage` when survival
across a browser refresh is needed. It is never hard-coded into source,
committed configuration, local storage, a production bundle, or a URL.

The frontend never asks for or stores an authoritative actor or role. The
backend returns the resolved operator summary and action flags. A missing or
invalid credential renders a safe access/error state and does not retry
indefinitely.

This interaction is development/demo authentication, not production identity.
Phase 10 owns production authentication and security hardening.

### 11.3 Review information hierarchy

The detail page uses semantic, labelled sections with visual distinctions for:

- **Original AI extraction and evidence:** read-only values, notes, evidence
  locations/quotes, and immutable source metadata;
- **Human-reviewed values:** the labelled edit form backed by the effective
  `ReviewDraft`;
- **Trusted persisted order:** read-only current `Order` and `OrderLine` data;
- **Deterministic validation issues:** rule code, severity, field, explanation,
  expected, and actual values;
- **Current trusted reference data:** separate loading/success/unavailable
  panel with an explicit current-data label;
- **Revision history:** append-only actor/time/change records;
- **Audit history:** loaded from the existing audit route rather than copied
  into the detail payload.

The page keeps the source limitation visible. It may show source name, type,
MIME, SHA-256, message/storage reference when present, original values, and
evidence location/quote. It does not claim to render the original raw source
file.

### 11.4 Loading, error, and concurrency behavior

The queue and detail pages each expose explicit loading, empty, success, and
error states. Queue filters preserve the selected allowed state set and use
backend pagination/order. Selecting an item navigates to its detail route.

The detail form sends the last server ETag in `If-Match`. A `412` response
shows that another mutation changed the case and offers reload; it does not
silently merge fields or replay a side effect. A successful save replaces the
local detail with the response and its new ETag. Action buttons are shown only
when backend-computed capabilities permit them, but API errors remain visible
when the server rejects a stale, unauthorized, or invalid action.

The trusted-reference panel can fail independently. Its failure does not hide
the main case and exposes a deliberate retry control. Provider response values
are displayed as current trusted reference data, never as persisted order
truth.

Forms use native labels, field-level errors, an error summary for failed
submission, keyboard-accessible controls, and semantic headings/regions. The
UI does not locally decide whether a value is business-valid beyond basic
input affordances; deterministic backend issues remain the source of truth.

## 12. Testing contract for later implementation

M6A creates no tests. The later milestones must add tests without invoking
live AI providers, external business systems, network mutations, real email,
Slack, n8n, or stock changes.

### 12.1 Persistence and serialization

Backend persistence coverage must prove:

- migration `0004_phase6_review_revisions` upgrades from the verified Phase 5
  head and downgrades its ownership dependencies in reverse order;
- UUID, order ownership, snapshot ownership, positive revision number,
  per-order uniqueness, actor bounds, JSON object/array checks, timezone-aware
  timestamp, and cascade behavior are enforced;
- a revision cannot reference another order's extraction snapshot;
- canonical `ReviewDraft` payloads round-trip with explicit nulls, ISO dates,
  canonical Decimal strings, ordered lines, and no extra/provider fields;
- strict deserialization rejects wrong types, missing/extra keys,
  noncanonical dates/Decimals, mutable collections, and source/evidence fields;
- field changes are canonical, ordered, server-computed, and based on the
  previous effective draft;
- no-op candidates create no revision, no audit, and no current-issue change;
- revision insert/read is append-only and no update/delete operation exists;
- effective-draft projection is correct for zero revisions and highest
  revision, including line-order changes.

### 12.2 Authorization and transport

Backend application/HTTP coverage must prove:

- the complete role matrix, including ordinary versus high-value approval;
- missing, unknown, and malformed bearer credentials fail safely;
- actor/role request-body or arbitrary-header claims are ignored and cannot
  grant authority;
- tests can inject explicit immutable operator contexts without real tokens;
- edit whitelist and complete draft shape are enforced;
- no-op edit rejection is safe;
- missing `If-Match` and stale ETags produce `428`/`412` structured errors;
- final order locking, state/revision checks, local-fact staleness, and safe
  rollback protect every review mutation;
- safe errors do not disclose provider payloads, source content, credentials,
  SDK objects, SQL, or stack traces.

### 12.3 Revalidation, commands, and audit

Application integration coverage must prove:

- provider lookup and pure-engine execution occur outside the final database
  transaction;
- invalid correction remains `NEEDS_REVIEW`, preserves the trusted order
  graph, replaces current issues, and records revision/revalidation/review
  audit events atomically;
- clean correction promotes only trusted `ValidatedOrderData` and reaches
  `READY_FOR_APPROVAL` with the high-value warning persisted when applicable;
- ordinary approval, elevated high-value approval, and rejection of a
  high-value order by an ordinary approver behave as specified;
- rejection reason and server actor appear in audit history;
- retry works from each valid `failure_origin`, clears the failure origin, and
  does not run resumed processing;
- invalid state actions, stale ETags, stale local facts, races, and injected
  write failures roll back all related writes;
- existing Phase 1–5 behavior remains covered by regression tests.

### 12.4 Frontend

The first business-critical frontend phase must add Vitest, React Testing
Library, `@testing-library/user-event`, and the required DOM matchers/jsdom
configuration. Component/integration tests must cover:

- queue loading, success, empty, error, filters, deterministic navigation,
  and pagination;
- detail loading, success, safe error, source-document limitation, original
  extraction/evidence distinction, human-reviewed values, trusted order data,
  validation issues, revision history, and audit loading;
- current trusted reference-data success, unavailable, and retry states;
- labelled edit form, complete Save & revalidate behavior, invalid correction,
  clean correction, and no-op error;
- ETag capture, `If-Match` submission, stale `412` handling without replay;
- allowed/hidden actions, ordinary approval, high-value approval restriction,
  elevated approval, rejection, retry, and API error rendering;
- operator credential entry, session-only handling, backend-resolved role
  display, and safe authentication errors.

Playwright and Cypress are not part of the Phase 6 design because unit and
component/integration tests cover the specified browser behavior. A concrete
cross-browser requirement would need a later scope decision. CI later runs
frontend tests in addition to lint and build.

## 13. Source-document limitation

Phase 6 does not persist raw source files and does not create object storage,
OCR, a PDF viewer, an email viewer, or a raw-file download route. The existing
Phase 3/4/5 source contract retains metadata, references when present, source
hash, original extraction fields, and evidence location/quote only.

The UI must label evidence as the original AI extraction's provenance. It must
not suggest that an evidence quote verifies a later human edit, and it must
not imply that a storage reference guarantees that a raw file is available in
the Phase 6 application.

## 14. Non-goals and future boundaries

Phase 6 explicitly excludes:

- n8n workflow implementation or changes;
- Gmail, Slack, Odoo, HubSpot, ERP, CRM, or other external mutations;
- stock reservation or inventory mutation;
- OAuth/OIDC, production IAM, accounts, passwords, refresh tokens, or
  production security hardening;
- object storage, raw source-file persistence, OCR, PDF/email viewers, or
  download routes;
- a generic workflow engine, event-sourcing/versioning framework, field-change
  table, generic retry framework, or generic permissions framework;
- approval-level persistence or a new order state;
- reopening rejected orders;
- broad customer/product/catalogue search APIs;
- a second validation engine, LLM validation call, provider prompt, or AI
  approval decision;
- provider raw-response persistence, prompt persistence, credentials, SDK
  objects, or internal SQL in responses;
- Phase 7–12 implementation, integration, evaluation, or release work.

The only planned persistence concept for review history is the focused
immutable `review_revisions` table. The only planned frontend state mechanism
is ordinary React state plus a small typed API layer. The existing business
provider and deterministic engine remain the reusable Phase 5 contracts.

## 15. Phase 6 milestone boundaries

| Milestone | Boundary |
| --- | --- |
| **M6A — Human Review Contract & Design** | This authority, persistence, concurrency, authorization, API, frontend, testing, non-goal, and source-limitation design; documentation-only status update; no implementation |
| **M6B — Review Persistence, Authorization & Read Model** | Implement `ReviewDraft`/operator contracts, migration `0004`, immutable revision persistence, effective-draft projection, authentication dependency, queue/detail/reference-data reads, and backend read/authorization coverage |
| **M6C — Human Correction & Deterministic Revalidation** | Implement Save & revalidate, reviewed-data promotion, provider/engine transaction boundaries, issue replacement, stale-fact guards, revision/audit writes, and correction coverage |
| **M6D — Approval, Rejection & Retry Commands/API** | Implement command authorization, ETag preconditions, legal state operations, high-value approval restriction, rejection reason, retry restoration, HTTP contracts, and command coverage |
| **M6E — React Review Application & Cross-Boundary Hardening** | Implement the two React routes, typed fetch layer, access interaction, queue/detail/forms/panels, accessible states, Vitest/RTL coverage, frontend CI, and backend/frontend hardening |
| **M6F — Independent Phase 6 Audit & Closeout** | Fresh read-only audit, justified remediation if required, exact-head CI evidence, status closeout, and durable audit report |

M6A does not create the implementation plan. The milestone boundaries above
define ownership and sequencing without authorizing M6B–M6F implementation.

## 16. Design self-review checklist

The design was reviewed against the requested Phase 6 boundary:

- Phase 1 state transitions remain authoritative; no new state or implicit
  reopening is introduced.
- The Phase 5 extraction snapshot remains immutable and untrusted; human data
  is stored in a separate immutable complete review revision.
- Human edits are composed with original source identity, notes, and evidence,
  and the existing deterministic engine is reused exactly once outside the
  final transaction.
- Trusted order fields and lines are never populated from invalid review
  values; clean promotion uses validated trusted data through a separate
  `NEEDS_REVIEW`-specific path.
- Actors and roles are server-resolved through a bearer dependency and fixed
  role matrix; client claims cannot grant authority.
- High-value approval uses the persisted Phase 5 warning and no
  `approval_level` column.
- Every mutation requires `If-Match`, uses a strong ETag, locks the order, and
  rechecks state, revision, source ownership, and local facts before commit.
- Provider/network and pure-engine calls are outside the final write
  transaction; all final writes are atomic.
- Queue ordering/pagination, stable detail response, separate current trusted
  reference data, and reuse of the existing audit endpoint are explicit.
- Raw-source persistence/viewing, external integrations, generic frameworks,
  and Phase 7–12 functionality are excluded.
- Backend and frontend test obligations cover serialization, authorization,
  concurrency, rollback, state routes, privacy, UI states, and regression
  behavior without creating tests in M6A.
- The document contains no unresolved design markers and no secret/token
  values.

## 17. M6A acceptance boundary

M6A is ready for independent review when this specification, the README status,
and the roadmap status consistently identify Phase 6/M6A as `IN PROGRESS`,
identify M6B–M6F and Phase 7–12 as `NOT STARTED`, and the committed diff
contains no product implementation. M6A is not marked `COMPLETE` by this
candidate.
