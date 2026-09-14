# Phase 2 Persistence & Core API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build OpsFlow AI's first durable PostgreSQL-backed order intake and
retrieval vertical slice with idempotent creation, audit persistence, and the
four approved `/v1/orders` endpoints.

**Architecture:** Implement the accepted thin API → application →
domain/persistence architecture. Phase 1 remains the business authority;
SQLAlchemy/Pydantic adapt around it. PostgreSQL provides durable storage and
database-authoritative idempotency uniqueness.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, asyncpg,
Alembic, PostgreSQL, pytest, HTTPX, Ruff, mypy, uv, Docker Compose.

**Spec:**
`docs/superpowers/specs/2026-09-14-phase-2-persistence-api-design.md`

## Global Constraints

- Read and follow the accepted Phase 2 design before each milestone; it is the
  behavioral authority and this plan is its execution sequence.
- Work only on `phase/2-persistence-api`; do not modify `main` or implement
  Phase 3+ behavior.
- Keep `src/opsflow/domain/` unchanged. If a real Phase 1 contract defect is
  discovered, stop the task and report it rather than reshaping the domain.
- Use exactly the six approved tables and exactly the four approved business
  endpoints; preserve existing `/health` and `/ready` behavior.
- Keep AI, document processing, validation policy, approval, integrations,
  authentication, workers, Redis, queues, event buses, and mature error
  infrastructure out of Phase 2.
- Use explicit concrete persistence operations; no abstract repository
  interface, generic CRUD base, Unit of Work framework, CQRS, mediator,
  command bus, service container, DI library, or state-machine framework.
- Use Pydantic v2 with nested `extra="forbid"`, but leave domain structural
  validity to Phase 1 constructors rather than duplicating policy.
- Use PostgreSQL NUMERIC for Decimal values and preserve explicit child
  positions, ordered duplicate-key metadata, state/origin checks, and UTC
  timezone-aware timestamps.
- The idempotency database uniqueness constraint is the concurrency authority.
  Do not replace it with a pre-check, lock service, TTL, or cleanup worker.
- Every successful intake writes order, children, one initial audit event, and
  one idempotency record in one transaction or writes nothing.
- Use real PostgreSQL for migration, constraint, transaction, and concurrency
  behavior. Synthetic fixtures only; no live provider or external side effect.
- Expected result: no new runtime dependency. Do not add `pytest-asyncio`
  merely for convenience.
- Follow RED → expected failure → minimal GREEN → targeted verification →
  justified refactor → milestone regression → diff review → focused commit.
- Apply Alembic explicitly through the established workflow; do not add
  unbounded startup schema mutation.
- Keep commits coherent and reviewable. Do not create a commit for every
  assertion or ceremonial setup step.

## File and interface map

The expected production files are:

| File | Responsibility | First milestone |
| --- | --- | --- |
| `src/opsflow/persistence/__init__.py` | Small persistence package surface. | M2B |
| `src/opsflow/persistence/models.py` | SQLAlchemy metadata and six table models. | M2B |
| `src/opsflow/persistence/mappers.py` | Explicit ORM ↔ Phase 1 mapping. | M2B |
| `src/opsflow/persistence/repositories.py` | Concrete row and read operations only. | M2C |
| `src/opsflow/application/__init__.py` | Small application package surface. | M2C |
| `src/opsflow/application/errors.py` | HTTP-independent application errors. | M2C |
| `src/opsflow/application/orders.py` | Thin order read/create orchestration. | M2C |
| `src/opsflow/api/__init__.py` | Small API package surface. | M2E |
| `src/opsflow/api/schemas.py` | Pydantic v2 request/response contracts. | M2E |
| `src/opsflow/api/orders.py` | Four order routes and HTTP translation. | M2E |
| `src/opsflow/database.py` | Existing engine plus session factory support. | M2E |
| `src/opsflow/main.py` | Existing app plus router/session wiring. | M2E |
| `alembic/env.py` | Persistence metadata as Alembic target metadata. | M2B |
| `alembic/versions/0002_phase2_persistence.py` | Reviewed Phase 2 migration. | M2B |

Create package `__init__.py` files only if normal package behavior or exports
need them. Do not create empty future-phase modules.

The small explicit read containers used below are permitted because they keep
ORM rows inside persistence while returning typed domain data and persistence
metadata:

~~~python
@dataclass(frozen=True, slots=True)
class PersistedOrder:
    order: Order
    created_at: datetime
    validation_issues: tuple[ValidationIssue, ...]


@dataclass(frozen=True, slots=True)
class OrderSummary:
    order: Order
    created_at: datetime
~~~

If a simpler typed representation is demonstrably clearer, use it without
creating a generalized result framework. The names and fields above are the
default interfaces for later tasks.

---

## M2B — Relational Schema & Domain Mapping

