# Phase 1 Domain Model & State Machine Contract

## Status and authority

This document is the authoritative domain specification for Phase 1. It was
created by M1A — Domain Contract & Implementation Plan. The contract was
implemented through M1E: M1B supporting records, the immutable M1C Order
aggregate, M1D state-machine and retry/reopen behavior, and M1E scenario
verification and hardening are complete. The independent M1F audit and final
Phase 1 closeout have not yet passed, so Phase 1 remains in progress.

The domain is a pure-Python, infrastructure-independent representation of a
purchase order and its lifecycle. Later implementation work must implement
this document without silently adding business policy or external-system
knowledge.

## 1. Responsibility boundary

Phase 1 owns:

- structural domain representation;
- immutable domain snapshots;
- structural invariants;
- state-machine legality;
- retry and rejected-order reopening semantics.

Phase 1 does not own:

- persistence;
- HTTP/API schemas;
- LLM extraction;
- document parsing;
- customer or product lookup;
- inventory lookup;
- duplicate-PO detection;
- pricing tolerance;
- supported-currency business policy;
- high-value approval policy;
- external side effects.

The domain must work without PostgreSQL, SQLAlchemy, FastAPI, Docker,
network access, AI providers, n8n, Odoo, HubSpot, Gmail, or Slack. It must
not import any of those systems or their integration modules.

The approved implementation uses only Python standard-library domain types:
frozen `dataclasses`, `Enum`, `Decimal`, `UUID`, `date`, and timezone-aware
`datetime`. Phase 1 adds no runtime dependency.

## 2. Domain design rules

Every domain record is an immutable snapshot. The planned implementation uses
frozen dataclasses with tuple collections where collections are part of the
snapshot. Callers must not be able to perform arbitrary mutation such as
`order.state = OrderState.COMPLETED`. Operations that change state return a new, validated
`Order` and leave the original object unchanged.

Immutability applies to every state, not only `COMPLETED`. It is a value and
snapshot design choice, not event sourcing: Phase 1 has no event bus, event
sourcing, repository, service, dependency-injection, or state-machine
framework architecture.

`Decimal` is required for quantities and prices. Binary floating-point values
are not part of the domain contract. Decimal values must be finite wherever
the contract says finite; signaling NaN, quiet NaN, positive infinity, and
negative infinity are invalid.

## 3. Supporting domain records

### 3.1 OrderLine

Planned record: immutable `OrderLine`.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `UUID` | Stable identity of the line within the domain snapshot. |
| `sku` | `str \| None` | Extracted or supplied stock-keeping-unit text, if present. |
| `description` | `str \| None` | Useful human-readable item description, if present. |
| `quantity` | `Decimal` | Requested quantity. |
| `submitted_price` | `Decimal \| None` | Price submitted with the order, if present. |
| `trusted_catalogue_price` | `Decimal \| None` | Reference catalogue price, if available. |

Structural invariants:

- `quantity` is finite and strictly greater than zero;
- each supplied price is finite and greater than or equal to zero;
- at least one of `sku` or a useful `description` is present. A useful
  description is a non-blank string after surrounding whitespace is ignored;
- quantity and prices use `Decimal`, never binary `float`.

`trusted_catalogue_price` is reference information only. Phase 1 does not
compare it with `submitted_price` and does not decide whether the submitted
price is acceptable. Price tolerance is later deterministic business policy.

### 3.2 SourceDocument

Initial `SourceDocumentType` values are exactly:

- `EMAIL_BODY`
- `PDF`
- `XLSX`
- `CSV`
- `FORM`

Planned record: immutable `SourceDocument`.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `UUID` | Stable source-document identity. |
| `document_type` | `SourceDocumentType` | Canonical kind of source. |
| `name` | `str` | Human-readable source name. |
| `mime_type` | `str` | Declared MIME type. |
| `sha256` | `str` | Lower- or upper-case hexadecimal SHA-256 digest. |
| `message_id` | `str \| None` | Source-message identifier when the document came from messaging. |
| `storage_reference` | `str \| None` | Reference to externally stored content, if one exists. |
| `metadata` | `immutable key/value metadata` | Small provenance metadata snapshot. |

The metadata representation must be immutable and standard-library based. The
planned implementation uses a tuple of key/value pairs so it does not expose
a mutable dictionary through a frozen dataclass.

Structural invariants:

- `name` is non-empty;
- `mime_type` is non-empty;
- `sha256` is exactly 64 hexadecimal ASCII characters, matched
  case-insensitively;
