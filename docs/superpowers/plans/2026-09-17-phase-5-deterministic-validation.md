# Phase 5 — Deterministic Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task.
> Single-agent sequential execution is mandatory for this project.

**Status:** Implementation plan only. No Phase 5 production implementation,
tests, migration, dependency, status change, audit file, API, or PR is created
by this document.

**Planning baseline:** `phase/5-deterministic-validation` at
`1356f194ff817fd3d30292c4f3ddae4e7a93dc17`, two commits ahead of
`84de8ed70b745bf987227953495320deccee94fe` and zero commits behind it. The
approved M5A design is the second Phase 5 commit at that exact current SHA.

**Goal:** Implement the approved deterministic trust boundary that validates
one untrusted `ExtractionDraft` against trusted business reference data,
OpsFlow-local `ValidationFacts`, explicit policy/context, then atomically
records the snapshot/issues and routes the `Order` to `NEEDS_REVIEW` or
`READY_FOR_APPROVAL`.

**Architecture:** Keep a synchronous, pure `ValidationEngine` separate from
the external-reference-data `BusinessDataProvider` and the immutable local
`ValidationFacts` contract. Persist the untrusted extraction snapshot
separately. The application service owns the final transaction, trusted-data
promotion, state transitions, and audit events.

**Tech Stack:** Python 3.12, standard-library `dataclasses`/`Decimal`/`date`/
`Enum`/`Protocol`, SQLAlchemy 2 async, PostgreSQL 16, Alembic, pytest, Ruff,
mypy.

**Spec:**
`docs/superpowers/specs/2026-09-17-phase-5-deterministic-validation-design.md`

---

## File Map

Lock this map before implementation. Every file has one primary responsibility;
existing Phase 0–4 files are modified only where the approved Phase 5 contract
requires an extension.

### Planned creates

- `src/opsflow/validation/__init__.py` — exports the Phase 5 value contracts
  and the pure engine callable.
- `src/opsflow/validation/models.py` — immutable validation routes,
  approval levels, facts, trusted reference records, promotable records, and
  result types.
- `src/opsflow/validation/policy.py` — immutable explicit policy and its
  structural validation.
- `src/opsflow/validation/business_data.py` — external reference-data
  protocol, lookup request, customer-name normalizer, and provider-result
  contract validation.
- `src/opsflow/validation/sandbox.py` — deterministic synthetic provider with
  only customer/product reference data.
- `src/opsflow/validation/engine.py` — one pure rule evaluator and focused
  helpers; no class-per-rule design.
- `src/opsflow/application/validation.py` — internal application validation
  operation, preflight, orchestration, final transaction, and result type.
- `alembic/versions/0003_phase5_extraction_snapshots.py` — the reviewed
  extraction-snapshot schema migration.
- `tests/unit/validation/test_models.py` — validation value-contract tests.
- `tests/unit/validation/test_policy.py` — policy validation tests.
- `tests/unit/validation/test_business_data.py` — provider protocol and
  lookup-request contract tests.
- `tests/unit/validation/test_sandbox.py` — sandbox lookup behavior tests.
- `tests/unit/validation/test_engine.py` — pure rule-matrix tests.
- `tests/unit/application/test_validation.py` — application-only behavior
  tests that do not duplicate PostgreSQL integration assertions.
- `tests/integration/test_phase5_persistence.py` — migration, snapshot, and
  focused repository PostgreSQL coverage.
- `tests/integration/test_phase5_application.py` — atomic validation and
  routing PostgreSQL coverage.

### Planned modifications

- `src/opsflow/domain/order.py` — add only
  `Order.promote_validated_data(...)`; retain all existing state values,
  transitions, and invariants.
- `src/opsflow/domain/__init__.py` — export the promotion-related domain
  surface only if required by the existing import convention.
- `src/opsflow/application/__init__.py` — expose the internal validation
  operation only if current package exports require it; add no HTTP surface.
- `src/opsflow/application/errors.py` — add safe Phase 5 application error
  categories while reusing the existing `OrderNotFoundError`.
- `src/opsflow/persistence/models.py` — add
  `ExtractionSnapshotModel` and the narrow source-document ownership
  constraint.
- `src/opsflow/persistence/mappers.py` — add the typed snapshot record and
  strict deterministic draft/payload mappings.
- `src/opsflow/persistence/repositories.py` — add transaction-owned snapshot,
  local-fact, issue, lock, state, and trusted-graph operations.
- `src/opsflow/persistence/__init__.py` — export new persistence types only
  where current package style calls for it.
- `tests/unit/domain/test_order.py` — promotion behavior and invariant tests.
- `tests/unit/application/test_errors.py` — safe error hierarchy/message
  tests.
- `tests/unit/persistence/test_models.py` — ORM shape/constraint metadata
  tests where useful.
- `tests/unit/persistence/test_mappers.py` — snapshot serialization and
  mapper tests; retain existing Phase 2 mapping coverage.
- Existing integration tests — only extend them when a Phase 5 regression
  belongs to an already-owned Phase 2 contract; do not duplicate the new
  focused integration modules.

### Planned status files

- `README.md`
- `docs/roadmap/project-roadmap.md`

These files are modified only by separate status-only commits during the
M5B–M5E closeout protocol, never by an implementation task before its
milestone passes review and CI.

### Explicitly not in the file map

No public validation endpoint, API schema, UI, n8n workflow, Odoo/HubSpot/
Gmail/Slack adapter, Phase 10 reliability framework, dependency change,
status edit during an implementation task, audit file, or future-phase
implementation. The two planned status files are restricted to the closeout
protocol below.

## Global Constraints

- The approved design is authoritative. If implementation reveals a genuine
  design contradiction, stop and report it instead of silently changing the
  design.
- AI never decides customer/product identity, duplicate status, pricing,
  inventory sufficiency, approval level, routing, or side effects.
- `validation.engine.validate(...)` is synchronous, pure, deterministic,
  database-free, network-free, provider-free, and clock-free. It must not
  import or call SQLAlchemy, FastAPI, a provider, a network client, an
  environment reader, `date.today()`, `datetime.now()`, randomness, or UUID
  generation.
- `BusinessDataProvider` owns only externally sourced customer/product
  reference data: customer candidates and active status, exact products and
  active status, catalogue price, product currency, and inventory.