M2B implements only ORM metadata/models, the six-table migration, database
constraints/indexes, metadata wiring, and explicit mapping. It does not add
repository use cases, idempotency orchestration, application HTTP operations,
or API routes.

### Task 1: Define six-table SQLAlchemy metadata and defense-in-depth constraints

**Files:**

- Create: `src/opsflow/persistence/__init__.py`
- Create: `src/opsflow/persistence/models.py`
- Test: `tests/unit/persistence/test_models.py`

**Interfaces:**

- Produces: a SQLAlchemy declarative base/metadata and named models:
  `OrderModel`, `OrderLineModel`, `SourceDocumentModel`,
  `ValidationIssueModel`, `AuditEventModel`, and
  `OrderCreationIdempotencyModel`.
- Produces: metadata containing exactly `orders`, `order_lines`,
  `source_documents`, `validation_issues`, `audit_events`, and
  `order_creation_idempotency`.

- [ ] **Step 1: Write the failing metadata tests**

  Assert the exact table set, required columns, primary keys, foreign keys,
  `UNIQUE(order_id, position)` for every ordered child, composite
  `(order_id, position)` identity for validation issues, and the idempotency
  key primary key. Assert that state, source-document type, severity,
  currency, SHA-256, state/failure-origin, position, numeric, and metadata
  checks are represented in the metadata.

  Include a test that metadata does not contain a processing-attempt table or
  PostgreSQL custom ENUM type. Use SQLAlchemy inspection of constraints rather
  than asserting only class attributes.

- [ ] **Step 2: Run the focused tests to confirm RED**

  Run:

  ~~~bash
  uv run pytest tests/unit/persistence/test_models.py -q --no-cov
  ~~~

  Expected: collection fails because the persistence package/models do not
  exist. Correct only test setup errors; do not create migration or repository
  stubs to make collection pass.

- [ ] **Step 3: Implement the smallest model metadata**

  Define the six models with UUID keys, nullable Phase 1 order fields,
  TIMESTAMPTZ metadata, NUMERIC quantities/prices, JSONB metadata/expected/
  actual values, explicit child positions, and foreign keys. Add the exact
  state values, five document-type values, three severity values, currency
  shape, SHA-256 shape, non-negative position, quantity/price lower bounds,
  ordered metadata outer-array, and conditional failure-origin checks from the
  design.

  Use only minimal indexes justified by current reads: child order access,
  audit order/occurred_at/id ordering, order creation ordering as needed, and
  the unique idempotency key. Do not add speculative columns or indexes.

- [ ] **Step 4: Verify the model contract and commit**

  Run:

  ~~~bash
  uv run pytest tests/unit/persistence/test_models.py -q --no-cov
  uv run ruff check src/opsflow/persistence tests/unit/persistence
  uv run mypy src/opsflow
  git diff --check
  ~~~

  Inspect the model diff for exact six-table scope and commit this
  independently reviewable schema slice.

  ~~~bash
  git add src/opsflow/persistence tests/unit/persistence/test_models.py
  git commit -m "feat: add Phase 2 persistence schema"
  ~~~

### Task 2: Write and verify the reviewed Alembic 0002 migration

**Files:**

- Modify: `alembic/env.py`
- Create: `alembic/versions/0002_phase2_persistence.py`
- Test: `tests/integration/test_phase2_migrations.py`
- Test: `tests/integration/test_phase2_schema.py`

**Interfaces:**

- Produces: Alembic chain `0001_baseline → 0002_phase2_persistence` and a
  downgrade back to `0001_baseline`.
- Produces: `alembic/env.py` target metadata imported from
  `opsflow.persistence.models` without importing the FastAPI app or creating
  an engine as an import side effect.

- [ ] **Step 1: Write migration and schema tests before the revision exists**

  Add real-PostgreSQL tests that:

  - upgrade an empty database through both revisions;
  - assert the exact six business tables plus Alembic bookkeeping;
  - assert foreign keys, primary/unique constraints, state/origin checks,
    numeric checks, metadata-array check, and the minimal expected indexes;
  - downgrade Phase 2 to the baseline and assert only baseline bookkeeping
    remains;
  - upgrade again successfully.

  The schema test must attempt invalid direct inserts for an unknown state,
  invalid failure-origin combinations, non-positive quantity, negative price,
  duplicate child position, invalid source-document type/severity, and a
  missing parent row, and assert PostgreSQL rejects each one.

- [ ] **Step 2: Run the migration tests to confirm RED**

  With a dedicated synthetic PostgreSQL test database available, run:

  ~~~bash
  docker compose up -d --build
  uv run pytest tests/integration/test_phase2_migrations.py -q --no-cov
  uv run pytest tests/integration/test_phase2_schema.py -q --no-cov
  ~~~

  Expected: tests fail because `0002_phase2_persistence` and metadata
  wiring do not exist. If Docker/PostgreSQL is unavailable, record the
  environmental failure and do not weaken or skip the tests.

