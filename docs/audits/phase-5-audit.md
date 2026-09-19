# Phase 5 Independent Audit

## Audit identity

- Repository: Joseph-Nawar/OpsFlow_AI
- Phase: Phase 5 — Deterministic Validation
- Branch: phase/5-deterministic-validation
- Audit date: 2026-09-19
- Main / Phase 4 baseline: 84de8ed70b745bf987227953495320deccee94fe
- Initial audit candidate: 041d03038fc403fc8a3a1f05657e38d071442969
- M5F-001 remediation: b0622a0a9e734675516ccbe9ee76a5ac34914961
- Final audited candidate: b0622a0a9e734675516ccbe9ee76a5ac34914961
- Merge-base: 84de8ed70b745bf987227953495320deccee94fe
- Final audited relationship before this documentation commit: 29 ahead / 0 behind main

The initial M5F audit was read-only and was completed before this audit
document existed. It found one MEDIUM issue. M5F-001 was then remediated in
the remediation commit above. A second fresh, whole-Phase-5, read-only audit
was performed against the remediated candidate. The final re-audit found zero
CRITICAL, HIGH, MEDIUM, or LOW findings.

## Initial audit finding history

| ID | Severity | Area | Problem | Disposition |
| --- | --- | --- | --- | --- |
| M5F-001 | MEDIUM | Application local-fact customer identity | The application filtered customer candidates to active candidates before resolving the canonical duplicate-PO identity. A set containing one active exact-match customer and one inactive exact-match customer could therefore supply the active reference to local customer+PO lookup even though the ValidationEngine correctly classified the complete two-candidate identity as ambiguous. | RESOLVED |

### M5F-001 detail

The defect meant that ValidationFacts could contain a duplicate-PO fact derived
from an identity that was not actually resolved. In a local-history race, this
could also cause an unnecessary ValidationFactsChangedError for an order that
should simply route to NEEDS_REVIEW for AMBIGUOUS_CUSTOMER.

The remediation changed canonical customer identity construction so that only
a complete candidate set containing exactly one candidate, where that
candidate is active, supplies a reference for duplicate-PO lookup.

Regression evidence verified:

- zero candidates produce None;
- one inactive candidate produces None;
- one active candidate produces its reference;
- multiple active candidates produce None;
- a mixed active/inactive candidate set produces None;
- both the initial and final local-facts reads use None for the ambiguous identity;
- the processed-source fact remains independently evaluated;
- the real engine still emits AMBIGUOUS_CUSTOMER for multiple candidates;
- DUPLICATE_CUSTOMER_PO is suppressed when the customer identity is ambiguous.

Remediation commit: b0622a0a9e734675516ccbe9ee76a5ac34914961.

## Final re-audit finding ledger

The second fresh whole-Phase-5 read-only audit found no remaining CRITICAL,
HIGH, MEDIUM, or LOW finding after remediation.

- CRITICAL: 0
- HIGH: 0
- MEDIUM: 0
- LOW: 0

## Scope audited

The audit covered the complete baseline-to-final-candidate Phase 5 diff,
including:

- M5A design and implementation-plan artifacts;
- validation value contracts;
- ValidationPolicy;
- the trusted business-data protocol;
- the deterministic sandbox provider;
- the pure ValidationEngine and all 28 approved rule codes;
- Decimal/date arithmetic and threshold semantics;
- narrow Order promotion;
- the extraction-snapshot migration and ORM model;
- strict snapshot serialization and deserialization;
- repository snapshot, local-fact, issue, locking, and graph operations;
- the internal validation application service;
- transaction boundaries, replay/conflict semantics, local-fact staleness,
  atomic routing, rollback, audit events, safe errors, and privacy;
- M5E adversarial tests;
- Phase 1–4 regression behavior;
- cost, side-effect, and scope boundaries;
- the M5F-001 remediation.

The governing sources were [AGENTS.md](../../AGENTS.md), [the project
roadmap](../roadmap/project-roadmap.md), [the domain model](../architecture/domain-model.md),
[the system overview](../architecture/system-overview.md), [the development
guide](../development/development-guide.md), [the Phase 2 audit](phase-2-audit.md),
[the Phase 3 audit](phase-3-audit.md), [the Phase 4 audit](phase-4-audit.md),
[the Phase 5 design](../superpowers/specs/2026-09-17-phase-5-deterministic-validation-design.md),
and [the Phase 5 implementation plan](../superpowers/plans/2026-09-17-phase-5-deterministic-validation.md).