- `ValidationFacts` is a separate immutable value containing the two local
  facts `duplicate_customer_po` and `document_already_processed`. Focused
  OpsFlow persistence repository functions are their sole authority. Neither
  field is part of `TrustedBusinessData`.
- No provider receives `order_id`, PO history, source SHA history, or another
  value solely needed for an OpsFlow-local lookup. The sandbox has no local PO
  set or processed-source-hash set.
- Matching is exact or the specified normalized-exact customer-name match.
  There is no fuzzy, semantic, transliteration, embedding, or LLM matching.
- Quantities and prices use finite `Decimal` values only. No float arithmetic,
  currency-scale quantization, or implicit rounding is introduced.
- All date-sensitive behavior uses explicit `ValidationContext.evaluation_date`;
  no system clock is read by the engine.
- High-value classification is a non-blocking `WARNING` plus
  `ApprovalLevel.ELEVATED`, not a review failure. The persisted
  `HIGH_VALUE_APPROVAL_REQUIRED` issue is the durable Phase 5 signal. No
  `approval_level` column is added; the order remains
  `READY_FOR_APPROVAL`.
- Phase 1 `Order` and `OrderLine` invariants are not weakened. An invalid
  `ExtractionDraft` is never constructed as an `OrderLine` and never copied
  into trusted `Order`/`order_lines` fields.
- The only validation state paths are the existing
  `EXTRACTED → VALIDATED → NEEDS_REVIEW` and
  `EXTRACTED → VALIDATED → READY_FOR_APPROVAL` transitions.
- One immutable extraction snapshot is allowed per `(order_id,
  source_document_id)`. Exact replay and conflicting replay are application
  outcomes; the source SHA is not globally unique.
- Persist only the typed draft payload and safe deterministic issue/audit
  values. Never persist raw provider responses, prompts, API keys, provider
  SDK objects, provider-internal fields, or raw source content.
- Before either route commits, the final locked transaction re-queries both
  local facts and aborts with a safe changed-data/race error if they differ
  from the engine inputs. It does not rerun the engine inside persistence and
  does not add a general retry/concurrency framework.
- No public API, UI, n8n, Odoo, HubSpot, Gmail, Slack, external mutation,
  inventory reservation, human approval action, Phase 6 edit flow, or future
  integration is added.
- Do not add a generic rule framework, DSL, class-per-rule plugin system,
  Unit of Work abstraction, service locator, event-sourcing subsystem,
  caching layer, or generic integration framework.
- Do not add a runtime dependency unless the approved design is genuinely
  impossible with the committed stack. The mandatory automated path remains
  synthetic, network-free, and costs `$0`.

## Implementation Order and Review Gates

Implement tasks strictly in numerical order, one task at a time. Each task
ends with its focused RED/GREEN or characterization verification, relevant
regression checks, diff inspection, and one coherent commit. At the end of
M5B, M5C, M5D, and M5E, push the exact candidate HEAD and require successful
Backend, Frontend, and Secret scan jobs, then obtain independent ChatGPT
review. When that review passes without an architecture, scope, or product
decision, continue automatically through the applicable status-only closeout,
its exact-head CI, and the next approved milestone. Ask for explicit user
direction only when the approved architecture must change, scope materially
changes, a new product-level decision is required, or independent review
identifies a decision not resolved by the approved design.

The task count is 11:

- M5B: Tasks 1–4.
- M5C: Tasks 5–7.
- M5D: Tasks 8–9.
- M5E: Tasks 10–11.
- M5F: an independent-audit boundary, not an implementation task in this
  plan.

## M5B — Trusted Business Data, Policy & Rule Engine

M5B is memory-only. It must not modify persistence, migrations, application
orchestration, state transitions, or external systems.

### Task 1 — Add immutable validation value contracts

**Files:** Create `src/opsflow/validation/models.py`,
`src/opsflow/validation/__init__.py`, and
`tests/unit/validation/test_models.py`.

**Interfaces locked by this task:**

```python
class ValidationRoute(Enum):
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"


class ApprovalLevel(Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"


@dataclass(frozen=True, slots=True)
class ValidationContext:
    evaluation_date: date


@dataclass(frozen=True, slots=True)
class ValidationFacts:
    duplicate_customer_po: bool
    document_already_processed: bool


@dataclass(frozen=True, slots=True)
class TrustedCustomer:
    reference: str
    name: str
    active: bool


@dataclass(frozen=True, slots=True)
class TrustedProduct:
    sku: str
    description: str | None
    active: bool
    currency: str
    catalogue_price: Decimal | None
    available_quantity: Decimal | None


@dataclass(frozen=True, slots=True)
class TrustedBusinessData:
    customer_candidates: tuple[TrustedCustomer, ...]
    products_by_line: tuple[TrustedProduct | None, ...]


@dataclass(frozen=True, slots=True)
class BusinessDataLookupRequest:
    customer_reference: str | None
    customer_name: str | None
    skus: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class ValidatedOrderLine:
    sku: str
    description: str | None
    quantity: Decimal
    submitted_price: Decimal
    trusted_catalogue_price: Decimal


@dataclass(frozen=True, slots=True)
class ValidatedOrderData:
    customer_reference: str
    po_number: str
    order_date: date
    requested_delivery_date: date
    currency: str
    lines: tuple[ValidatedOrderLine, ...]


@dataclass(frozen=True, slots=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]
    route: ValidationRoute
    approval_level: ApprovalLevel
    order_total: Decimal | None
    validated_order_data: ValidatedOrderData | None
```

**Steps:**

1. Write focused tests for frozen/slotted records, exact enum values, tuple
   collection requirements, strict booleans in `ValidationFacts`, finite
   nonnegative trusted Decimal values, and the required non-null fields of
   promotable data.
2. Run `uv run pytest tests/unit/validation/test_models.py -q --no-cov` and
   confirm the RED failure is caused by the missing validation package.
3. Implement only the value records and structural invariants. Keep
   `TrustedBusinessData` limited to external customer/product reference
   records; do not add local history fields or persistence imports.
4. Add `ValidationResult` invariants for immutable issue order, enum types,
   optional total/data shape, and the rule that blocking results cannot carry
   promotable data. Leave route/approval derivation to the engine.
