# Phase 1 Domain Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved pure-Python Phase 1 domain contract, including immutable supporting records, the `Order` aggregate, exhaustive lifecycle transitions, retry/reopen recovery, and scenario verification.

**Architecture:** Keep the domain in a small responsibility-oriented package under `src/opsflow/domain/`. Frozen dataclasses represent immutable snapshots; `Order` owns the explicit state-transition rules and recovery operations. The package has no database, HTTP, AI, workflow, integration, repository, service, event-bus, or dependency-injection knowledge.

**Tech Stack:** Python 3.12, standard-library `dataclasses`, `Enum`, `Decimal`, `UUID`, `date`, timezone-aware `datetime`, pytest, Ruff, mypy, and the repository’s existing `uv`/`uv.lock` environment. No new runtime dependencies.

**Spec:** [docs/architecture/domain-model.md](../../architecture/domain-model.md)

## Global Constraints

- Work only on the designated Phase 1 branch; M1B is the first implementation milestone after M1A.
- Implement only M1B–M1E in this plan; M1F is an independent audit in a fresh context and has no implementation tasks here.
- Use only standard-library domain types and existing development dependencies; add zero runtime dependencies.
- Keep all domain objects immutable snapshots; state operations return new validated `Order` instances.
- Preserve the boundary: AI interprets; deterministic Python controls structural validity, lifecycle legality, and side-effect authorization.
- The domain must not import PostgreSQL, SQLAlchemy, FastAPI, Docker, network clients, AI providers, n8n, Odoo, HubSpot, Gmail, Slack, or integration modules.
- Do not add persistence, migrations, API endpoints/schemas, document parsing, business validation rules, external adapters, event infrastructure, repositories, services, factories without a demonstrated need, or Phase 2+ functionality.
- Keep `OrderLine.quantity` and all prices as `Decimal`; reject non-finite numeric values and binary floats.
- Keep `Order.lines` and `Order.source_documents` as tuples in the public contract.
- Enforce currency shape only (`None` or exactly three uppercase ASCII letters); do not add a supported-currency set.
- Enforce only the legal transitions in the spec; `retry()` and `reopen()` are explicit operations and are not generic transitions.
- Tests must not start PostgreSQL, Docker, an API server, use network access, call live AI, or cause external mutations.

## File map and interfaces

| Milestone | Files created | Responsibility |
| --- | --- | --- |
| M1B | `src/opsflow/domain/__init__.py` | Small public export surface for the domain package. |
| M1B | `src/opsflow/domain/errors.py` | `DomainValidationError` and `InvalidStateTransitionError`. |
| M1B | `src/opsflow/domain/records.py` | `SourceDocumentType`, `ValidationSeverity`, `OrderLine`, `SourceDocument`, `ValidationIssue`, and `AuditEvent`. |
| M1C | `src/opsflow/domain/order.py` | `OrderState`, immutable `Order`, construction, structural validation, and tuple snapshots. |
| M1B–M1E | `tests/unit/domain/*.py` | Focused record, aggregate, transition-matrix, and scenario tests. |

The public interfaces produced by the implementation are:

```python
class DomainValidationError(ValueError):
    pass


class InvalidStateTransitionError(DomainValidationError):
    current_state: OrderState
    requested_state: OrderState | None
    operation: str


class OrderState(Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    EXTRACTED = "EXTRACTED"
    VALIDATED = "VALIDATED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    SYNCING = "SYNCING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_FINAL = "FAILED_FINAL"


class Order:
    @classmethod
    def received(
        cls,
        *,
        id: UUID,
        customer_reference: str | None = None,
        po_number: str | None = None,
        order_date: date | None = None,
        requested_delivery_date: date | None = None,
        currency: str | None = None,
        lines: tuple[OrderLine, ...] = (),
        source_documents: tuple[SourceDocument, ...] = (),
    ) -> "Order":
        raise NotImplementedError

    def transition_to(self, target: OrderState) -> "Order":
        raise NotImplementedError

    def retry(self) -> "Order":
        raise NotImplementedError

    def reopen(self) -> "Order":
        raise NotImplementedError
```

The method bodies above are shown as explicit implementation boundaries; their
behavior is defined by the task sections and the authoritative domain spec.

---