- [ ] **Step 3: Implement the reviewed migration directly**

  Import persistence metadata as Alembic `target_metadata`. Write the
  migration operations explicitly rather than blindly accepting
  autogeneration output. Create all six tables, foreign keys, checks,
  uniqueness constraints, and justified indexes. Use foreign-key-safe
  downgrade order and make the revision reversible.

  Review generated SQL or Alembic operations against Task 1’s metadata. Do not
  add triggers, custom enum types, processing attempts, or unrelated schema.

- [ ] **Step 4: Run upgrade/downgrade/re-upgrade and commit**

  Run:

  ~~~bash
  uv run alembic upgrade head
  uv run alembic current
  uv run pytest tests/integration/test_phase2_migrations.py -q --no-cov
  uv run pytest tests/integration/test_phase2_schema.py -q --no-cov
  uv run alembic downgrade 0001_baseline
  uv run alembic upgrade head
  git diff --check
  ~~~

  Inspect the complete migration diff and commit:

  ~~~bash
  git add alembic/env.py alembic/versions/0002_phase2_persistence.py tests/integration
  git commit -m "feat: add Phase 2 persistence migration"
  ~~~

### Task 3: Implement explicit domain ↔ persistence mappers

**Files:**

- Create: `src/opsflow/persistence/mappers.py`
- Test: `tests/unit/persistence/test_mappers.py`
- Test: `tests/integration/test_phase2_round_trip.py`

**Interfaces:**

- Produces: explicit functions with no ORM leakage:
  `order_to_model(order: Order, created_at: datetime) -> OrderModel`;
  `line_to_model(order_id: UUID, position: int, line: OrderLine) -> OrderLineModel`;
  `source_document_to_model(order_id: UUID, position: int, document: SourceDocument) -> SourceDocumentModel`;
  `order_from_models(order_row: OrderModel, line_rows: Sequence[OrderLineModel], document_rows: Sequence[SourceDocumentModel]) -> Order`;
  `validation_issue_from_model(row: ValidationIssueModel) -> ValidationIssue`;
  `audit_event_from_model(row: AuditEventModel) -> AuditEvent`.
- Consumes: only validated Phase 1 records and the ORM models from Task 1.
- Produces: Decimal, enum, UUID, date, timezone-aware datetime, tuple, and
  ordered metadata values reconstructed through Phase 1 constructors.

- [ ] **Step 1: Write pure mapper tests**

  Test a minimal RECEIVED order and a populated order. Assert that Decimal
  quantity/prices remain Decimal, no binary float is used, state/origin map to
  OrderState, dates/UUIDs survive, child positions are represented explicitly,
  and malformed mapped values are rejected by Phase 1 constructors.

  Test source metadata with duplicate keys and non-sorted order, for example
  `(("message_source", "email"), ("message_source", "archive"))`, and assert
  the JSONB representation is an ordered pair array and the reverse mapping is
  identical. Test validation issue fields and JSON-compatible expected/actual
  values, plus timezone-aware audit reconstruction.

- [ ] **Step 2: Run mapper tests to confirm RED**

  Run:

  ~~~bash
  uv run pytest tests/unit/persistence/test_mappers.py -q --no-cov
  ~~~

  Expected: collection or import failure until the mapper module and models
  exist. Keep the failure caused by the missing mapping behavior.

- [ ] **Step 3: Implement explicit mapping only**

  Map every Phase 1 field explicitly. Preserve tuple order through the
  position column, convert NUMERIC values to Decimal before domain
  construction, serialize metadata only as ordered pair arrays, and map
  validation issues/audit events as separate domain records because they are
  not fields on Order. Do not add lifecycle mutation or repository behavior.

- [ ] **Step 4: Prove real round trips and commit M2B**

  Insert mapper-produced rows through a direct test session after applying
  migrations, reconstruct them with the mappers, and assert exact aggregate,
  Decimal, metadata, child-order, validation-issue, and audit values.

  Run:

  ~~~bash
  uv run pytest tests/unit/persistence/test_mappers.py -q --no-cov
  uv run pytest tests/integration/test_phase2_round_trip.py -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src/opsflow
  git diff --check
  ~~~

  Commit the complete M2B mapping slice:

  ~~~bash
  git add src/opsflow/persistence tests/unit/persistence tests/integration/test_phase2_round_trip.py
  git commit -m "feat: add Phase 2 domain persistence mapping"
  ~~~

---

## M2C — Repository & Durable Reads

M2C adds concrete persistence operations and thin read application use cases
only. It does not add HTTP routes, Pydantic API schemas, idempotency
orchestration, or state mutation.

### Task 4: Add concrete repository operations and deterministic reads

**Files:**

- Modify: `src/opsflow/persistence/repositories.py`
- Test: `tests/integration/test_phase2_repositories.py`

**Interfaces:**