- the record does not parse files, detect MIME types, persist files, or
  perform duplicate detection.

### 3.3 ValidationIssue

Initial `ValidationSeverity` values are exactly:

- `INFO`
- `WARNING`
- `ERROR`

Planned record: immutable `ValidationIssue`.

Structural invariants are that `rule_code` is non-blank, `explanation` is
non-blank, and a supplied `field` is non-blank. `expected` and `actual` retain
their `object | None` representation and have no additional Phase 1 shape
requirement.

| Field | Type | Meaning |
| --- | --- | --- |
| `rule_code` | `str` | Identifier of the rule that produced the issue. |
| `severity` | `ValidationSeverity` | Impact classification. |
| `field` | `str \| None` | Affected field path, if specific. |
| `expected` | `object \| None` | Expected value or shape, if useful. |
| `actual` | `object \| None` | Observed value or shape, if useful. |
| `explanation` | `str` | Human-readable explanation. |

Phase 1 represents issues but does not implement validation rules or decide
which issue to generate. Rule generation belongs to Phase 5 and may use this
record as its output contract.

### 3.4 AuditEvent

Planned record: immutable `AuditEvent`.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `UUID` | Stable audit-record identity. |
| `order_id` | `UUID` | Order to which the event relates. |
| `event_type` | `str` | Event category. |
| `actor` | `str` | Actor or subsystem responsible for the event. |
| `occurred_at` | `datetime` | Time at which the event occurred. |
| `description` | `str` | Human-readable event description. |

Required strings (`event_type`, `actor`, and `description`) are non-empty.
`occurred_at` must be timezone-aware: its `tzinfo` must be present and its
UTC offset must not be `None`. Naive datetimes are invalid.

There is no event bus, event sourcing, automatic publishing, or logging
behavior in this record. Phase 1 defines representation only.

## 4. Order aggregate

Planned record: immutable `Order`.

| Field | Type | Meaning |
| --- | --- | --- |
| `id` | `UUID` | Stable order identity. |
| `customer_reference` | `str \| None` | Customer identifier or reference when known. |
| `po_number` | `str \| None` | Purchase-order number when known. |
| `order_date` | `date \| None` | Order date when extracted or supplied. |
| `requested_delivery_date` | `date \| None` | Requested delivery date when known. |
| `currency` | `str \| None` | ISO-like structural currency code when present. |
| `lines` | `tuple[OrderLine, ...]` | Immutable order-line snapshot. |
| `source_documents` | `tuple[SourceDocument, ...]` | Immutable provenance snapshot. |
| `state` | `OrderState` | Lifecycle state. |
| `failure_origin` | `OrderState \| None` | State from which a failure was recorded, when applicable. |

Core business fields are optional because an order exists at `RECEIVED`
before extraction has populated customer, PO number, dates, currency, and
lines. An empty `lines` tuple is therefore valid for a pre-extraction
`RECEIVED` snapshot. Phase 1 does not require a customer, PO number, date,
currency, or line before extraction.

`lines` and `source_documents` are tuples in the public domain contract;
mutable list collections are not accepted as the snapshot representation.
Optional business text remains optional and Phase 1 does not infer or enrich
its content.

Every constructed `Order` snapshot must satisfy the state/origin consistency
invariant:

- when `state` is `FAILED_RETRYABLE` or `FAILED_FINAL`,
  `failure_origin` must be exactly one of `PROCESSING`, `EXTRACTED`, or
  `SYNCING`;
- for every other state, `failure_origin` must be `None`.

Therefore construction rejects `FAILED_RETRYABLE` with no origin,
`FAILED_FINAL` with `COMPLETED` as its origin, `RECEIVED` with `SYNCING` as
its origin, and `COMPLETED` with any failure origin, using
`DomainValidationError`. Failure transitions create valid snapshots by
recording the previous operational state. `FAILED_FINAL` retains that valid
origin for information only; it never authorizes retry or reopening.

`Order.received(...)` is the normal business creation path for a new order and
always creates `state=RECEIVED` and `failure_origin=None`. Direct aggregate
construction, if retained as a low-level snapshot mechanism for tests and
future persistence rehydration, is not a lifecycle operation and must satisfy
all structural and state/origin invariants as well.

## 5. Currency boundary

Currency is a structural field, not a supported-currency policy decision.

- `currency=None` is valid before extraction.
- When present, `currency` must be exactly three uppercase ASCII letters.
- Valid structural examples are `USD`, `EUR`, and `EGP`.
- Structurally invalid examples are `usd`, `US`, `USDD`, and `12A`.