### Task 1: M1B — Supporting Domain Records

**Files:**
- Create: `src/opsflow/domain/__init__.py`
- Create: `src/opsflow/domain/errors.py`
- Create: `src/opsflow/domain/records.py`
- Create: `tests/unit/domain/test_records.py`
- Create: `tests/unit/domain/test_domain_imports.py`

**Interfaces:**
- Consumes: only Python standard-library types and `DomainValidationError`.
- Produces: frozen records and enums imported from `opsflow.domain`, with
  fields exactly matching [the domain contract](../../architecture/domain-model.md).

The exact planned signatures are:

```python
class SourceDocumentType(Enum):
    EMAIL_BODY = "EMAIL_BODY"
    PDF = "PDF"
    XLSX = "XLSX"
    CSV = "CSV"
    FORM = "FORM"


class ValidationSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class OrderLine:
    id: UUID
    sku: str | None
    description: str | None
    quantity: Decimal
    submitted_price: Decimal | None
    trusted_catalogue_price: Decimal | None


@dataclass(frozen=True, slots=True)
class SourceDocument:
    id: UUID
    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None
    storage_reference: str | None
    metadata: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    rule_code: str
    severity: ValidationSeverity
    field: str | None
    expected: object | None
    actual: object | None
    explanation: str


@dataclass(frozen=True, slots=True)
class AuditEvent:
    id: UUID
    order_id: UUID
    event_type: str
    actor: str
    occurred_at: datetime
    description: str
```

- [ ] **Step 1: Write the failing structural tests**

Add tests for positive quantity, zero/negative quantity, NaN/infinity,
negative prices, and missing SKU plus useful description. Add tests for a
valid source, malformed SHA-256, blank name, blank MIME type, valid severity
and source-type enum members, timezone-aware audit time, and naive audit time.
Use real values such as:

```python
def test_order_line_rejects_zero_quantity() -> None:
    with pytest.raises(DomainValidationError):
        OrderLine(UUID(int=1), "SKU-1", None, Decimal("0"), None, None)
```

Also assert frozen behavior by attempting to assign a field and expecting
`dataclasses.FrozenInstanceError`, and assert that metadata is a tuple rather
than a mutable mapping. Keep each test focused on one behavior.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
uv run pytest tests/unit/domain/test_records.py -q
```

Expected: collection fails because `opsflow.domain.records` and the domain
errors do not yet exist. If collection reports an import or test typo rather
than the missing implementation, correct the test and rerun until the
failure is caused by the absent domain records.

- [ ] **Step 3: Implement the minimal record and error types**

Create `DomainValidationError(ValueError)` with no HTTP behavior. Implement
the four frozen dataclasses and two enums. Validate in `__post_init__`:

- quantity and each supplied price are `Decimal`, finite, and satisfy the
  positive/non-negative bounds;
- at least one SKU or non-blank description exists;
- source name and MIME type are non-blank;
- SHA-256 matches exactly 64 ASCII hexadecimal characters;
- required audit strings are non-blank and `occurred_at` is timezone-aware;
- metadata is already a tuple of string pairs and remains unchanged.

Do not parse files, normalize external metadata, inspect MIME content, emit
events, or create integration behavior.

- [ ] **Step 4: Run focused tests to verify GREEN**

Run:

```bash
uv run pytest tests/unit/domain/test_records.py -q
uv run ruff check src/opsflow/domain tests/unit/domain
uv run mypy src/opsflow/domain
```

Expected: all record tests pass, Ruff reports no violations, and mypy exits
zero. Fix implementation defects without weakening assertions.

- [ ] **Step 5: Add the package export surface and import-independence test**

Export the supporting records, enums, and errors from
`src/opsflow/domain/__init__.py`. In `test_domain_imports.py`, import the
package and inspect loaded domain modules or source text to assert that the
domain package imports none of `fastapi`, `sqlalchemy`, `asyncpg`, `alembic`,
AI-provider, or integration modules. The test must run without PostgreSQL or
Docker.

- [ ] **Step 6: Run the import test and commit M1B**

Run:

```bash
uv run pytest tests/unit/domain/test_domain_imports.py -q
git diff --check
git add src/opsflow/domain tests/unit/domain
git commit -m "feat: add Phase 1 supporting domain records"
```

The commit must contain only M1B domain records, errors, exports, and their
focused tests.

### Task 2: M1C — Order Aggregate

**Files:**
- Create: `src/opsflow/domain/order.py`
- Modify: `src/opsflow/domain/__init__.py`
- Create: `tests/unit/domain/test_order.py`

**Interfaces:**
- Consumes: `OrderLine`, `SourceDocument`, and `DomainValidationError` from
  M1B.
- Produces: `OrderState`, immutable `Order`, and the `Order.received`,
  `transition_to`, `retry`, and `reopen` method names used by M1D.

Use these exact aggregate fields:

```python
@dataclass(frozen=True, slots=True)
class Order:
    id: UUID
    customer_reference: str | None = None
    po_number: str | None = None
    order_date: date | None = None
    requested_delivery_date: date | None = None
    currency: str | None = None
    lines: tuple[OrderLine, ...] = ()
    source_documents: tuple[SourceDocument, ...] = ()
    state: OrderState = OrderState.RECEIVED
    failure_origin: OrderState | None = None