- Produces:
  `async def insert_order_graph(session: AsyncSession, order: Order, created_at: datetime) -> None`;
  `async def get_order(session: AsyncSession, order_id: UUID) -> PersistedOrder | None`;
  `async def list_orders(session: AsyncSession, limit: int, offset: int) -> tuple[tuple[OrderSummary, ...], int]`;
  `async def get_audit_events(session: AsyncSession, order_id: UUID) -> tuple[AuditEvent, ...]`.
- Consumes: Task 3 mappers and Task 1 ORM models.
- Produces: typed Phase 1 records and persistence metadata only; no SQLAlchemy
  model escapes the persistence module.

- [ ] **Step 1: Write failing repository integration tests**

  Test direct graph persistence/reconstruction for minimal and populated
  orders. Test that list returns summaries only, applies `created_at DESC,
  id DESC`, honors limit/offset, and returns the unfiltered total. Test
  audit retrieval uses `occurred_at ASC, id ASC` and keeps child ordering.
  Assert returned values contain domain records, not ORM model instances.

- [ ] **Step 2: Run the repository tests to confirm RED**

  Run:

  ~~~bash
  uv run pytest tests/integration/test_phase2_repositories.py -q --no-cov
  ~~~

  Expected: import or missing-operation failure because concrete repository
  functions do not exist.

- [ ] **Step 3: Implement minimal explicit SQLAlchemy operations**

  Insert the order row and ordered child rows using the mappers. Retrieve
  child collections with explicit position ordering. Use a deterministic
  two-column order for list results and a single count query. Retrieve audit
  rows with the required timestamp/ID ordering. Keep transaction ownership
  with the caller; repository functions do not add a Unit of Work framework.

- [ ] **Step 4: Verify repository behavior and commit**

  Run the focused integration tests, the mapper/domain suites, Ruff,
  formatting, and mypy. Inspect SQL construction for SQLAlchemy-only
  parameterized statements and commit:

  ~~~bash
  git add src/opsflow/persistence/repositories.py tests/integration/test_phase2_repositories.py
  git commit -m "feat: add durable order reads"
  ~~~

### Task 5: Add thin application read use cases and not-found errors

**Files:**

- Create: `src/opsflow/application/__init__.py`
- Create: `src/opsflow/application/errors.py`
- Create: `src/opsflow/application/orders.py`
- Test: `tests/unit/application/test_errors.py`
- Test: `tests/integration/test_phase2_application_reads.py`

**Interfaces:**

- Produces: `class OrderNotFoundError(Exception)` with no HTTP dependency.
- Produces:
  `async def get_order(session: AsyncSession, order_id: UUID) -> PersistedOrder`;
  `async def list_orders(session: AsyncSession, limit: int, offset: int) -> tuple[tuple[OrderSummary, ...], int]`;
  `async def get_order_audit(session: AsyncSession, order_id: UUID) -> tuple[AuditEvent, ...]`.
- Consumes: Task 4 repository operations.
- Does not produce: routes, HTTPException, Pydantic schemas, idempotency
  behavior, or state transitions.

- [ ] **Step 1: Write failing application read tests**

  Assert an existing order is returned as Phase 1 records plus created_at and
  validation issues. Assert missing detail and missing audit raise
  OrderNotFoundError. Assert list and audit ordering remain unchanged from the
  repository contract. Assert application errors have no FastAPI/HTTP imports.

- [ ] **Step 2: Run tests to confirm RED and implement minimally**

  Run:

  ~~~bash
  uv run pytest tests/unit/application/test_errors.py tests/integration/test_phase2_application_reads.py -q --no-cov
  ~~~

  Expected: import failure first, then focused failures until the two read
  operations and not-found translation are implemented. Use a direct
  repository call and one explicit error branch; do not create a generic
  exception hierarchy.

- [ ] **Step 3: Run M2C regression and commit**

  Run:

  ~~~bash
  uv run pytest tests/unit/domain -q --no-cov
  uv run pytest tests/unit/persistence tests/unit/application -q --no-cov
  uv run pytest tests/integration/test_phase2_repositories.py tests/integration/test_phase2_application_reads.py -q --no-cov
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src/opsflow
  git diff --check
  ~~~

  Commit:

  ~~~bash
  git add src/opsflow/application tests/unit/application tests/integration/test_phase2_application_reads.py
  git commit -m "feat: add application order reads"
  ~~~

---

## M2D — Idempotent Order Creation

M2D adds canonical semantic input/fingerprinting, atomic creation, the fixed
initial audit event, idempotency conflict behavior, rollback, and concurrency
proof. It does not add HTTP routes.

### Task 6: Define semantic create input and canonical fingerprinting

**Files:**

- Modify: `src/opsflow/application/orders.py`
- Test: `tests/unit/application/test_fingerprinting.py`

**Interfaces:**

- Produces small immutable create-input records without server IDs:
  `CreateOrderInput`, `CreateLineInput`, and `CreateSourceDocumentInput`.