5. Rerun the focused tests, then run the existing domain suite to confirm the
   Phase 1 records are unchanged.
6. Inspect imports and the diff, then commit:
   `feat: add Phase 5 validation contracts`.

### Task 2 — Add explicit validation policy

**Files:** Create `src/opsflow/validation/policy.py` and
`tests/unit/validation/test_policy.py`.

**Interface locked by this task:**

```python
@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    supported_currencies: tuple[str, ...]
    price_tolerance_fraction: Decimal
    high_value_threshold: Decimal
```

**Steps:**

1. Write RED tests for a non-empty stable tuple of unique `[A-Z]{3}` currency
   codes, caller-order preservation, finite nonnegative Decimal tolerance and
   threshold, and rejection of empty/duplicate/malformed currencies, floats,
   NaN, infinities, negative values, lists, and mutable replacements.
2. Run the focused policy test and confirm the failure is for the absent
   contract, not an unrelated repository failure.
3. Implement `ValidationPolicy.__post_init__` with strict runtime type checks;
   do not read settings or environment variables and do not hide defaults in
   the engine.
4. Run the policy tests, the model tests, and Ruff on the new package. Commit:
   `feat: add explicit Phase 5 validation policy`.

### Task 3 — Add the external business-data protocol and sandbox

**Files:** Create `src/opsflow/validation/business_data.py`,
`src/opsflow/validation/sandbox.py`,
`tests/unit/validation/test_business_data.py`, and
`tests/unit/validation/test_sandbox.py`.

**Interfaces locked by this task:**

```python
class TrustedBusinessDataContractError(ValueError): ...


def normalize_customer_name(value: str) -> str: ...


class BusinessDataProvider(Protocol):
    async def get_validation_data(
        self,
        request: BusinessDataLookupRequest,
    ) -> TrustedBusinessData: ...


def validate_trusted_business_data(
    draft: ExtractionDraft,
    data: TrustedBusinessData,
) -> None: ...


@dataclass(frozen=True, slots=True)
class SandboxBusinessDataProvider:
    customers: tuple[TrustedCustomer, ...]
    products: tuple[TrustedProduct, ...]

    async def get_validation_data(
        self,
        request: BusinessDataLookupRequest,
    ) -> TrustedBusinessData: ...
```

`validate_trusted_business_data` raises
`TrustedBusinessDataContractError` for duplicate exact identities, bad trusted
records, non-canonical ordering, or a `products_by_line` length that does not
equal the draft line count. The application translates that error to its safe
invalid-provider category.

**Steps:**

1. Write RED tests for request shape, exact customer-reference precedence,
   normalized customer-name matching (`casefold → Unicode-whitespace split →
   single ASCII-space join`), exact case-sensitive SKU matching, deterministic
   candidate/SKU ordering, and no description fallback.
2. Add tests proving duplicate exact customer references and exact SKUs are
   rejected as trusted configuration errors, while duplicate normalized names
   are returned for engine ambiguity handling.
3. Add tests distinguishing `available_quantity=None` from
   `Decimal("0")`, inactive records from unknown records, and repeated equal
   requests from a deterministic equal result.
4. Run the two focused suites and confirm RED is limited to missing provider
   behavior.
5. Implement the protocol, normalization helper, provider-result contract
   validator, and frozen synthetic provider. Its constructor must accept only
   `customers` and `products`; it must not accept order IDs, PO sets, source
   hashes, environment settings, credentials, or a clock.
6. Run sandbox, business-data, and validation-model tests. Inspect the module
   imports for network/provider SDK access and commit:
   `feat: add sandbox business data provider`.

### Task 4 — Implement the pure deterministic engine

**Files:** Create `src/opsflow/validation/engine.py` and
`tests/unit/validation/test_engine.py`.

**Public engine callable:**

```python
def validate(
    draft: ExtractionDraft,
    trusted_business_data: TrustedBusinessData,
    validation_facts: ValidationFacts,
    policy: ValidationPolicy,
    context: ValidationContext,
) -> ValidationResult: ...
```

The module-level `validate` function is the complete `ValidationEngine`; it is
stateless and has no constructor or injected repository/provider.

**Steps:**

1. Write focused RED tests for the complete approved rule matrix. Assert each
   rule code, severity, exact zero-based field path, JSON-safe expected/actual
   representation, explanation, and stable issue order. Cover customer
   required/unknown/ambiguous/inactive, PO required/duplicate, source SHA
   duplicate, date rules, currency rules, empty lines, SKU rules, quantity and
   inventory rules, price rules, product currency, tolerance boundaries, and
   high-value warning.
2. Add tests for the exact dependency gates: duplicate PO only after one
   customer candidate and a present PO; product-dependent checks only after an
   exact product; inventory only after positive quantity; tolerance only after
   nonnegative submitted price, catalogue price, usable order currency, and
   matching product currency; missing dates produce required issues but no
   comparison issues.
3. Add tests proving independent checks continue after unrelated failures,
   line rules run in ascending index order, and multiple simultaneous issues
   do not stop at the first failure.
4. Add tests for Decimal-only arithmetic, zero catalogue price, missing versus
   known-zero inventory, exact/on/outside tolerance, total computability,
   threshold just below and exactly at the inclusive boundary, and standard
   versus elevated approval.
5. Add tests proving any `ERROR` derives `NEEDS_REVIEW` and
   `validated_order_data is None`; warning/info-only high-value output derives
   `READY_FOR_APPROVAL`, `ApprovalLevel.ELEVATED`, and complete promotable
   trusted line data. Assert `HIGH_VALUE_APPROVAL_REQUIRED` remains a warning.
6. Add the five-input determinism test: two equal
   `ExtractionDraft`/`TrustedBusinessData`/`ValidationFacts`/
   `ValidationPolicy`/`ValidationContext` values produce equal complete
   `ValidationResult` values, including issues, total, approval, route, and
   promotable data.
7. Implement one engine module with focused helpers for identity resolution,
   issue construction, per-line checks, total calculation, and result
   construction. Preserve the exact matrix order; do not create one class per
   rule and do not call a repository/provider.