```

`Order.received` takes the same fields except `state` and
`failure_origin`, requires `id: UUID`, defaults both collections to empty
tuples, and always returns a `RECEIVED` snapshot. Direct construction remains
validated so every returned aggregate is safe. Currency validation accepts
`None` or exactly three uppercase ASCII letters and has no supported-currency
allowlist. A `RECEIVED` aggregate may have no business fields and no lines.

- [ ] **Step 1: Write the failing aggregate tests**

Write tests for an empty pre-extraction order, `Order.received`, tuple
collections, frozen assignment failure, invalid currency shapes, and a
structurally valid code outside any supported-currency set. Include a test
that invalid nested records cannot be hidden inside a valid order.

- [ ] **Step 2: Run the focused tests to verify RED**

Run:

```bash
uv run pytest tests/unit/domain/test_order.py -q
```

Expected: collection fails because `opsflow.domain.order` and `OrderState`
do not yet exist.

- [ ] **Step 3: Implement the minimal aggregate**

Define the twelve exact `OrderState` values from the spec. Implement the
frozen `Order` dataclass, the `received` constructor, tuple/type validation,
currency-shape validation, and nested-record validation. Keep transition
logic centralized for M1D; M1C only supplies the aggregate and its
structural invariants.

- [ ] **Step 4: Run aggregate tests and the existing suite**

Run:

```bash
uv run pytest tests/unit/domain/test_order.py -q
uv run pytest tests/unit/domain -q
uv run ruff check src/opsflow/domain tests/unit/domain
uv run mypy src/opsflow/domain
```

Expected: focused and existing domain tests pass, with no infrastructure
connection attempted.

- [ ] **Step 5: Commit M1C**

```bash
git diff --check
git add src/opsflow/domain/order.py src/opsflow/domain/__init__.py tests/unit/domain/test_order.py
git commit -m "feat: add immutable Order aggregate"
```

### Task 3: M1D — State Machine & Recovery Semantics

**Files:**
- Modify: `src/opsflow/domain/order.py`
- Modify: `src/opsflow/domain/errors.py`
- Modify: `src/opsflow/domain/__init__.py`
- Create: `tests/unit/domain/test_transitions.py`

**Interfaces:**
- Consumes: `Order` and `OrderState` from M1C.
- Produces: `Order.transition_to(target)`, `Order.retry()`,
  `Order.reopen()`, and `InvalidStateTransitionError` with public
  `current_state`, `requested_state`, and `operation` attributes.

Use one centralized immutable transition mapping with exactly these 17 pairs:

```python
NORMAL_TRANSITIONS = {
    RECEIVED: {PROCESSING},
    PROCESSING: {EXTRACTED, FAILED_RETRYABLE, FAILED_FINAL},
    EXTRACTED: {VALIDATED, FAILED_RETRYABLE, FAILED_FINAL},
    VALIDATED: {NEEDS_REVIEW, READY_FOR_APPROVAL},
    NEEDS_REVIEW: {VALIDATED, REJECTED},
    READY_FOR_APPROVAL: {APPROVED, REJECTED},
    APPROVED: {SYNCING},
    SYNCING: {COMPLETED, FAILED_RETRYABLE, FAILED_FINAL},
    COMPLETED: set(),
    REJECTED: set(),
    FAILED_RETRYABLE: set(),
    FAILED_FINAL: set(),
}
```

The implementation may use another immutable representation, but it must
have the same content and remain the single source for normal transitions.

- [ ] **Step 1: Write the exhaustive transition-matrix test**

Define the complete `OrderState` list and expected transition mapping in the
test. For every state pair, construct an order in the current state and call
`transition_to(target)`. Assert success for the 17 approved pairs and
`InvalidStateTransitionError` for every other pair, including self-pairs.

```python
for current in OrderState:
    for target in OrderState:
        order = make_order(state=current)
        if target in EXPECTED[current]:
            assert order.transition_to(target).state is target
        else:
            with pytest.raises(InvalidStateTransitionError):
                order.transition_to(target)