## Architecture and authority boundaries

The verified boundary is:

    ExtractionDraft       = untrusted AI interpretation
    TrustedBusinessData   = external customer/product reference data only
    ValidationFacts       = OpsFlow-local duplicate/history facts only
    ValidationEngine      = pure synchronous deterministic decision layer
    Application service   = orchestration, final locked transaction, and routing
    Persistence            = storage authority only

AI interprets; deterministic software decides.

No LLM or provider decides routing, customer identity, product identity,
duplicate status, inventory sufficiency, price acceptance, approval level, or
external side effects. TrustedBusinessData contains only externally sourced
customer and product reference records. ValidationFacts contains only the two
immutable OpsFlow-local facts required by validation. The engine is
synchronous, pure, deterministic, database-free, network-free, and
provider-free. The application owns orchestration, preconditions, final
locking, staleness checks, routing, and atomic writes. Persistence stores the
supplied immutable snapshots and does not decide business policy.

## Validation contracts and trusted data

The validation values are frozen, slotted, immutable records with strict tuple
boundaries and explicit invariants. Boolean fields are strict booleans; Decimal
policy values are finite, nonnegative, and reject floats, NaN, and infinity.
Supported currencies are an explicit, non-empty, unique tuple of uppercase
ASCII three-letter values in caller order. There are no hidden environment or
default policy values. Result and validated-data invariants preserve the
distinction between untrusted drafts, trusted data, issues, route, approval
level, and computed totals. Approval level is an in-memory ValidationResult
contract; the durable high-value signal is the
HIGH_VALUE_APPROVAL_REQUIRED issue. READY_FOR_APPROVAL remains the Order state
and no additional Order state is introduced.

Customer lookup uses an exact reference as authoritative. When no reference is
provided, it uses normalized exact name matching with Unicode casefold,
Unicode-whitespace splitting, and one ASCII space between words. It does not
use fuzzy matching, transliteration, semantic matching, embeddings, or an
LLM. Product lookup is exact and case-sensitive by SKU, with no description
fallback. The provider contract is asynchronous but deterministic and contains
no network, credentials, environment, clock, database, session, or OpsFlow
history behavior. The sandbox supplies synthetic customers and products,
rejects duplicate trusted identities, preserves deterministic candidate
ordering and positional product alignment, and rejects returned identities
that do not agree with the request.

For application local-fact construction, only exactly one total customer
candidate that is active supplies the canonical customer reference for
duplicate-PO lookup. An active candidate does not remove ambiguity created by
another exact-match candidate.

## Rule engine

The final engine uses the following stable order: customer, PO/local facts,
source duplicate, dates, currency, line presence, per-line checks in ascending
line index, and high-value approval. It does not stop at the first error;
independent checks continue, while prerequisite-dependent checks are
suppressed when their inputs are missing or invalid.

### Customer

CUSTOMER_REQUIRED, UNKNOWN_CUSTOMER, AMBIGUOUS_CUSTOMER, and
INACTIVE_CUSTOMER validate the presence, exact resolution, candidate
cardinality, and active status of the customer reference data. Ambiguous
candidate sets remain ambiguous regardless of the active status mix.

### PO and local facts

PO_NUMBER_REQUIRED, DUPLICATE_CUSTOMER_PO, and
DOCUMENT_ALREADY_PROCESSED validate the extracted PO and consume only the
application-supplied ValidationFacts. Duplicate customer+PO identity is not
inferred by the provider or engine.

### Dates

ORDER_DATE_REQUIRED, DELIVERY_DATE_REQUIRED, ORDER_DATE_IN_FUTURE,
DELIVERY_DATE_IN_PAST, and DELIVERY_BEFORE_ORDER_DATE validate required dates,
temporal bounds, and their ordering. Date comparisons are suppressed when the
required date prerequisite is absent.

### Currency

CURRENCY_REQUIRED, UNSUPPORTED_CURRENCY, and PRODUCT_CURRENCY_MISMATCH
validate required policy currency, supported currency membership, and trusted
product currency agreement.

### Lines, product, inventory, and pricing