8. Run the focused engine suite, all M5B unit suites, and the domain suite.
   Inspect `engine.py` imports/source for database, network, clock, random,
   environment, provider SDK, FastAPI, and UUID boundaries. Commit:
   `feat: implement deterministic validation engine`.

**M5B exit gate:** The provider-neutral records, explicit policy/context,
sandbox, and complete pure engine work in memory with focused unit coverage.
No database, migration, application service, state transition, or external
integration is included.

## M5C — Extraction Snapshot Persistence

M5C adds only persistence primitives. It must not add the complete application
validation operation or route an order.

### Task 5 — Add migration 0003 and the snapshot ORM model

**Files:** Create `alembic/versions/0003_phase5_extraction_snapshots.py`;
modify `src/opsflow/persistence/models.py` and
`src/opsflow/persistence/__init__.py`; add migration/schema assertions to
`tests/integration/test_phase5_persistence.py` and, where useful, metadata
assertions to `tests/unit/persistence/test_models.py`.

**Migration contract locked by this task:**

```python
revision = "0003_phase5_extraction_snapshots"
down_revision = "0002_phase2_persistence"
```

Create the narrow redundant source ownership constraint
`uq_source_documents_id_order_id` on `(source_documents.id,
source_documents.order_id)` before creating `extraction_snapshots`. The new
table has application-assigned UUID `id`, required `order_id`, required
`source_document_id`, lowercase `source_sha256`, `source_document_type`,
required JSONB `payload`, and application-supplied timezone-aware
`created_at`. Add the named constraints/indexes from the design:

- `uq_extraction_snapshots_order_source` on `(order_id,
  source_document_id)`;
- the `order_id` foreign key to `orders.id` with `ON DELETE CASCADE`;
- the composite `(source_document_id, order_id)` foreign key to
  `(source_documents.id, source_documents.order_id)` with `ON DELETE CASCADE`;
- `ck_extraction_snapshots_sha256` for exactly 64 lowercase ASCII hex chars;
- `ck_extraction_snapshots_document_type` for exactly `EMAIL_BODY`, `PDF`,
  `XLSX`, `CSV`, or `FORM`;
- `ck_extraction_snapshots_payload_object` using
  `jsonb_typeof(payload) = 'object'`;
- non-unique `ix_extraction_snapshots_source_sha256` on `source_sha256`.

Do not add a global SHA uniqueness constraint or an approval-level column.

**Steps:**

1. Write PostgreSQL assertions for the clean Phase 2 head upgrading to
   `0003_phase5_extraction_snapshots`, the migration revision chain, table
   columns/nullability, all named constraints/indexes, the two foreign-key
   delete actions, and the absence of a global SHA unique key. Confirm the
   existing Phase 2 schema/data remains migratable.
2. Run the migration/schema test against the current database and confirm RED
   identifies the absent revision/table rather than changing existing tests.
3. Implement the revision explicitly with Alembic operations. Create the
   source composite unique constraint first, then the snapshot table and
   index. Implement downgrade in reverse dependency order: drop the snapshot
   table, then drop `uq_source_documents_id_order_id`.
4. Add `ExtractionSnapshotModel` with the exact relational envelope and no
   server-owned identity/time values that would bypass application-supplied
   persistence data. Keep provider/raw-response fields absent.
5. Run the migration test from an empty/Phase 2 schema path and the existing
   Phase 2 integration suite. Inspect generated SQL/schema intent manually;
   do not rely on an unreviewed autogenerate result. Commit:
   `feat: persist Phase 5 extraction snapshots`.

### Task 6 — Add strict deterministic snapshot serialization and mapping

**Files:** Modify `src/opsflow/persistence/mappers.py` and
`tests/unit/persistence/test_mappers.py`.

**Interfaces locked by this task:**

```python
@dataclass(frozen=True, slots=True)
class PersistedExtractionSnapshot:
    id: UUID
    order_id: UUID
    source_document_id: UUID
    source_sha256: str
    source_document_type: SourceDocumentType
    draft: ExtractionDraft
    created_at: datetime


def extraction_draft_to_payload(
    draft: ExtractionDraft,
) -> dict[str, object]: ...


def extraction_draft_from_payload(payload: object) -> ExtractionDraft: ...


def extraction_snapshot_to_model(
    snapshot: PersistedExtractionSnapshot,
) -> ExtractionSnapshotModel: ...


def extraction_snapshot_from_model(
    row: ExtractionSnapshotModel,
) -> PersistedExtractionSnapshot: ...
```

**Steps:**

1. Write RED round-trip tests for every required top-level key, explicit nulls,
   source envelope, ordered lines/evidence, ISO dates, and canonical finite
   fixed-point Decimal strings. Assert `Decimal("-0")` serializes as `"0"`
   and no exponent notation is emitted.
2. Add rejection tests for missing/extra keys at every object level, wrong
   scalar types, non-canonical Decimal/date strings, mutable collections,
   source envelope/column disagreement, wrong source type/hash, and provider,
   prompt, UUID, timestamp, or raw-response fields.
3. Implement explicit ordinary JSON-safe dict/list/string/null construction;
   preserve text and array order exactly. Parse only canonical strings and
   rebuild `ExtractionDraft`, never `OrderLine`, so invalid extracted
   quantities/prices remain representable as untrusted data.
4. Implement the typed relational-envelope mapper with aware `created_at`,
   lowercase SHA, source-document type, and payload agreement checks. Keep
   object-key ordering out of equality semantics while preserving array order.
5. Run mapper tests, existing persistence mapper tests, and Ruff/mypy. Commit:
   `feat: add deterministic extraction snapshot mapping`.

### Task 7 — Add transaction-owned snapshot and local-fact repositories

**Files:** Modify `src/opsflow/persistence/repositories.py`,
`src/opsflow/persistence/__init__.py`, and add focused assertions to
`tests/integration/test_phase5_persistence.py`.

**Interfaces locked by this task:**