- Produces:
  `def canonical_order_request(request: CreateOrderInput) -> bytes`;
  `def fingerprint_order_request(request: CreateOrderInput) -> str`.
- Consumes: Phase 1 enums/Decimal/date types; no raw HTTP bytes and no API
  module imports.

- [ ] **Step 1: Write pure RED tests**

  Test that object-key ordering in two validated semantic inputs produces
  identical canonical bytes/fingerprints, while order-line and source-document
  list order remains significant. Test null optional values and omitted
  collections materialized as empty tuples.

  Test Decimal normalization for `5.0`/`5.00`, exponent expansion, trailing
  zero removal, and all zero spellings becoming the canonical string
  `"0"`. Test dates use ISO strings, enums use Phase 1 values, and generated
  IDs/timestamps/state/failure-origin are absent from the canonical payload.

- [ ] **Step 2: Run the focused tests to confirm RED**

  Run:

  ~~~bash
  uv run pytest tests/unit/application/test_fingerprinting.py -q --no-cov
  ~~~

  Expected: import failure because the create input and fingerprint functions
  do not exist.

- [ ] **Step 3: Implement the smallest deterministic serializer**

  Normalize validated values into an explicit fixed-field semantic object,
  preserve semantic array order, encode UTF-8 compact JSON with stable object
  keys, and hash the bytes with SHA-256. Reject non-finite or unsupported
  values explicitly. Do not normalize arbitrary strings or use float
  conversion.

- [ ] **Step 4: Verify and commit the pure slice**

  Run the focused tests, domain suite, Ruff, formatting, and mypy. Commit:

  ~~~bash
  git add src/opsflow/application/orders.py tests/unit/application/test_fingerprinting.py
  git commit -m "feat: add canonical order fingerprints"
  ~~~

### Task 7: Implement atomic creation, initial audit, replay, and conflict behavior

**Files:**

- Modify: `src/opsflow/persistence/repositories.py`
- Modify: `src/opsflow/application/errors.py`
- Modify: `src/opsflow/application/orders.py`
- Test: `tests/integration/test_phase2_creation.py`

**Interfaces:**

- Produces: `class IdempotencyConflictError(Exception)` with no HTTP
  dependency.
- Produces:
  `async def create_order(session: AsyncSession, request: CreateOrderInput, idempotency_key: str, now: datetime | None = None) -> PersistedOrder`.
- Produces concrete idempotency row insert/read operations used only by this
  workflow.
- Consumes: Task 6 fingerprinting, Task 4 graph persistence, and the Phase 1
  `Order.received` constructor.

- [ ] **Step 1: Write failing real-PostgreSQL creation tests**

  Test minimal and populated RECEIVED creation, server-generated IDs, exact
  initial audit values, UTC occurrence, one idempotency row, and all child
  values. Test sequential same-key/same-input replay returns the same order
  and created_at without adding rows. Test same-key/different-input raises
  IdempotencyConflictError and leaves exactly one winner.

- [ ] **Step 2: Run creation tests to confirm RED**

  Run:

  ~~~bash
  uv run pytest tests/integration/test_phase2_creation.py -q --no-cov
  ~~~

  Expected: import or missing-operation failure because create orchestration
  and idempotency operations do not exist.

- [ ] **Step 3: Implement the one-transaction workflow**

  Validate the create input before opening the write transaction, compute the
  fingerprint, generate order/child/source/audit IDs and UTC timestamps, and
  construct Order.received(...). Inside one AsyncSession transaction insert
  order, lines, source documents, exactly one fixed ORDER_RECEIVED audit row,
  and the idempotency row.

  Let the database unique key decide the race. Do not perform SELECT-then-
  INSERT as the uniqueness authority. On a unique-key integrity failure,
  roll back the entire losing transaction, start a fresh read transaction,
  load the committed idempotency row, compare fingerprints, and either return
  its order or raise IdempotencyConflictError.

- [ ] **Step 4: Verify atomic sequential semantics and commit**

  Run the focused creation tests, M2B/M2C integration tests, domain suite,
  Ruff, formatting, mypy, and diff checks. Inspect that no second audit,
  child, order, or idempotency row is written. Commit:

  ~~~bash
  git add src/opsflow/application src/opsflow/persistence/repositories.py tests/integration/test_phase2_creation.py
  git commit -m "feat: add idempotent order creation"
  ~~~

### Task 8: Prove concurrency and rollback against real PostgreSQL

**Files:**

- Modify: `tests/integration/test_phase2_creation.py`
- Test: `tests/integration/test_phase2_concurrency.py`
- Modify: `src/opsflow/application/orders.py` only if the focused tests expose
  a transaction defect.

**Interfaces:**

- Consumes: Task 7 create operation and real PostgreSQL unique constraints.
- Produces evidence for concurrent identical and conflicting calls, and for
  failure atomicity. It must not introduce Redis, advisory locks, distributed
  locks, TTL cleanup, or retry infrastructure.