ORDER_LINES_REQUIRED, SKU_REQUIRED, UNKNOWN_SKU, INACTIVE_SKU,
QUANTITY_REQUIRED, QUANTITY_NOT_POSITIVE, INVENTORY_UNAVAILABLE,
INSUFFICIENT_INVENTORY, SUBMITTED_PRICE_REQUIRED, SUBMITTED_PRICE_NEGATIVE,
CATALOGUE_PRICE_UNAVAILABLE, and PRICE_OUTSIDE_TOLERANCE validate line
presence, exact trusted SKU identity, product status, quantities, inventory,
submitted prices, catalogue prices, and tolerance. None inventory is
unavailable; known zero inventory is distinct and can be insufficient for a
positive quantity.

### High-value approval

HIGH_VALUE_APPROVAL_REQUIRED is a WARNING. It uses exact Decimal arithmetic
and an inclusive threshold. If no ERROR exists, the result remains
READY_FOR_APPROVAL with ELEVATED approval. Any ERROR routes to NEEDS_REVIEW
and produces no validated order data. Price tolerance checks use Decimal-only
arithmetic with inside, exact-boundary, and outside behavior; zero catalogue
price follows the approved explicit semantics. No float conversion or implicit
rounding occurs. Invalid draft business values never become trusted OrderLine
values.

## Persistence and migration

Migration 0003_phase5_extraction_snapshots follows 0002_phase2_persistence. It
uses an application-assigned snapshot UUID, order/source ownership, a required
JSONB payload, and an application-supplied timezone-aware created_at. It
defines a unique order_id/source_document_id pair, an order foreign key with
CASCADE, and a composite source ownership foreign key with CASCADE. It also
defines the lowercase 64-character SHA constraint, the approved document-type
constraint, the JSON-object constraint, and a non-unique source-SHA lookup
index.

The source-documents table has the redundant named unique id/order_id
constraint required by the composite ownership foreign key. There is no global
SHA uniqueness constraint and no approval_level persistence column. The ORM
model and migration agree. Downgrade removes snapshot indexes, constraints,
table, and then the source-document ownership dependency in reverse order.

## Snapshot serialization

The extraction snapshot workflow surface is immutable insert/read only. Its
payload has the exact strict JSON shape with explicit nulls, exact nested
source, line, and evidence keys, and no provider response, prompt, model,
raw-response, or API-key fields. Line and evidence array order is preserved.

Decimal values serialize as finite canonical fixed-point strings: insignificant
fractional zeroes are removed, exponent notation is not used, and signed zero
becomes the string 0. Dates use canonical YYYY-MM-DD strings. Deserialization
rejects wrong types, missing or extra keys, noncanonical decimals and dates,
invalid SHA/type values, and any unexpected provider fields. Relational columns
and the JSON source envelope must agree, and created_at must be timezone aware.
Invalid or missing business values remain representable as an ExtractionDraft;
they are not forced into trusted Order or OrderLine values during snapshot
mapping.

## Repository operations

Customer+PO duplicate lookup uses the exact canonical customer reference and
exact, case-sensitive PO string. It excludes only the current order; any other
order qualifies regardless of workflow state. Processed-source lookup excludes
only the exact current order/source pair. Another order with the same SHA
counts, and another source document under the same order with the same SHA also
counts. If canonical customer identity or PO is missing, the duplicate query
is suppressed, while the processed-source check still runs.

Validation issues are fully replaced in tuple order at positions 0..n-1; an
empty tuple clears the existing set. The final order read uses SELECT ...
FOR UPDATE. Repository helpers do not commit, invoke the engine or provider,
decide a route, or perform a state transition. Snapshot workflow operations
expose insertion and exact read, not snapshot update or delete. Graph
replacement preserves source-document rows and persists only the supplied
already-valid trusted order snapshot.

## Application transaction and routing

The verified application sequence is:

    initial DB reads
      -> rollback
      -> provider with no DB transaction
      -> local ValidationFacts read
      -> rollback
      -> engine with no DB transaction
      -> final session.begin()
      -> order row SELECT FOR UPDATE
      -> source/state/snapshot rechecks
      -> fresh ValidationFacts
      -> exact equality guard
      -> atomic writes
      -> one final commit

The provider is called once and the engine is called once. The engine is not
rerun and there is no general retry framework.

On the READY path, validated data is mandatory, application-owned line UUIDs
are created, trusted values are promoted, and the order transitions EXTRACTED
to VALIDATED to READY_FOR_APPROVAL. On the REVIEW path, no promotion occurs,
invalid AI values are not copied into the trusted graph, the existing trusted
graph is preserved, and the order transitions EXTRACTED to VALIDATED to
NEEDS_REVIEW.