```

Add explicit assertions that only `APPROVED -> SYNCING` succeeds, that
`COMPLETED` and `FAILED_FINAL` have no outgoing transitions, and that the
error exposes the current state, requested state, and operation.

- [ ] **Step 2: Run the matrix to verify RED**

Run:

```bash
uv run pytest tests/unit/domain/test_transitions.py -q
```

Expected: the test fails because transition methods and
`InvalidStateTransitionError` are not implemented.

- [ ] **Step 3: Implement normal transitions minimally**

Add `InvalidStateTransitionError` with the required attributes and a clear
message. Implement `transition_to` against the centralized table. Return a
new `Order` using `dataclasses.replace`; never mutate the original. For
`FAILED_RETRYABLE` and `FAILED_FINAL`, set `failure_origin` to the current
state. For every successful non-failure transition, clear
`failure_origin`. Reject ordinary calls from `FAILED_RETRYABLE` and
`REJECTED`, even when the target appears to be a useful recovery destination.

- [ ] **Step 4: Add retry tests before implementing retry**

Test failures from `PROCESSING`, `EXTRACTED`, and `SYNCING`, asserting the
exact recorded origin. Test `retry()` returns the original operational state,
clears `failure_origin`, leaves the failed snapshot unchanged, and cannot
accept a destination argument. Test `retry()` raises from every state other
than `FAILED_RETRYABLE`, including `FAILED_FINAL`, `COMPLETED`, and
`REJECTED`. Test a malformed missing origin raises a domain transition error.

- [ ] **Step 5: Run retry tests to verify RED, then implement retry**

Run:

```bash
uv run pytest tests/unit/domain/test_transitions.py -q
```

Expected: the new retry tests fail because `retry()` is absent or incomplete.
Implement `retry()` to use only the recorded `failure_origin`; it must not
accept a target parameter or choose a fallback. Restore exactly that state
and clear the active failure origin.

- [ ] **Step 6: Add reopen tests before implementing reopen**

Test that `REJECTED.reopen()` returns a new `NEEDS_REVIEW` order, clears
`failure_origin`, and leaves the rejected snapshot unchanged. Test that
`reopen()` raises from all other states and that ordinary transition calls
cannot reach recovery states from `REJECTED`.

- [ ] **Step 7: Run reopen tests to verify RED, then implement reopen**

Run:

```bash
uv run pytest tests/unit/domain/test_transitions.py -q
```

Expected: the new reopen tests fail until the explicit operation exists.
Implement `reopen()` with only the `REJECTED -> NEEDS_REVIEW` behavior.

- [ ] **Step 8: Run the complete M1D verification and commit**

Run:

```bash
uv run pytest tests/unit/domain/test_transitions.py -q
uv run pytest tests/unit/domain -q
uv run ruff check src/opsflow/domain tests/unit/domain
uv run mypy src/opsflow/domain
git diff --check
git add src/opsflow/domain tests/unit/domain/test_transitions.py
git commit -m "feat: enforce domain lifecycle recovery rules"
```

Expected: the exhaustive matrix and recovery tests pass, with 17 legal
normal transitions and all remaining state pairs rejected.

### Task 4: M1E — Scenario Verification & Contract Hardening

**Files:**
- Create: `tests/unit/domain/test_scenarios.py`
- Modify: `tests/unit/domain/test_domain_imports.py` only if the import check
  needs to cover a newly introduced standard-library module
- Modify: `docs/development/development-guide.md` only if the verified
  domain command needs durable documentation after it has actually run

**Interfaces:**
- Consumes: the completed M1B–M1D domain package and the authoritative
  contract.
- Produces: no new production architecture; only regression evidence and
  minimal contract corrections if a verified defect is found.

- [ ] **Step 1: Add the happy-path scenario test**

Build one order through:

```text
RECEIVED -> PROCESSING -> EXTRACTED -> VALIDATED
-> READY_FOR_APPROVAL -> APPROVED -> SYNCING -> COMPLETED
```

Assert each returned snapshot has the expected state, each prior snapshot is
unchanged, and the completed snapshot rejects transition, retry, and reopen.

- [ ] **Step 2: Add review/revalidation and reject/reopen scenarios**

Test:

```text
VALIDATED -> NEEDS_REVIEW -> VALIDATED -> READY_FOR_APPROVAL
```

and:

```text
READY_FOR_APPROVAL -> REJECTED -> reopen() -> NEEDS_REVIEW
             -> VALIDATED -> READY_FOR_APPROVAL