- [ ] **Step 1: Write failing concurrency/rollback tests**

  Open two independent AsyncSessions and use `asyncio.gather` to start
  identical create calls with the same key. Assert exactly one order, one
  initial audit, one idempotency row, and equal returned order results.

  Repeat with different semantic inputs and assert one successful winner and
  one IdempotencyConflictError, with no provisional loser rows.

  Inject a deterministic failure after at least one required insert and before
  commit. Assert orders, lines, source documents, audits, and idempotency rows
  are all absent after rollback.

- [ ] **Step 2: Run the focused tests to confirm RED**

  Run:

  ~~~bash
  uv run pytest tests/integration/test_phase2_concurrency.py -q --no-cov
  ~~~

  Expected: failures until the database-race recovery and rollback behavior
  are correct. A test that merely serializes calls is insufficient.

- [ ] **Step 3: Fix only the transaction/race defect and verify**

  Keep the unique constraint as the authority. Ensure the losing session
  performs rollback before the fresh read; do not reuse an invalid transaction
  state. Ensure a winner that fails before commit leaves no record for the
  loser to replay.

  Run:

  ~~~bash
  uv run pytest tests/integration/test_phase2_creation.py tests/integration/test_phase2_concurrency.py -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src/opsflow
  git diff --check
  ~~~

  Commit the concurrency proof as one focused test/implementation slice:

  ~~~bash
  git add src/opsflow/application src/opsflow/persistence tests/integration/test_phase2_creation.py tests/integration/test_phase2_concurrency.py
  git commit -m "test: prove Phase 2 creation concurrency"
  ~~~

---

## M2E — Core /v1/orders API & Hardening

M2E adds only Pydantic transport contracts, request-scoped sessions, the four
approved routes, HTTP translation, response serialization, and regressions for
health/readiness.

### Task 9: Define dedicated Pydantic v2 request and response schemas

**Files:**

- Create: `src/opsflow/api/__init__.py`
- Create: `src/opsflow/api/schemas.py`
- Test: `tests/unit/api/test_schemas.py`

**Interfaces:**

- Produces request schemas:
  `MetadataPair`, `OrderLineCreate`, `SourceDocumentCreate`,
  and `OrderCreateRequest`.
- Produces response schemas:
  `OrderLineResponse`, `SourceDocumentResponse`,
  `ValidationIssueResponse`, `OrderDetailResponse`,
  `OrderSummaryResponse`, `OrderListResponse`, `AuditEventResponse`,
  and `AuditListResponse`.
- Every request and nested model uses `model_config = ConfigDict(extra="forbid")`.
- The schema mapper produces Task 6 `CreateOrderInput` without accepting
  client-generated IDs, state, failure origin, audit events, validation
  issues, or persistence timestamps.

- [ ] **Step 1: Write focused schema RED tests**

  Test minimal and populated request parsing, nested unknown-field rejection,
  forbidden order/line/source IDs, forbidden state/failure-origin/audit/
  validation/timestamp fields, ordered metadata objects with duplicate keys,
  and Decimal/date/enum transport values.

  Test dedicated response serialization includes created_at, lines, source
  documents, validation issues, and lifecycle fields for detail; summaries
  exclude child collections and audit events; audit responses remain separate.

- [ ] **Step 2: Run tests to confirm RED**

  Run:

  ~~~bash
  uv run pytest tests/unit/api/test_schemas.py -q --no-cov
  ~~~

  Expected: collection fails because API schema modules do not yet exist.

- [ ] **Step 3: Implement transport-only schemas**

  Use Pydantic v2 for shape and unknown-field rejection. Keep quantity/price
  and structural domain checks in Phase 1 constructors. Expose source metadata
  as ordered key/value objects and map it losslessly to ordered pairs. Keep
  validation issues response-only for Phase 2 intake.

- [ ] **Step 4: Verify and commit schema contracts**

  Run the focused tests, fingerprint tests, domain suite, Ruff, formatting,
  and mypy. Commit:

  ~~~bash
  git add src/opsflow/api tests/unit/api/test_schemas.py
  git commit -m "feat: add Phase 2 API schemas"
  ~~~

### Task 10: Add request-scoped sessions and the four routes

**Files:**

- Create: `src/opsflow/api/orders.py`
- Modify: `src/opsflow/database.py`
- Modify: `src/opsflow/main.py`
- Test: `tests/integration/test_orders_api.py`
- Test: `tests/integration/test_readiness.py`
- Test: `tests/unit/test_health.py`

**Interfaces:**

- Produces: one application-level
  `async_sessionmaker[AsyncSession]` created from the existing engine.
- Produces: one small request dependency that yields and closes an
  `AsyncSession`; it does not commit business writes.