```python
async def insert_extraction_snapshot(
    session: AsyncSession,
    snapshot: PersistedExtractionSnapshot,
) -> None: ...


async def get_extraction_snapshot(
    session: AsyncSession,
    order_id: UUID,
    source_document_id: UUID,
) -> PersistedExtractionSnapshot | None: ...


async def has_customer_po_duplicate(
    session: AsyncSession,
    customer_reference: str,
    po_number: str,
    *,
    exclude_order_id: UUID,
) -> bool: ...


async def has_processed_source_sha(
    session: AsyncSession,
    source_sha256: str,
    *,
    exclude_order_id: UUID,
    exclude_source_document_id: UUID,
) -> bool: ...


async def build_validation_facts(
    session: AsyncSession,
    *,
    order_id: UUID,
    source_document_id: UUID,
    canonical_customer_reference: str | None,
    po_number: str | None,
    source_sha256: str,
) -> ValidationFacts: ...


async def replace_validation_issues(
    session: AsyncSession,
    order_id: UUID,
    issues: tuple[ValidationIssue, ...],
) -> None: ...


async def get_order_for_update(
    session: AsyncSession,
    order_id: UUID,
) -> PersistedOrder | None: ...


async def update_order_snapshot(session: AsyncSession, order: Order) -> None: ...


async def replace_order_graph(session: AsyncSession, order: Order) -> None: ...
```

**Steps:**

1. Write PostgreSQL RED tests for snapshot insert/read, pair uniqueness,
   source ownership, order/source cascade, and no update/delete repository
   operation. Use the existing `asyncio.run`, `Settings().database_url`, and
   `AsyncSession` conventions; do not add a generic fixture framework.
2. Add RED tests proving `has_customer_po_duplicate` compares the exact
   canonical customer reference plus exact PO, considers any persisted order,
   and excludes the current order. Add tests proving
   `has_processed_source_sha` compares lowercase snapshot SHA and excludes
   only the current `(order_id, source_document_id)` pair, so another order or
   another source remains a qualifying prior record.
3. Add tests for `build_validation_facts`: absent canonical customer/PO makes
   the PO fact false, and both booleans are returned as an immutable
   `ValidationFacts` with no ORM/query objects.
4. Add tests for issue replacement positions `0..n-1`, locked order reads, and
   trusted graph replacement preserving source documents and ordered lines.
   Verify every repository function flushes as needed but never commits.
5. Implement narrow queries with explicit ordering and a shared internal
   complete-order loader. Use `SELECT ... FOR UPDATE` only in
   `get_order_for_update`; preserve the existing `get_order` behavior.
6. Implement issue replacement and graph/state helpers so the caller owns the
   transaction. Confirm the snapshot repository exposes insertion/read only,
   not update or delete.
7. Run focused persistence integration tests and the full Phase 2 persistence
   regression subset. Inspect the diff and commit:
   `feat: add Phase 5 validation persistence operations`.

**M5C exit gate:** Migration 0003, strict snapshot mapping, immutable snapshot
semantics, focused local-fact queries, issue replacement, row locking, and
trusted graph primitives exist and are PostgreSQL-tested. Complete validation
orchestration is still absent.

## M5D — Validation Application Service & Atomic Routing

M5D is the only milestone that composes the pure engine with the provider and
repositories. There is no HTTP endpoint.

### Task 8 — Add narrow validated-order promotion and safe application errors

**Files:** Modify `src/opsflow/domain/order.py`,
`src/opsflow/domain/__init__.py`, `src/opsflow/application/errors.py`, and
`tests/unit/domain/test_order.py`, `tests/unit/application/test_errors.py`.

**Interfaces locked by this task:**

```python
def Order.promote_validated_data(
    self,
    data: ValidatedOrderData,
    line_ids: tuple[UUID, ...],
) -> Order: ...
```

The method requires `self.state is OrderState.EXTRACTED`, requires exactly one
application-created UUID per validated line, constructs Phase 1-valid
`OrderLine` records from trusted/promotable values, preserves `id`,
`source_documents`, and current state, and does not transition state. It
re-validates by constructing a new immutable `Order` snapshot. The domain
module may use a deferred/type-checking import for the Phase 5 value type so
the existing standard-library domain import boundary remains free of
SQLAlchemy/FastAPI/provider concerns.

Add safe application errors with stable categories and messages:

- reuse `OrderNotFoundError` for a missing order;
- `SourceDocumentNotFoundError` — source document is not present;
- `SourceOwnershipError` — source document is not owned by the order;
- `SourceIdentityMismatchError` — draft SHA/type does not match the source;
- `OrderValidationStateError` — order is not `EXTRACTED`;
- `SnapshotReplayError` — identical order/source snapshot already exists;
- `SnapshotConflictError` — existing order/source snapshot differs;
- `ValidationFactsChangedError` — local facts changed before commit;
- `InvalidTrustedDataError` — provider returned invalid contract data;
- `BusinessDataProviderError` — provider operation failed, with no raw
  provider exception, credentials, payload, or source text in its message.

**Steps:**

1. Write RED domain tests for promotion from `EXTRACTED`, rejection from all
   other states, exact line-ID count/type, preservation of order/source/state,
   replacement of trusted fields/lines, and rejection through existing
   `OrderLine` invariants.
2. Write RED error tests asserting HTTP independence, safe stable messages,
   and reuse of the existing `OrderNotFoundError` instead of a duplicate.
3. Run the focused tests and confirm failures identify the missing operation
   and error categories.
4. Implement the narrow domain method and application errors. Do not add a
   new state, alter `transition_to`, alter `CreateOrderInput`, or permit an
   invalid extraction line to cross into the domain.
5. Run the focused domain/application suites and the existing transition suite.
   Commit: `feat: add validated order promotion`.

### Task 9 — Implement the internal application validation operation

**Files:** Create `src/opsflow/application/validation.py`; modify
`src/opsflow/application/__init__.py` only if needed for current exports; add
`tests/unit/application/test_validation.py` and
`tests/integration/test_phase5_application.py` coverage.

**Interfaces locked by this task:**

```python
@dataclass(frozen=True, slots=True)
class ValidationApplicationResult:
    order: Order
    validation_result: ValidationResult
    snapshot_id: UUID


async def validate_order(
    session: AsyncSession,
    order_id: UUID,
    source_document_id: UUID,
    draft: ExtractionDraft,
    business_data_provider: BusinessDataProvider,
    policy: ValidationPolicy,
    context: ValidationContext,
    recorded_at: datetime,
) -> ValidationApplicationResult: ...
```

`recorded_at` is required to be timezone-aware and is the application-supplied
timestamp for the persistence/audit operation. The service allocates snapshot,
line, and audit UUIDs outside the pure engine.