```

Assert that rejection can be recovered only with `reopen()`, not by selecting
an arbitrary target in `transition_to`.

- [ ] **Step 3: Add retryable processing, extraction, and sync scenarios**

Exercise each failure origin:

```text
PROCESSING -> FAILED_RETRYABLE -> retry() -> PROCESSING
EXTRACTED  -> FAILED_RETRYABLE -> retry() -> EXTRACTED
SYNCING    -> FAILED_RETRYABLE -> retry() -> SYNCING
```

Assert that every retry restores exactly its origin and clears
`failure_origin`; `FAILED_FINAL` remains terminal with an informational
origin and no recovery operation.

- [ ] **Step 4: Run the domain suite with infrastructure unavailable**

With PostgreSQL stopped, Docker stopped, and no API server running, execute:

```bash
uv run pytest tests/unit/domain -q
```

Expected: the full domain suite passes without network access or service
startup. Record the observed result in the milestone closeout; do not invent
a result if the local environment cannot satisfy the command.

- [ ] **Step 5: Run the full repository quality gates**

Run the existing documentation-compatible quality commands:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
uv run pytest
uv build
npm --prefix web ci
npm --prefix web run lint
npm --prefix web run build
git diff --check
```

The domain suite must remain independent even though the repository’s full
backend suite may require PostgreSQL according to the development guide.

- [ ] **Step 6: Inspect scope and commit M1E**

Inspect `git diff --stat`, `git diff`, imports, dependency files, and the
complete transition matrix. Confirm no persistence, API, integration,
document, AI, n8n, frontend, or later-phase behavior entered the change.

```bash
git diff --check
git add tests/unit/domain docs/development/development-guide.md
git commit -m "test: harden Phase 1 domain contract"
```

## Milestone verification and closeout gate

M1B–M1E implementation is ready for independent review only when:

- the domain unit suite passes with PostgreSQL and Docker unavailable;
- every legal transition and every unlisted transition pair is tested;
- retry restores only the recorded origin;
- reopen returns only `NEEDS_REVIEW` from `REJECTED`;
- `COMPLETED` and `FAILED_FINAL` are terminal;
- only `APPROVED` enters `SYNCING`;
- package imports remain infrastructure-independent;
- Ruff, formatting, mypy, pytest, build, frontend lint, and frontend build
  pass with observed output;
- no runtime dependency, migration, endpoint, schema, integration, or
  future-phase functionality was introduced.

M1F — Independent Phase 1 Audit is not implemented by this plan. A fresh
context must review the contract, implementation, tests, scope, and CI state
after M1E.

## Commit boundaries

Use one focused commit per implementation milestone:

1. `feat: add Phase 1 supporting domain records` — M1B;
2. `feat: add immutable Order aggregate` — M1C;
3. `feat: enforce domain lifecycle recovery rules` — M1D;
4. `test: harden Phase 1 domain contract` — M1E.

Do not squash or combine these implementation commits unless the designated
review process explicitly requires it. M1A itself is documentation-only and
uses one separate coherent commit: `docs: define Phase 1 domain contract`.