Phase 1 contains no hardcoded supported-currency set. Phase 5 owns the
business-policy question: “Is this structurally valid currency
supported/configured by this deployment?”

## 6. States and ordinary transitions

`OrderState` has exactly these twelve values:

`RECEIVED`, `PROCESSING`, `EXTRACTED`, `VALIDATED`, `NEEDS_REVIEW`,
`READY_FOR_APPROVAL`, `APPROVED`, `SYNCING`, `COMPLETED`, `REJECTED`,
`FAILED_RETRYABLE`, and `FAILED_FINAL`.

The following 17 ordinary transitions are the complete normal transition
table. A transition not listed here is illegal.

| Current state | Legal next state(s) |
| --- | --- |
| `RECEIVED` | `PROCESSING` |
| `PROCESSING` | `EXTRACTED`, `FAILED_RETRYABLE`, `FAILED_FINAL` |
| `EXTRACTED` | `VALIDATED`, `FAILED_RETRYABLE`, `FAILED_FINAL` |
| `VALIDATED` | `NEEDS_REVIEW`, `READY_FOR_APPROVAL` |
| `NEEDS_REVIEW` | `VALIDATED`, `REJECTED` |
| `READY_FOR_APPROVAL` | `APPROVED`, `REJECTED` |
| `APPROVED` | `SYNCING` |
| `SYNCING` | `COMPLETED`, `FAILED_RETRYABLE`, `FAILED_FINAL` |
| `COMPLETED` | none |
| `REJECTED` | none through ordinary transitions |
| `FAILED_RETRYABLE` | none through ordinary transitions |
| `FAILED_FINAL` | none |

`FAILED_RETRYABLE` and `REJECTED` are intentionally controlled by explicit
operations rather than generic normal recovery transitions.

### Approval-before-sync invariant

The only legal normal entry to `SYNCING` is `APPROVED -> SYNCING`. The domain
state graph itself rejects `VALIDATED -> SYNCING`,
`NEEDS_REVIEW -> SYNCING`, `READY_FOR_APPROVAL -> SYNCING`, and
`REJECTED -> SYNCING`. This invariant is not delegated to an LLM, n8n, an
API, or persistence code.

### Immutable state change

The planned operation `transition_to(target: OrderState) -> Order` validates
the requested normal transition and returns a new snapshot. It does not mutate
the current order. On ordinary non-failure transitions, `failure_origin` is
cleared unless the operation is explicitly recording a failure state.

## 7. Retry and reopen semantics

### Retryable failures

Only `PROCESSING`, `EXTRACTED`, and `SYNCING` may transition through the
ordinary table to `FAILED_RETRYABLE`. When that happens, the returned snapshot
stores `failure_origin` as the exact previous operational state:

- `PROCESSING -> FAILED_RETRYABLE` stores `failure_origin=PROCESSING`;
- `EXTRACTED -> FAILED_RETRYABLE` stores `failure_origin=EXTRACTED`;
- `SYNCING -> FAILED_RETRYABLE` stores `failure_origin=SYNCING`.

The explicit operation `retry() -> Order` may be called only from
`FAILED_RETRYABLE`. It returns a new snapshot in exactly the recorded
`failure_origin`; callers cannot select an arbitrary destination. The returned
snapshot clears `failure_origin` because the active retry failure no longer
exists. A missing, terminal, or otherwise invalid recorded origin is a domain
error rather than an opportunity to guess a destination.

`FAILED_FINAL` cannot retry. For diagnosability, the transition to
`FAILED_FINAL` records the previous operational state in `failure_origin`,
but that value is informational only and never authorizes recovery. Neither
failure state has an ordinary outgoing transition.

### Rejected-order reopening

`REJECTED` recovery is not a generic transition. The explicit operation
`reopen() -> Order` may be called only from `REJECTED` and returns a new
snapshot in `NEEDS_REVIEW`, with no active failure origin.

The intended recovery path is:

`REJECTED` -> `reopen()` -> `NEEDS_REVIEW` -> `VALIDATED` -> `NEEDS_REVIEW`
or `READY_FOR_APPROVAL`.

Ordinary `REJECTED -> PROCESSING`, `REJECTED -> VALIDATED`, and
`REJECTED -> READY_FOR_APPROVAL` transitions are illegal. `reopen()` is
illegal from every state other than `REJECTED`.

### Terminal states

`COMPLETED` has no outgoing lifecycle transition, no retry, and no reopen.
`FAILED_FINAL` has no outgoing lifecycle transition, no retry, and no reopen.
If a future requirement needs post-completion correction, it must introduce an
explicit future-phase process rather than being inferred in Phase 1.