**Required sequence and transaction strategy:**

1. Perform the initial database preflight reads on the supplied session: load
   the order, resolve and verify source-document ownership, verify the draft
   SHA/type identity, require state `EXTRACTED`, and check the existing
   `(order_id, source_document_id)` snapshot for replay/conflict. A missing
   order raises the existing `OrderNotFoundError`; missing source, ownership,
   source identity, and state failures raise their safe application errors.
2. Immediately after those initial reads, execute `await session.rollback()`.
   This closes the SQLAlchemy-autobegun initial read transaction before any
   provider work. No provider/network call may occur while it is open.
3. Call `business_data_provider.get_validation_data(...)` exactly once with a
   `BusinessDataLookupRequest` containing only draft customer identity and
   ordered line SKUs. During this call no database transaction is open on the
   supplied session. Validate the returned `TrustedBusinessData` safely and
   translate contract or operational provider failures without leaking raw
   provider details.
4. After the provider returns, perform the focused OpsFlow-local
   `ValidationFacts` reads. For the duplicate PO lookup, pass a canonical
   reference only when the trusted data has exactly one active customer
   candidate and the draft PO is present. Unknown, ambiguous, inactive, or
   missing identity yields a false PO fact; the processed-SHA lookup remains
   repository-owned. These reads may autobegin a second short read
   transaction.
5. Immediately after the local-fact reads, execute `await session.rollback()`
   again. This closes the second read transaction before pure validation; the
   engine must not run while local-fact database work remains open.
6. Call the synchronous five-input `validation.engine.validate(...)` exactly
   once. During engine execution no database transaction is open and no
   provider/network call occurs.
7. Start the single final `async with session.begin()` write transaction. Lock
   the order row with `get_order_for_update`, then re-check order state, source
   ownership/identity, and pair snapshot replay/conflict conditions.
8. Re-query both local facts inside this locked transaction using the same
   focused repository functions. Compare the fresh immutable value with the
   facts used by the engine. If different, raise `ValidationFactsChangedError`
   uniformly for review and ready results; the context manager rolls back and
   the caller may retry later. Never rerun the engine in persistence or
   silently commit stale facts.
9. Insert the immutable snapshot, replace current validation issues in result
   order, and on the ready path only call `Order.promote_validated_data(...)`
   with application-created line UUIDs. On the review path, update only the
   state snapshot and preserve existing trusted fields/lines.
10. Apply `transition_to(VALIDATED)` followed by the result route transition.
    Persist the state/graph without repository commits. Add audit events in
    exact order with actor `system`: `EXTRACTION_SNAPSHOT_RECORDED`,
    `ORDER_VALIDATED`, then either `ORDER_NEEDS_REVIEW` or
    `ORDER_READY_FOR_APPROVAL`. Use the exact design descriptions; for an
    elevated ready result use `Deterministic validation passed; elevated
    approval is required.`
11. Commit once through the final transaction context and return the final
    immutable order, result, and snapshot ID only after commit succeeds. Any
    snapshot, issue, graph, state, or audit failure rolls back all writes.

**Compatibility requirement for Phase 2 intake:** Keep `CreateOrderInput`
and its domain-valid `OrderLine` construction unchanged. Phase 5 tests create
an `EXTRACTED` order with empty or already-valid trusted lines using the
existing immutable aggregate/state transitions and persistence setup. The
untrusted draft is stored only as `ExtractionDraft` JSON. A review result never
constructs an invalid `OrderLine`; a ready result replaces the existing graph
with validated lines. Phase 5 does not add an extraction-completion operation
or silently change Phase 2 intake semantics; the preceding extraction caller
must supply an order already in `EXTRACTED`.

**Steps:**

1. Write unit RED tests for request construction, provider call count and
   arguments, preflight failures, local-fact ownership, snapshot replay/
   conflict classification, and safe provider error translation. Use a
   provider test double that can inspect the supplied `AsyncSession` and
   assert `session.in_transaction()` is false when the provider is invoked.
2. Write integration RED tests for the ready, review, and high-value ready
   paths, including the exact final state/result/audit values and trusted
   catalogue prices on the ready path.
3. Add a pure-engine test double or controlled engine seam that records the
   supplied session state at invocation, and assert the second local-fact read
   transaction has also been closed before the engine runs.
4. Implement the service in the sequence above. Keep provider lookup outside
   both read and final write transactions, keep the engine outside all
   database transactions, and keep every repository helper commit-free.
5. Add integration assertions that invalid extracted customer/PO/date/currency
   and line values are present only in the snapshot/issues and never overwrite
   trusted order or line rows on review.
6. Add the state/source race and final-facts-change tests for both routes. Make
   the test prove the changed-data error writes no snapshot/issues/graph/state/
   audit rows and that the engine is not called a second time.
7. Run focused application/domain/persistence integration tests, then inspect
   the complete transaction diff and commit:
   `feat: route validated orders atomically`.

**M5D exit gate:** One internal Python operation validates and durably routes an
`EXTRACTED` order atomically. No HTTP endpoint or external side effect exists.

## M5E — Rule Matrix, Integration & Adversarial Hardening

M5E is primarily a coverage and boundary-hardening milestone. Before changing
production code, inventory the tests added in Tasks 1–9 and record each
behavior’s primary owner. Add production code only for a demonstrated contract
defect; do not manufacture a production change to satisfy redundant tests.

### Task 10 — Close matrix and cross-boundary coverage gaps

**Files:** Extend `tests/unit/validation/test_engine.py`,
`tests/unit/validation/test_sandbox.py`,
`tests/unit/persistence/test_mappers.py`,
`tests/integration/test_phase5_persistence.py`, and
`tests/integration/test_phase5_application.py` only where the inventory shows
a genuine missing assertion.

**Primary ownership:** engine unit tests own rule semantics and issue shape;
sandbox unit tests own external reference lookup behavior; persistence tests
own schema/mapping/local-fact semantics; application integration tests own
orchestration, promotion, routing, and transaction outcomes.

**Steps:**

1. Inventory existing assertions by rule code and contract boundary before
   editing. Confirm all matrix codes have one primary engine test owner and
   no rule behavior is tested only through a brittle end-to-end side effect.