## Replay, concurrency, and staleness

An existing identical snapshot is classified as a replay. A differing
snapshot or envelope is classified as a conflict, with no second snapshot.
The order-row lock serializes the ordinary same-order final-write path. Final
state, source ownership, canonical SHA, document type, snapshot, and local-fact
checks prevent stale writes. Unrelated integrity failures are not broadly
reclassified, and no speculative distributed-lock or general concurrency
framework was added.

Both READY and REVIEW candidates use the same local-fact staleness guard. If
the facts observed by the engine differ from the fresh locked facts, the
application raises the safe validation-data-changed error, performs no writes,
does not rerun the engine, and does not retry automatically. Customer
candidate ambiguity is included in the canonical identity used for both fact
reads.

## Atomicity evidence

M5E failure-injection coverage exercised representative failures after
extraction snapshot insertion, validation-issue replacement, order scalar/state
persistence, trusted graph replacement, and audit insertion. PostgreSQL-backed
tests proved that each failure rolls back the complete Phase 5 transaction,
leaving no partial snapshot, new issue set, scalar promotion, trusted line
graph, state change, or Phase 5 audit event. Existing trusted fields and
issues remain unchanged when a final transaction fails.

## Audit events

The final transaction records exactly three events in chronological order:

1. EXTRACTION_SNAPSHOT_RECORDED
2. ORDER_VALIDATED
3. ORDER_NEEDS_REVIEW or ORDER_READY_FOR_APPROVAL

The actor is system. Caller-supplied recorded_at is used, followed by
recorded_at + 1 microsecond and recorded_at + 2 microseconds. Elevated
approval has its distinct deterministic description. No raw provider data,
source text, notes, evidence, or credentials appear in the descriptions.

## Privacy, cost, and side effects

Safe application error categories distinguish operational provider failure,
invalid trusted provider data, replay, conflict, stale validation data, and
other precondition failures without exposing raw provider exception text,
provider payloads, source text, notes, evidence, credentials, API keys, SDK
objects, or SQL. Provider failures and invalid provider data are application
errors, not fabricated ValidationIssue values.

The mandatory Phase 5 path is network-free for business data, uses synthetic
test data, and requires no live LLM, ERP, CRM, email, Slack, or n8n mutation.
The mandatory development and CI path remains $0. No external business
provider call is required by the tests.

## Regression and scope

The audit found no unauthorized public validation API, UI, n8n workflow,
Odoo/HubSpot integration, Gmail/Slack integration, stock reservation, Phase 6
review or approval action, Phase 10 retry framework, generic Unit of Work,
rule DSL, event sourcing, service locator, caching layer, speculative
integration framework, or Phase 5 runtime dependency addition. Phase 1–4
regression behavior remained green. No production deployment is implied.

## Verification evidence

The final audited candidate was:

    b0622a0a9e734675516ccbe9ee76a5ac34914961

Exact-head CI evidence came from run 35454271026:

- Python: 3.12.14
- PostgreSQL: 16.15
- migration head: 0003_phase5_extraction_snapshots
- full tests: 764 passed
- coverage: 92.68%
- Backend: SUCCESS
- Frontend: SUCCESS
- Secret scan: SUCCESS
- Ruff: PASS
- Ruff format: 115 files already formatted
- mypy: PASS — 43 source files
- build: PASS

Final focused local read-only audit verification recorded:

- validation unit: 85 passed
- domain unit: 191 passed
- application unit: 50 passed
- persistence unit: 50 passed
- Ruff: PASS
- Ruff format: 115 files already formatted
- mypy: PASS — 43 source files
- build: PASS
- git diff --check: PASS

Local PostgreSQL/Docker was unavailable during the final read-only audit.
PostgreSQL-backed evidence came from exact-head GitHub CI; no local integration
test pass is claimed here.

## Audit-document self-review

This artifact preserves the historical M5F-001 MEDIUM finding and does not
claim that the first audit was finding-free. It records the exact remediation,
candidate, CI run, test counts, coverage, migration head, and local PostgreSQL
limitation. It does not claim an approval-level database field, global source
SHA uniqueness, a public Phase 5 API, LLM routing, live external integrations,
production deployment, or Phase 6 work. All relative links in the governing
source list resolve to repository paths.

## Final audit decision

The remediated Phase 5 implementation passes the fresh full read-only audit.
The final finding ledger is zero at every severity. The audit is ready for
durable recording and final status closeout.