## 8. Domain errors

The planned domain-specific errors are:

- `DomainValidationError` for invalid record values or invalid structural
  invariants;
- `InvalidStateTransitionError` for illegal lifecycle requests.

Neither error is coupled to HTTP or a framework. `InvalidStateTransitionError`
exposes at least `current_state`, `requested_state`, and `operation`. For a
normal transition, `requested_state` is the requested `OrderState`; for
`retry()` and `reopen()`, `operation` identifies the explicit operation and
`requested_state` may be `None` because the destination is domain-controlled.
The domain defines no logging behavior.

## 9. Structural versus business validation

| Phase 1 structural domain contract may enforce | Phase 1 must not decide; later deterministic policy owns it |
| --- | --- |
| Positive, finite quantity | Customer existence or active status |
| Finite, non-negative supplied prices | SKU existence |
| At least one SKU or useful description | Inventory sufficiency |
| Currency-code shape when currency is present | Price tolerance or price acceptability |
| SHA-256 shape | Duplicate PO detection |
| Non-empty required record strings | Document duplicate policy |
| Timezone-aware audit timestamp | Supported-currency business configuration |
| Legal state transition | Commercially sensible delivery date |
| Immutable tuple snapshots | High-value approval rules |

Phase 5 or another later phase may generate `ValidationIssue` records for
these business decisions. The domain record does not perform those lookups,
comparisons, policies, or side effects.

## 10. Required later test contract

The M1B–M1E implementation must add focused tests under
`tests/unit/domain/`. The tests must include the following categories.

### Supporting records

- `OrderLine` accepts positive quantity;
- zero, negative, NaN, and infinite quantity are rejected;
- negative supplied prices are rejected;
- missing both SKU and meaningful description is rejected;
- a valid `SourceDocument` is accepted;
- malformed SHA-256, blank name, and blank MIME type are rejected;
- blank `rule_code`, blank `explanation`, and supplied blank `field` are
  rejected for `ValidationIssue`;
- a timezone-aware `AuditEvent` is accepted;
- a naive audit timestamp is rejected;
- supporting records and metadata are immutable;
- severity and source-document enums expose exactly the defined values.

### Order aggregate

- a pre-extraction `RECEIVED` order can exist with optional business fields
  absent;
- tuple collections and all fields are immutable;
- structurally invalid order values are rejected;
- currency shape accepts `USD`, `EUR`, and `EGP`, rejects `usd`, `US`,
  `USDD`, and `12A`, and does not reject a structurally valid code merely
  because it is outside a hardcoded supported set.

### State machine and scenarios

- every one of the 17 listed legal transitions succeeds;
- every unlisted pair across the complete 12-state set is rejected;
- approval-before-sync is enforced;
- `COMPLETED` and `FAILED_FINAL` are terminal;
- retry works from `PROCESSING`, `EXTRACTED`, and `SYNCING` failures;
- retry is disallowed outside `FAILED_RETRYABLE`;
- retry restores the recorded origin and cannot accept a destination choice;
- rejected-order reopening returns exactly `NEEDS_REVIEW`;
- reopen is disallowed outside `REJECTED`.

Scenario tests must cover a successful lifecycle, review/revalidation,
reject/reopen, and retryable sync failure. State-transition tests must be
table-driven and exhaustive across the defined state set, not a sample of
illegal pairs.

## 11. Infrastructure-independence acceptance rule

The later domain implementation must support:

```bash
uv run pytest tests/unit/domain -q --no-cov
```

with PostgreSQL stopped, Docker stopped, no network, and no FastAPI server.
The `--no-cov` option is used only for this isolated domain-independence
check because the repository-wide pytest configuration measures coverage
across all `opsflow` modules. It does not weaken the global coverage
requirement enforced by the full repository quality gates.
The domain source must have no imports from FastAPI, SQLAlchemy, asyncpg,
Alembic, AI-provider modules, or integration modules. The full repository
quality gates still apply before Phase 1 closeout.

## 12. Phase 1 implementation sequence

The durable implementation plan is
[2026-09-13-phase-1-domain-model.md](../superpowers/plans/2026-09-13-phase-1-domain-model.md).
It covers M1B Supporting Domain Records, M1C Order Aggregate, M1D State
Machine & Recovery Semantics, and M1E Domain Scenario Verification & Contract
Hardening. M1F is an independent audit and is intentionally excluded from
that implementation plan.