2. Fill real engine gaps for exact severities, paths, expected/actual JSON-safe
   values, explanations, ordering, prerequisite suppression, independent
   continuation, simultaneous violations, missing/known-zero inventory,
   negative/non-positive values, zero catalogue price, all three tolerance
   boundaries, and high-value below/exact threshold.
3. Fill real sandbox gaps for exact customer/SKU behavior, ambiguous names,
   inactive records, duplicate trusted configuration rejection, deterministic
   ordering, and proof that no duplicate PO/source-hash fixture is accepted by
   the provider.
4. Fill real persistence/application gaps for customer-scoped duplicate PO,
   duplicate source SHA, replay versus conflict, source ownership, malformed
   snapshot rejection, ordered issue positions, trusted ready-path promotion,
   and invalid review-path non-promotion.
5. Run the focused suites and record whether each change was a test-only gap
   closure or a production correction tied to a demonstrated contract defect.
   Commit test-only work as:
   `test: close Phase 5 matrix and integration coverage gaps`.

### Task 11 — Adversarial rollback, race, privacy, and regression hardening

**Files:** Extend the Phase 5 unit/integration tests from Task 10 and modify
production files only if an adversarial test demonstrates a real defect.

**Steps:**

1. Add representative failure injection after snapshot insertion, after issue
   replacement, during trusted graph replacement, during state persistence,
   and during audit insertion. Assert one transaction rolls back snapshot,
   issues, order fields/lines, state, and audit events with no partial rows.
2. Add state-race, source-identity mismatch, source ownership, wrong-state,
   exact replay, conflicting replay, and database uniqueness tests. Verify no
   duplicate snapshot is created and no uniqueness error is exposed as a fake
   validation issue.
3. Add local-fact staleness tests for both `NEEDS_REVIEW` and
   `READY_FOR_APPROVAL`. After the initial facts and engine result but before
   final commit, make one repository fact differ; assert the safe race error,
   zero writes, uniform route behavior, and no repository-side engine rerun.
4. Add provider-contract and privacy tests proving invalid provider results and
   operational failures expose no raw exception/provider response, source
   text, secret, API key, or SDK object. Inspect imports and test doubles for
   no live LLM/provider SDK/network, ERP/CRM, email, Slack, stock, or n8n
   interaction.
5. Add repeated-input equality tests across the full application preparation
   boundary where IDs/timestamps are excluded from engine equality, and verify
   explicit database ordering for lines, sources, issues, and audits.
6. Run the complete verification ladder below. If Docker/PostgreSQL is
   unavailable, state that fact in the milestone report and rely on exact-head
   GitHub CI for the PostgreSQL proof; never claim a local pass that was not
   observed.
7. Inspect the final diff for future-phase leakage, secrets, generated files,
   and unrelated changes. Commit any justified hardening as:
   `test: harden Phase 5 validation boundaries`.

**M5E exit gate:** Deterministic rule, persistence, application, rollback,
replay/conflict, race, privacy, scope, and regression coverage is complete and
the exact-head CI gates pass. Phase 5 remains `IN PROGRESS` until M5F.

## M5F — Independent Phase 5 Audit & Closeout Boundary

M5F is not executed by this plan. After M5E and its exact-head CI pass, an
independent audit starts read-only from the main baseline to the exact Phase 5
candidate HEAD. It classifies CRITICAL/HIGH/MEDIUM/LOW findings, remediates
only demonstrated defects, fully re-audits after remediation, and creates
`docs/audits/phase-5-audit.md` only after the audit passes. Its closeout then
updates truthful README/roadmap status and obtains exact-head CI evidence
before any PR/integration action. No M5F artifact or status change is created
by this planning task, and Phase 5 must not be marked complete earlier.

## M5B–M5E Status-Only Closeout Protocol

For each of M5B, M5C, M5D, and M5E, use this sequence after the implementation
candidate is complete:

```text
implementation candidate
    → exact-head CI
    → independent ChatGPT PASS
    → status-only closeout commit
    → exact-head CI for the closeout commit
    → continue automatically to the next approved milestone
```

Routine user approval is not required when the candidate conforms to the
approved design and the independent review identifies no unresolved
architecture, scope, or product decision. Explicit user direction is required
only for an architecture change, material scope change, new product-level
decision, or an independent-review decision that cannot be resolved from the
approved design.

The status-only commit modifies only `README.md` and
`docs/roadmap/project-roadmap.md` as needed to reflect completed work. It is
separate from implementation commits and is created only after the milestone
candidate has passed its review gate. The first legitimate Phase 5 status
update must also repair the known stale Phase 4 overview-table row from
`IN PROGRESS` to `COMPLETE`; the existing Phase 4 narrative and audit are the
evidence for that repair.

After the M5B closeout, status must show approximately:

```text
Phase 4 — COMPLETE
Phase 5 — IN PROGRESS

M5A — COMPLETE
M5B — COMPLETE
M5C — NOT STARTED
M5D — NOT STARTED
M5E — NOT STARTED
M5F — NOT STARTED

Phase 6 — NOT STARTED
```

Each later closeout advances only the milestone that has just passed its
review and closeout gates. Phase 5 remains `IN PROGRESS` until M5F completes.

## Transaction Strategy

The later implementation must follow this exact boundary:

```text
initial preflight reads on supplied session
    → explicit session.rollback() to close initial SQLAlchemy autobegin
    → provider call with no DB transaction open
    → local ValidationFacts reads in a second short read transaction
    → explicit session.rollback() to close the second read transaction
    → pure five-input engine call with no DB transaction open
    → explicit session.begin()
        → SELECT ... FOR UPDATE order row
        → state/source/snapshot replay-conflict checks
        → fresh local ValidationFacts query
        → compare facts with engine input
        → insert snapshot
        → replace issues
        → ready-only trusted graph promotion
        → state transitions
        → ordered audit inserts
    → one commit
```

Each database read phase may autobegin a transaction because SQLAlchemy 2 async
sessions autobegin on the first database operation. The service must explicitly
roll the supplied session back immediately after the initial order/source/
snapshot preflight, before the provider call. The provider therefore runs with
no transaction open on that session. Local-fact repository reads then use a
second short read transaction, which the service immediately rolls back before
the engine call. Both read phases make no writes, so these rollbacks discard no
application work.