- Produces exactly:
  `POST /v1/orders`,
  `GET /v1/orders`,
  `GET /v1/orders/{order_id}`, and
  `GET /v1/orders/{order_id}/audit`.
- Consumes: M2C read use cases, M2D create operation, and M2E schemas.

- [ ] **Step 1: Write API integration RED tests**

  Add HTTPX/`asyncio.run` tests for minimal/populated create, generated
  fields, replay, conflict, missing/blank/overlong Idempotency-Key, extra
  fields, structural domain failure, detail, missing detail, list summary,
  limit/offset, deterministic ordering, audit, missing audit, and no duplicate
  order/audit on replay.

  Add regression assertions for `/health` and `/ready`, including the
  existing non-leaking unavailable-database response.

- [ ] **Step 2: Run the focused API tests to confirm RED**

  With PostgreSQL and migrations available, run:

  ~~~bash
  docker compose up -d --build
  uv run alembic upgrade head
  uv run pytest tests/integration/test_orders_api.py tests/integration/test_readiness.py -q --no-cov
  ~~~

  Expected: import or route-not-found failures until session wiring and routes
  exist. Do not change existing readiness expectations to bypass the missing
  database.

- [ ] **Step 3: Implement session lifecycle and route translation**

  Extend database.py with a reusable session factory derived from the existing
  engine. Wire one request-scoped session dependency through the app without
  creating an engine per request. Include the orders router while preserving
  lifespan engine disposal, health, and readiness.

  Routes receive transport data, call application operations, serialize
  dedicated response schemas, and translate OrderNotFoundError to 404 and
  IdempotencyConflictError to 409. Translate malformed transport/domain
  structural failures to 422 and leave unexpected failures as safe 500
  responses. Application code must not raise HTTPException.

  Validate Idempotency-Key as opaque, case-sensitive, nonblank, and no more
  than 128 characters. Return 201 for both new creation and approved replay.

- [ ] **Step 4: Verify route scope and commit**

  Confirm route registration contains exactly the four business paths. Run
  focused API/readiness/health tests and inspect OpenAPI output for no
  approval, rejection, transition, upload, validation, or integration routes.
  Commit:

  ~~~bash
  git add src/opsflow/api src/opsflow/database.py src/opsflow/main.py tests/integration/test_orders_api.py tests/integration/test_readiness.py tests/unit/test_health.py
  git commit -m "feat: expose core order API"
  ~~~

### Task 11: Run full M2E hardening and repository regression

**Files:**

- Modify only files whose defects are demonstrated by Task 10 tests.
- Test: all existing and Phase 2 unit/integration test files.

**Interfaces:**

- Consumes: complete M2B–M2E implementation.
- Produces: no new architecture; only targeted fixes required by evidence.

- [ ] **Step 1: Run the complete backend and frontend gates**

  With PostgreSQL available, run:

  ~~~bash
  make check
  ~~~

  Record test count, coverage, Ruff, formatting, mypy, package build,
  frontend lint/build, and any failures. Also run:

  ~~~bash
  uv run pytest tests/unit/domain -q --no-cov
  ~~~

  with PostgreSQL/Docker unavailable to prove Phase 1 independence.

- [ ] **Step 2: Review for exact scope and security**

  Inspect routes, schemas, SQL construction, migration state, session cleanup,
  error bodies, generated fields, source metadata, idempotency rows, and audit
  counts. Search for credentials, API keys, private/customer data, raw
  document content, Phase 3+ modules, unsafe SQL strings, and direct ORM
  exposure.

- [ ] **Step 3: Apply only evidence-backed fixes and rerun gates**

  For every defect, add or correct the smallest focused test first, verify the
  expected failure, implement the minimal fix, and rerun the affected test.
  Then rerun `make check`, the isolated domain suite, and
  `git diff --check`. Do not weaken assertions or add future-phase behavior.

- [ ] **Step 4: Commit the hardening slice**

  Commit only the verified fixes with a message describing the actual defect.
  If no fixes are needed, do not create an empty commit.

---

## M2F — Independent Phase 2 Audit & Closeout

M2F is not normal feature implementation. It begins only after M2E has a clean
exact-head CI result and does not authorize scope expansion.

### Task 12: Perform the fresh-context adversarial audit

**Files:**

- Create: `docs/audits/phase-2-audit.md` only after the read-only audit pass
  and remediation are complete.
- Modify: implementation files only for justified audit findings.

**Interfaces:**

- Consumes: the complete M2E branch and its exact-head CI evidence.
- Produces: classified findings and, after remediation, a durable audit record.
- Does not produce: new features, new architecture, or unrequested future
  phase work.

- [ ] **Step 1: Start from a fresh context and audit read-only**

  Verify branch, exact HEAD, base relationship, complete diff, migration
  history, six-table schema, ORM/domain boundaries, session lifecycle, route
  set, response/error contracts, idempotency race behavior, rollback,
  concurrency tests, synthetic-data posture, dependency diff, and CI results.
  Re-run relevant checks independently rather than trusting implementer
  summaries.