No repository helper calls `commit`, begins an independent transaction, or
reruns the engine. After the second rollback, the final transaction locks the
order first, revalidates state/source/snapshot identity, re-queries both local
facts, and compares the fresh immutable `ValidationFacts` to the exact value
used by the engine. Any difference raises `ValidationFactsChangedError` and
the transaction context rolls back. The same guard is applied to both routes.
Any later write failure also rolls back the snapshot, issue replacement, graph,
state, and all audit events together.

## Testing and Verification Ladder

### Task-level RED/GREEN

For new deterministic behavior, each task writes a focused failing assertion,
confirms the failure is the intended missing behavior, implements the smallest
change, reruns the focused test, runs the relevant regression subset, and
refactors only when the behavior remains covered. Assertions are never
weakened, correct expectations are never changed to match broken behavior,
tests are never skipped, and no sleeps or live APIs are used. Existing correct
behavior receives characterization assertions without manufacturing a RED
failure.

### M5B verification

```bash
uv run pytest tests/unit/validation -q --no-cov
uv run pytest tests/unit/domain -q --no-cov
uv run ruff check src/opsflow/validation tests/unit/validation
uv run ruff format --check src/opsflow/validation tests/unit/validation
uv run mypy src/opsflow
```

### M5C verification

```bash
uv run pytest tests/unit/persistence -q --no-cov
uv run pytest tests/integration/test_phase5_persistence.py -q --no-cov
uv run pytest tests/integration/test_phase2_migrations.py -q --no-cov
uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
```

The PostgreSQL migration test must prove a clean database reaches revision
`0003_phase5_extraction_snapshots` from `0001_baseline` through
`0002_phase2_persistence`, and that the existing Phase 2 schema remains valid.

### M5D verification

```bash
uv run pytest tests/unit/application tests/unit/domain -q --no-cov
uv run pytest tests/unit/persistence -q --no-cov
uv run pytest tests/integration/test_phase5_persistence.py -q --no-cov
uv run pytest tests/integration/test_phase5_application.py -q --no-cov
uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
uv build
```

### M5E final verification

Run exactly these focused suites and repository gates:

```bash
uv run pytest tests/unit/validation -q --no-cov
uv run pytest tests/unit/domain -q --no-cov
uv run pytest tests/unit/application -q --no-cov
uv run pytest tests/unit/persistence -q --no-cov
uv run pytest tests/integration -q --no-cov

uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
uv build
make frontend-check
git diff --check
```

When Docker/PostgreSQL is available, also run `make check`. If it is
unavailable locally, report that honestly and use exact-head CI for the
PostgreSQL-backed Backend proof. The existing CI must remain network-free from
live business providers and must retain Backend, Frontend, and Secret scan
jobs. Every milestone candidate is pushed at its exact reviewed HEAD; all
three jobs must be `SUCCESS` before the next independent review gate.

## Commit Strategy

Use one coherent commit per implementation task, after its focused checks and
diff inspection. The planned sequence is:

1. `feat: add Phase 5 validation contracts`
2. `feat: add explicit Phase 5 validation policy`
3. `feat: add sandbox business data provider`
4. `feat: implement deterministic validation engine`
5. `feat: persist Phase 5 extraction snapshots`
6. `feat: add deterministic extraction snapshot mapping`
7. `feat: add Phase 5 validation persistence operations`
8. `feat: add validated order promotion`
9. `feat: route validated orders atomically`
10. `test: close Phase 5 matrix and integration coverage gaps`
11. `test: harden Phase 5 validation boundaries`

Keep any legitimate contract-defect correction in the smallest affected task
commit. Keep later status-only closeout commits separate from implementation
commits, and do not mark Phase 5 complete before M5F.

## Plan Self-Review

Before committing this plan, verify the following:

- [x] Spec coverage maps the AI/trust boundary, snapshot envelope and JSON,
  pure five-input engine, trusted-data split, `ValidationFacts`, policy,
  context, complete rule matrix, promotion, application sequence, migration,
  repository authority, locking, audit events, errors, tests, non-goals, and
  milestone boundaries to concrete tasks.
- [x] M5A-001 is resolved explicitly: external `TrustedBusinessData` contains
  only customer/product reference records; local duplicate PO and processed
  SHA facts live only in immutable `ValidationFacts` built by focused OpsFlow
  repository functions; the provider and sandbox know no local history.
- [x] M5A-002 is explicit: `approval_level` is in-memory, while persisted
  `HIGH_VALUE_APPROVAL_REQUIRED` is the stable Phase 5 signal; no persistence
  field or state is added.
- [x] Every later task consumes only interfaces introduced by an earlier task.
  The exact names and signatures above are consistent across models,
  mappers, repositories, domain promotion, engine, and application service.
- [x] The plan explains the current Phase 2 intake compatibility boundary:
  invalid drafts never become `OrderLine` objects, and no Phase 2 creation API
  is silently changed.
- [x] The transaction plan identifies SQLAlchemy autobegin, explicitly closes
  both pre-final read transactions before provider/engine work, locks the final
  order, rechecks local facts uniformly, and proves all-or-nothing rollback
  without a repository-side engine rerun.
- [x] Routine user-approval stops were removed; explicit user direction is
  reserved for architecture, material scope, product decisions, or an
  independent-review decision not resolved by the approved design.
- [x] README.md and docs/roadmap/project-roadmap.md are planned only for
  separate post-review status commits, including the first stale Phase 4 row
  repair and truthful M5B–M5E progression.
- [x] The plan has no future API/UI/integration framework, no generic rule or
  persistence abstraction, no speculative dependency, and no M5F artifact.
- [x] Unresolved-marker and contradiction scans are required before commit; the
  plan contains no unresolved implementation marker.

## Scope and Closeout Contract

This document authorizes later implementation planning only. The current task
must change exactly this plan file, must not modify the approved design, and
must leave all production, test, migration, dependency, README, roadmap,
status, audit, API, and PR artifacts unchanged. Later milestone closeouts may
modify only the planned status files after their review and CI gates. The
current remediation is complete only after `git diff --check`, Markdown-link
validation, exact-head CI, and the final independent review gate are recorded.