- [ ] **Step 2: Classify findings**

  Classify every finding as CRITICAL, HIGH, MEDIUM, or LOW with concrete
  evidence. CRITICAL and HIGH findings block closeout. MEDIUM findings require
  remediation or explicit acceptance with rationale. LOW findings must not
  expand Phase 2 scope.

- [ ] **Step 3: Remediate only justified findings**

  For each required fix, follow the same RED → GREEN → regression process,
  keep Phase 1 unchanged, rerun affected PostgreSQL/API tests and full quality
  gates, and record the exact remediation SHA. Re-audit the exact remediation
  SHA; do not audit an unverified working tree.

- [ ] **Step 4: Record the durable audit and commit**

  Write `docs/audits/phase-2-audit.md` with repository/branch/SHA identity,
  findings and verdict, acceptance evidence, commands/results, security/cost
  notes, and known limitations. Commit the audit and any justified remediation
  as coherent reviewable commits.

### Task 13: Close statuses, PR, merge commit, and branch lifecycle

**Files:**

- Modify: `README.md`
- Modify: `docs/roadmap/project-roadmap.md`
- Modify: `docs/superpowers/specs/2026-09-14-phase-2-persistence-api-design.md`
- Create/modify: only the audit/PR documentation required by Task 12.

**Interfaces:**

- Produces canonical status:
  Phase 0 COMPLETE, Phase 1 COMPLETE, Phase 2 COMPLETE;
  M2A–M2F COMPLETE after their evidence is complete.
- Produces a pull request from `phase/2-persistence-api` to `main`,
  GitHub merge commit preserving milestone SHAs, post-merge CI evidence, and
  branch cleanup.

- [ ] **Step 1: Update statuses only after the audit verdict passes**

  Update README, roadmap, and the Phase 2 design status references. Do not
  mark any milestone complete without its evidence. Keep all later phases
  NOT STARTED unless later work actually exists.

- [ ] **Step 2: Verify the PR before merge**

  Independently inspect PR diff, commit list, base/head SHAs, changed-file
  scope, CI jobs, audit verdict, migration state, and security scan. Confirm
  CRITICAL/HIGH findings are zero and MEDIUM findings are fixed or explicitly
  accepted. Do not merge from a stale local branch.

- [ ] **Step 3: Merge with GitHub merge commit**

  Merge the reviewed PR into `main` using a merge commit. Preserve the
  Phase 2 branch commits; do not squash or rewrite milestone history.

- [ ] **Step 4: Verify post-merge main and clean up**

  Fetch remote state, verify the new main SHA and exact-head CI, rerun or
  inspect post-merge quality evidence, confirm the working tree is clean, and
  delete `phase/2-persistence-api` only after integration is verified.

---

## Plan self-review checklist

Before committing this plan, compare it against every section of the accepted
Phase 2 design:

| Design requirement | Plan coverage |
| --- | --- |
| Thin API → application → domain/persistence flow | Global constraints; Tasks 4–10 |
| Exactly six relational tables and no processing-attempt table | Task 1; Task 2 |
| Directly reviewed Alembic 0002 with downgrade/re-upgrade | Task 2 |
| State/failure-origin and numeric database checks | Tasks 1–2 |
| Explicit child positions and deterministic reconstruction | Tasks 1, 3, and 4 |
| Decimal NUMERIC and ordered duplicate-key metadata | Task 3 |
| ValidationIssue persistence without Phase 5 rules | Tasks 3, 4, and 9 |
| Fixed atomic initial audit | Task 7 |
| Canonical fingerprint and Decimal normalization | Task 6 |
| Database-authoritative idempotency race handling | Tasks 7–8 |
| Sequential replay/conflict and concurrent proof | Tasks 7–8 and 10 |
| Four routes plus health/readiness | Tasks 9–11 |
| Dedicated schemas, errors, sessions, and safe HTTP mapping | Tasks 5, 9–10 |
| Real PostgreSQL and infrastructure-independent domain tests | Tasks 2, 4, 7–11 |
| No new runtime dependency | Global constraints and Task 11 |
| Independent audit, remediation, PR, merge, and cleanup | Tasks 12–13 |

Final plan checks:

- no unresolved placeholders;
- no implementation code is being added by this planning task;
- no task introduces a Phase 3+ dependency;
- no task changes the Phase 1 domain contract;
- interfaces remain consistent from mappers to repositories to application to API;
- task boundaries are reviewable and each implementation task has a concrete
  red/green/regression/commit cycle;
- this plan directs execution without reproducing the complete design text.

After this plan is committed, the next execution choice is either
`superpowers:subagent-driven-development` (recommended) or
`superpowers:executing-plans`. Neither choice begins in this task; M2B
remains NOT STARTED until a later explicit implementation task.
