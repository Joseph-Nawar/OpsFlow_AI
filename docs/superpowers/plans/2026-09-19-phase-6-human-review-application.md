# Phase 6 — Human Review Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:executing-plans`.
> Single-agent sequential execution is mandatory for this repository. Do not
> use subagents, `subagent-driven-development`, spawned reviewers, parallel
> agents, or multi-agent workflows unless the user explicitly authorizes them
> for a future task.

**Status:** Implementation plan only. No Phase 6 production implementation,
migration, dependency, frontend component, test, status closeout, audit file,
or PR is created by this document.

**Planning baseline:** `phase/6-human-review-application` at
`c903130ff8fabd188b4cc402a0b610adcbc46d48`, three commits ahead of
`5ac96d96da72be185b3b7cc9b24ad33fb72d7849` and zero behind.

**Goal:** Build the approved human-review and approval application while
preserving the Phase 5 deterministic trust boundary.

**Architecture:** Human corrections are immutable untrusted `ReviewDraft`
revisions. Existing deterministic Phase 5 validation converts corrected drafts
into trusted data. Python/FastAPI owns authorization, concurrency, legal state
transitions, persistence, and audit; React renders the operator workflow but
never becomes an authority.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async,
PostgreSQL 16, Alembic, pytest, React 19, TypeScript, Vite, React Router
Declarative Mode, Vitest, React Testing Library, native fetch, and GitHub
Actions.

**Spec:**
`docs/superpowers/specs/2026-09-19-phase-6-human-review-application-design.md`

## Global Constraints

- The approved Phase 6 design is authoritative. If implementation reveals a genuine contradiction, stop and report it instead of silently revising the design.
- AI interprets; deterministic software validates; humans may correct or authorize; the UI never bypasses domain or application rules.
- The Phase 5 `ExtractionDraft` snapshot remains immutable, untrusted, and the sole anchor for original source identity, notes, and evidence.
- Human corrections live only in immutable complete `ReviewDraft` revisions and become trusted order data only through deterministic validation and `ValidatedOrderData` promotion.
- The browser never determines state, actor, role, approval authority, trusted customer/product identity, validation outcome, audit actor, revision number, or old values.
- The existing pure `validation.engine.validate(...)` is the only validation engine; no LLM validation, routing, or approval call is added.
- The Phase 1 `OrderState` enum and legal transitions remain unchanged. No Phase 6 state, approval-level column, or reopen route is introduced.
- Legal review routes are `NEEDS_REVIEW → VALIDATED → NEEDS_REVIEW` and `NEEDS_REVIEW → VALIDATED → READY_FOR_APPROVAL`; approval is only `READY_FOR_APPROVAL → APPROVED`; rejection is only from `NEEDS_REVIEW` or `READY_FOR_APPROVAL`; retry uses the persisted failure origin.
- Editing is legal only in `NEEDS_REVIEW`; approve is legal only in `READY_FOR_APPROVAL`; retry is legal only in `FAILED_RETRYABLE` for `REVIEWER`.
- Persist exactly one focused immutable `review_revisions` concept. Do not add event sourcing, a generic version table, a field-change table, a workflow engine, or a generic retry framework.
- Migration `0004_phase6_review_revisions` must have `down_revision = "0003_phase5_extraction_snapshots"` and must preserve composite snapshot ownership.
- Revision payload and changes are canonical, complete, server-computed, append-only, and strict. No revision is inserted for a no-op.
- Save & revalidate uses a typed candidate, preflight ETag/state/no-op checks, explicit read-transaction rollbacks, one provider call outside any DB transaction, one local-facts read transaction, one engine call outside any DB transaction, one final locked transaction, and one commit.
- The reference-data read closes its database read transaction before invoking the provider. No provider, network, AI, or external adapter call runs inside the final transaction.
- M6B owns read-side ETag generation and parsing machinery; M6C owns `If-Match` enforcement for Save & revalidate; M6D reuses the same precondition contract for approve, reject, and retry.
- Strong ETag input includes `order_id`, state, failure origin, latest review revision number/ID, and latest audit-event ID. Do not add `orders.version`.
- Missing `If-Match` maps to `428 Precondition Required`; malformed or stale values map to `412 Precondition Failed` with safe structured errors.
- Authorization is deny-by-default and server-derived from immutable `OperatorContext` and `OperatorRole`; client actor/role claims never grant authority.
- Development authentication uses multiple configured `OPSFLOW_REVIEW_DEV_OPERATORS` records, constant-time token comparison, and no committed usable credentials. No OAuth/OIDC, accounts, passwords, sessions, refresh tokens, JWT issuance, or IAM system is added.
- Phase 6 policy is explicitly composed as `ValidationPolicy(supported_currencies=("USD",), price_tolerance_fraction=Decimal("0.05"), high_value_threshold=Decimal("1000"))`; tests inject alternate policies directly.
- Save & revalidate captures exactly one review-time date through an injectable date provider; `ValidationEngine` remains clock-free.
- Demo trusted reference data uses only the synthetic records locked by the approved design and remains network-free, credential-free, and `$0`.
- No n8n, Gmail, Slack, Odoo, HubSpot, ERP/CRM mutation, stock reservation, raw-file persistence, OCR, object storage, PDF/email viewer, broad catalogue search, or Phase 7–12 implementation is included.
- Use ordinary React state, native `fetch`, a small typed API layer, semantic accessible HTML, focused CSS, Vite `/v1` proxying, and React Router Declarative Mode. Do not add Redux, Zustand, TanStack Query, Tailwind, Material UI, shadcn, a design system, a meta-framework, or a generated API client.
- Only the frontend packages explicitly approved by the design may be added: current stable `react-router`, Vitest, React Testing Library, `@testing-library/user-event`, DOM matchers, and jsdom support.
- Every implementation task follows RED → intended failure → minimal implementation → focused GREEN → relevant regression checks → diff inspection → one coherent commit.
- No task may weaken existing assertions, skip tests, add sleeps, swallow broad exceptions, call live providers, use real credentials, or change status documentation before its milestone closeout gate.

## Review Focus

These five risks are mandatory review targets. Each is pinned to the owning
test task rather than left as narrative guidance.

1. **Stale operator tab / retry-state ABA:** old ETags must not authorize a later mutation generation after `FAILED_RETRYABLE` returns to the same state and failure origin. Test ownership: Task 10 command integration tests and Task 15 frontend stale-screen coverage.
2. **Invalid human correction:** revision and issues persist, the trusted order graph remains unchanged, and the final state is `NEEDS_REVIEW`. Test ownership: Task 8 PostgreSQL revalidation tests and Task 14 component behavior tests.
3. **Network provider transaction boundary:** provider and reference-data lookup run with `session.in_transaction() is False`. Test ownership: Task 5 reference-data read tests and Task 8 revalidation boundary tests.
4. **High-value authorization:** ordinary approvers cannot approve high-value orders, elevated approvers can, and ordinary approvers can still reject high-value ready orders. Test ownership: Task 10 command tests and Task 15 action UI tests.
5. **Original evidence versus human changes:** original extraction evidence is immutable provenance and never presented as proof of later human values. Test ownership: Task 5 detail contract tests and Task 13 detail component tests.

## Repository Findings and File Map

The current repository uses `src/opsflow/domain/records.py` for supporting
domain records, `src/opsflow/database.py` for the async database engine, and
router-local error mapping in `src/opsflow/api/orders.py`. The requested
conceptual paths `src/opsflow/domain/models.py`,
`src/opsflow/persistence/database.py`, and `src/opsflow/api/errors.py` do not
exist. The implementation must follow these existing conventions instead of
creating aliases solely to match conceptual names.

### Planned backend creates

- `src/opsflow/review/__init__.py` — narrow exports for review contracts and immutable operator types.
- `src/opsflow/review/contracts.py` — `ReviewLine`, `ReviewDraft`, `ReviewChange`, `ReviewRevision`, `OperatorRole`, and `OperatorContext`.
- `src/opsflow/review/serialization.py` — strict canonical draft/change serialization, effective-draft projection, changed-field computation, and `ExtractionDraft` composition.
- `src/opsflow/review/concurrency.py` — canonical strong ETag construction and focused `If-Match` parsing/comparison helpers.
- `src/opsflow/review/auth.py` — configured-operator resolution and fixed Phase 6 capability checks.
- `src/opsflow/review/composition.py` — explicit synthetic policy, demo provider, injectable review-date provider, and runtime container.
- `src/opsflow/application/review_reads.py` — queue/detail/reference-data application reads and stable read DTOs.
- `src/opsflow/application/review_revalidation.py` — Save & revalidate operation and result type.
- `src/opsflow/application/review_commands.py` — approve, reject, and retry application commands and result type.
- `src/opsflow/api/review.py` — dedicated review router and transport error mapping.
- `src/opsflow/api/review_schemas.py` — request and response models for the narrow review HTTP surface.
- `alembic/versions/0004_phase6_review_revisions.py` — review revision schema migration.

### Planned backend modifications

- `src/opsflow/settings.py` — parse and validate the configured development operator collection.
- `src/opsflow/main.py` — attach review runtime/auth dependencies to application state and include the review router.
- `src/opsflow/domain/order.py` — add only the narrow `promote_reviewed_data(...)` operation legal from `NEEDS_REVIEW`.
- `src/opsflow/application/errors.py` — add a focused safe Phase 6 error taxonomy while retaining Phase 1–5 errors.
- `src/opsflow/persistence/models.py` — add `ReviewRevisionModel` and the ORM composite ownership constraint metadata.
- `src/opsflow/persistence/mappers.py` — add typed review-revision mapping without changing extraction-snapshot mapping semantics.
- `src/opsflow/persistence/repositories.py` — add review revision, latest-audit-generation, queue, detail dependency, and final-write helpers with caller-owned transactions.
- `src/opsflow/persistence/__init__.py` — export `ReviewRevisionModel` with the existing persistence model exports.
- `tests/unit/application/test_errors.py` — safe error hierarchy/privacy assertions.
- `tests/unit/domain/test_order.py` — reviewed-data promotion and invariant assertions.
- `tests/unit/persistence/test_models.py` — review ORM metadata assertions.
- `.env.example` — add the empty `OPSFLOW_REVIEW_DEV_OPERATORS=` configuration line; never add a usable credential.

### Planned backend test creates/modifications

- `tests/unit/review/test_contracts.py` — immutable review/operator value contracts.
- `tests/unit/review/test_serialization.py` — canonical payloads, strict deserialization, projection, composition, changes, and no-op behavior.
- `tests/unit/review/test_concurrency.py` — ETag canonical input and precondition semantics.
- `tests/unit/review/test_auth.py` — operator parsing, constant-time resolution seam, capabilities, and safe missing/unknown credentials.
- `tests/unit/review/test_composition.py` — explicit policy/date/provider composition and override seams.
- `tests/unit/persistence/test_review_mappers.py` — revision ORM mapper round trips and strict JSON shape.
- `tests/unit/application/test_review_reads.py` — read DTO/action projection and provider-boundary unit tests.
- `tests/unit/application/test_review_revalidation.py` — Save & revalidate application orchestration and transaction seams.
- `tests/unit/application/test_review_commands.py` — command authorization, legal states, audit descriptions, and atomic mutation behavior.
- `tests/integration/test_phase6_persistence.py` — migration, constraints, revision ownership, append-only reads, and PostgreSQL persistence.
- `tests/integration/test_phase6_reads.py` — queue/detail/reference-data HTTP and PostgreSQL behavior.
- `tests/integration/test_phase6_revalidation.py` — correction, promotion, stale state/facts/ETag, rollback, and transaction-boundary behavior.
- `tests/integration/test_phase6_commands.py` — approve/reject/retry, high-value matrix, ABA, locking, rollback, and safe errors.
- `tests/integration/test_phase6_auth.py` — bearer transport and multiple configured operators.

### Planned frontend creates/modifications

- `web/src/app/Router.tsx` — Declarative Mode router shell for `/review` and `/review/:orderId`.
- `web/src/api/review.ts` — typed native-fetch client, response parsing, ETag storage, bearer header, and safe error decoding.
- `web/src/auth/operatorAccess.ts` — session-only credential access form state and backend-resolved operator summary.
- `web/src/auth/OperatorAccessForm.tsx` — labelled credential entry, sign-out, and backend-resolved actor/role display.
- `web/src/pages/ReviewQueuePage.tsx` — queue filters, pagination, and explicit state rendering.
- `web/src/pages/ReviewDetailPage.tsx` — detail orchestration and mutation refresh behavior.
- `web/src/components/review/ReviewEvidencePanel.tsx` — original extraction/evidence and source limitation presentation.
- `web/src/components/review/ReviewReferencePanel.tsx` — current trusted reference-data panel and retry/unavailable state.
- `web/src/components/review/ReviewHistoryPanel.tsx` — revision history and existing audit-history read.
- `web/src/components/review/ReviewDraftForm.tsx` — labelled editable draft and ordered-line interaction.
- `web/src/components/review/ReviewActions.tsx` — backend-computed approve/reject/retry controls and safe action errors.
- `web/src/test/setup.ts` — jsdom and DOM matcher setup.
- `web/src/test/fixtures.ts` — typed synthetic review responses and operator fixtures without credentials.
- `web/vitest.config.ts` — Vitest jsdom/test setup configuration.

### Planned frontend/CI modifications

- `web/package.json` and `web/package-lock.json` — only approved React Router/testing packages and the `test` script.
- `web/vite.config.ts` — local `/v1` proxy to FastAPI.
- `web/src/App.tsx`, `web/src/main.tsx`, and `web/src/index.css` — replace the foundation screen with the review shell and focused accessible styling.
- `Makefile` — make `frontend-check` run frontend tests in addition to lint/build.
- `.github/workflows/ci.yml` — run the frontend test script in the existing Frontend job.

### Explicitly not in the file map

No Phase 6 implementation is created by this plan. Later implementation tasks
must not add a public generic state endpoint, generic command bus, unit-of-work
framework, service locator, permissions framework, generated API client,
global state library, design system, object storage, raw source persistence,
external integration, Phase 7+ module, or pre-created M6F audit report.

## Implementation Order and Review Gates

Execute Tasks 1–15 strictly in numerical order, one task at a time. Each task
ends with its focused RED/GREEN or characterization verification, relevant
regression checks, diff inspection, and one coherent commit. No task begins
until the preceding task's commit is present and its interface is stable.

Milestone gates are:

1. Tasks 1–5 produce the M6B backend read foundation. Push the exact candidate, require Backend/Frontend/Secret scan CI success, obtain independent review, then create a separate status-only M6B closeout commit only after independent PASS.
2. Tasks 6–8 produce M6C Save & revalidate. Apply the same candidate, CI, independent review, and status-only closeout sequence.
3. Tasks 9–10 produce M6D commands/API. Apply the same sequence.
4. Tasks 11–15 produce M6E frontend and cross-boundary hardening. Apply the same sequence. Phase 6 remains `IN PROGRESS` and M6F remains `NOT STARTED`.
5. M6F is a later independent read-only whole-Phase-6 audit boundary. It creates the audit report only after M6E passes and must not be pre-created by this plan.

An implementation worker must stop and report when the approved design is
contradicted, when a new product-level decision is needed, when scope must
expand, or when an independent review identifies a decision not resolved by
the approved design. Routine approval is not a substitute for these gates.

## M6B — Review Persistence, Authorization & Read Model

M6B is backend-only. It owns review value contracts, persistence,
authentication, explicit runtime composition, read-side concurrency machinery,
queue/detail/reference-data reads, and backend tests. It does not implement
Save & revalidate, approve, reject, retry, or React.

### Task 1: Add immutable review and operator contracts

**Files:**

- Create: `src/opsflow/review/__init__.py`
- Create: `src/opsflow/review/contracts.py`
- Test: `tests/unit/review/test_contracts.py`

**Interfaces:**

- Consumes: existing `ExtractionDraft` field types, Phase 1 `OrderState`, Phase 1 `ValidationIssue`, and Phase 5 `ValidatedOrderData` conventions.
- Produces the following exact immutable interfaces for Tasks 2–15:

```python
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID


class OperatorRole(Enum):
    REVIEWER = "REVIEWER"
    APPROVER = "APPROVER"
    ELEVATED_APPROVER = "ELEVATED_APPROVER"


@dataclass(frozen=True, slots=True)
class OperatorContext:
    actor: str
    role: OperatorRole


@dataclass(frozen=True, slots=True)
class ReviewLine:
    sku: str | None
    description: str | None
    quantity: Decimal | None
    submitted_price: Decimal | None


@dataclass(frozen=True, slots=True)
class ReviewDraft:
    customer_name: str | None
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    lines: tuple[ReviewLine, ...]


@dataclass(frozen=True, slots=True)
class ReviewChange:
    field_path: str
    old_value: object
    new_value: object


@dataclass(frozen=True, slots=True)
class ReviewRevision:
    id: UUID
    order_id: UUID
    extraction_snapshot_id: UUID
    revision_number: int
    payload: ReviewDraft
    changes: tuple[ReviewChange, ...]
    actor: str
    created_at: datetime
```

Structural rules are exact: all records are frozen/slotted; `OperatorContext`
has a nonblank actor bounded to 128 characters and one `OperatorRole`; optional
text is null or nonblank; dates are exact `date` values or null; decimals are
finite `Decimal` values or null; lines are immutable tuples; revision numbers
are positive; revision timestamps are timezone-aware; and review values do not
require Phase 1 business validity. A `ReviewLine` may retain missing SKU,
quantity, price, or description so the deterministic engine can report the
appropriate issue. It must not create an `OrderLine`.

**Steps:**

- [ ] Write tests for exact enum members, frozen/slotted records, bounded actors, strict optional text/date/Decimal boundaries, immutable tuple collections, positive revision numbers, timezone-aware timestamps, and revision ownership fields.
- [ ] Run `uv run pytest tests/unit/review/test_contracts.py -q --no-cov`; the initial failure must identify the absent review package.
- [ ] Implement only the standard-library contract records and structural invariants. Do not import FastAPI, SQLAlchemy, settings, providers, or browser types.
- [ ] Add tests proving invalid business quantities/prices/currencies remain representable in `ReviewDraft` while mutable collections, floats, non-finite decimals, blank optional text, invalid roles, and unbounded actors are rejected.
- [ ] Run `uv run pytest tests/unit/review/test_contracts.py tests/unit/domain -q --no-cov`, then `uv run ruff check src/opsflow/review tests/unit/review`.
- [ ] Inspect the import boundary and commit `feat: add review draft contracts`.

### Task 2: Add canonical review serialization, projection, and change computation

**Files:**

- Create: `src/opsflow/review/serialization.py`
- Test: `tests/unit/review/test_serialization.py`

**Interfaces:**

- Consumes: `ReviewDraft`, `ReviewLine`, `ReviewChange`, `ReviewRevision` from Task 1 and `ExtractionDraft`, `ExtractedLine`, `Evidence` from Phase 4.
- Produces:

```python
def review_draft_to_payload(draft: ReviewDraft) -> dict[str, object]: ...


def review_draft_from_payload(payload: object) -> ReviewDraft: ...


def review_draft_from_extraction(draft: ExtractionDraft) -> ReviewDraft: ...


def compose_extraction_draft(
    original: ExtractionDraft,
    candidate: ReviewDraft,
) -> ExtractionDraft: ...


def review_changes_to_payload(
    changes: tuple[ReviewChange, ...],
) -> list[dict[str, object]]: ...


def review_changes_from_payload(payload: object) -> tuple[ReviewChange, ...]: ...


def compute_review_changes(
    previous: ReviewDraft,
    candidate: ReviewDraft,
) -> tuple[ReviewChange, ...]: ...


def project_effective_review_draft(
    original: ReviewDraft,
    latest_revision: ReviewRevision | None,
) -> ReviewDraft: ...
```

`review_draft_to_payload` emits exactly the ordered top-level keys
`customer_name`, `customer_reference`, `po_number`, `order_date`,
`requested_delivery_date`, `currency`, and `lines`. Line keys are exactly
`sku`, `description`, `quantity`, and `submitted_price`. Dates are ISO strings;
finite decimals are fixed-point canonical strings with zero rendered as
`"0"`; nulls are explicit; array order is semantic; object-key order is not.
The deserializer accepts only the exact shape, exact canonical scalar strings,
and ordinary JSON lists/dicts, then returns immutable tuples. It rejects
missing/extra keys, floats, noncanonical dates/decimals, mutable application
collections, source/evidence/actor/provider fields, and non-finite values.

`compute_review_changes` compares canonical payload values in this order:
`customer_name`, `customer_reference`, `po_number`, `order_date`,
`requested_delivery_date`, `currency`, then `lines`. Scalar differences create
one scalar change each. Any difference in the complete ordered line array
creates exactly one change with `field_path="lines"`, complete canonical old
array, and complete canonical new array. Equal canonical payloads return an
empty tuple. `compose_extraction_draft` copies source SHA/type, notes, and
evidence from `original` and every editable business value from `candidate`.

**Steps:**

- [ ] Write RED tests for exact key sets, explicit nulls, canonical Decimal/date serialization, line order, strict deserialization, and rejection of provider/source/evidence fields.
- [ ] Add tests for projection from zero revisions and highest revision, candidate composition preserving original evidence, scalar change order, one aggregate line change for value/count/order/add/remove differences, and no-op equality.
- [ ] Run `uv run pytest tests/unit/review/test_serialization.py -q --no-cov` and confirm the intended missing-interface failures.
- [ ] Implement the pure serialization/projection/change functions without database access, clocks, UUID generation, or provider calls. Reuse canonical Decimal/date rules established in `src/opsflow/persistence/mappers.py` without weakening extraction serialization.
- [ ] Run the focused suite, existing extraction mapper tests, and `uv run ruff format --check src/opsflow/review tests/unit/review`.
- [ ] Inspect the canonical payload examples and commit `feat: add canonical review serialization`.

### Task 3: Add migration 0004, ORM mapping, and immutable revision repositories

**Files:**

- Create: `alembic/versions/0004_phase6_review_revisions.py`
- Create: `tests/unit/persistence/test_review_mappers.py`
- Create: `tests/integration/test_phase6_persistence.py`
- Modify: `src/opsflow/persistence/models.py`
- Modify: `src/opsflow/persistence/mappers.py`
- Modify: `src/opsflow/persistence/repositories.py`
- Modify: `src/opsflow/persistence/__init__.py` to export `ReviewRevisionModel`
- Modify: `tests/unit/persistence/test_models.py`

**Interfaces:**

- Consumes: Task 1 review records, Task 2 canonical serializers, existing `ExtractionSnapshotModel`, `AuditEventModel`, order lock, and transaction-owned repository conventions.
- Produces:

```python
async def insert_review_revision(
    session: AsyncSession,
    revision: ReviewRevision,
) -> None: ...


async def get_latest_review_revision(
    session: AsyncSession,
    order_id: UUID,
) -> ReviewRevision | None: ...


async def get_review_revision_history(
    session: AsyncSession,
    order_id: UUID,
) -> tuple[ReviewRevision, ...]: ...


async def get_latest_audit_event_id(
    session: AsyncSession,
    order_id: UUID,
) -> UUID | None: ...


def review_revision_to_model(revision: ReviewRevision) -> ReviewRevisionModel: ...


def review_revision_from_model(row: ReviewRevisionModel) -> ReviewRevision: ...
```

Migration `0004_phase6_review_revisions` follows `0003` and first adds the
minimal redundant unique key `uq_extraction_snapshots_id_order_id` on
`(extraction_snapshots.id, extraction_snapshots.order_id)` so PostgreSQL can
enforce review snapshot ownership. It then creates `review_revisions` with
UUID primary key, `order_id`, `extraction_snapshot_id`, positive
`revision_number`, canonical JSONB `payload`, JSONB `changes`, bounded
nonblank `actor`, and timezone-aware `created_at`. Add named unique/check/FK
constraints for `(order_id, revision_number)`, positive revision number,
JSON object/array shape, actor bounds, order ownership, and composite
`(extraction_snapshot_id, order_id)` ownership to the original snapshot.
Use `ON DELETE CASCADE` consistently with the existing order/snapshot graph.
Do not add global SHA uniqueness, revision update/delete operations, or an
approval-level column.

Repository functions insert and read only, never update/delete revisions,
commit, invoke providers, or invoke the engine. The latest audit query orders
by `occurred_at DESC, id DESC` and returns only the generation UUID. Revision
history orders by `revision_number ASC`. Revision numbers are assigned later
under the locked order row; the unique constraint is the database backstop.

**Steps:**

- [ ] Write RED metadata tests for the migration chain, exact table/column types, named constraints, positive/bounded checks, cascade behavior, composite ownership, and absence of global SHA/approval-level fields.
- [ ] Write mapper tests for canonical payload/change round trips, explicit nulls, ordered changes, timezone-aware `created_at`, and rejection of invalid or cross-order snapshot ownership.
- [ ] Write PostgreSQL tests for upgrade from `0003`, downgrade/re-upgrade, revision insert/latest/history ordering, uniqueness, cascade behavior, latest audit ID ordering, and absence of update/delete repository functions.
- [ ] Run `uv run pytest tests/unit/persistence/test_models.py tests/unit/persistence/test_review_mappers.py tests/integration/test_phase6_persistence.py -q --no-cov`; the RED result must identify the missing migration/model/repository surface.
- [ ] Implement the migration explicitly with Alembic operations, then the ORM model, mapper, and narrow transaction-owned repository functions. Keep existing Phase 5 snapshot mapping unchanged.
- [ ] Run the focused PostgreSQL suite plus `uv run pytest tests/integration/test_phase5_persistence.py tests/integration/test_phase2_migrations.py -q --no-cov`.
- [ ] Run `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src/opsflow`; inspect SQL ownership and commit `feat: persist immutable review revisions`.

### Task 4: Add development authorization, runtime composition, and read-side ETag machinery

**Files:**

- Create: `src/opsflow/review/auth.py`
- Create: `src/opsflow/review/concurrency.py`
- Create: `src/opsflow/review/composition.py`
- Create: `tests/unit/review/test_auth.py`
- Create: `tests/unit/review/test_concurrency.py`
- Create: `tests/unit/review/test_composition.py`
- Modify: `src/opsflow/settings.py`
- Modify: `src/opsflow/main.py`
- Modify: `src/opsflow/application/errors.py`
- Modify: `.env.example` by adding exactly `OPSFLOW_REVIEW_DEV_OPERATORS=`

**Interfaces:**

- Consumes: Task 1 `OperatorRole`/`OperatorContext`, Task 3 latest-audit repository contract, existing Pydantic Settings/app-state composition, Phase 5 `ValidationPolicy`, `SandboxBusinessDataProvider`, and `BusinessDataProvider`.
- Produces:

```python
def resolve_operator_token(
    token: str,
    configured: tuple[DevelopmentOperatorConfig, ...],
) -> OperatorContext: ...


def require_view_access(context: OperatorContext) -> None: ...
def require_reviewer(context: OperatorContext) -> None: ...
def require_approval(context: OperatorContext, *, high_value: bool) -> None: ...
def require_rejection(context: OperatorContext, state: OrderState) -> None: ...
def require_retry(context: OperatorContext) -> None: ...


def compute_review_etag(
    order_id: UUID,
    current_state: OrderState,
    failure_origin: OrderState | None,
    latest_review_revision_number: int | None,
    latest_review_revision_id: UUID | None,
    latest_audit_event_id: UUID | None,
) -> str: ...


def require_if_match(
    supplied: str | None,
    current: str,
) -> None: ...


class ReviewDateProvider(Protocol):
    def current_date(self) -> date: ...


@dataclass(frozen=True, slots=True)
class ReviewRuntime:
    policy: ValidationPolicy
    provider: BusinessDataProvider
    date_provider: ReviewDateProvider


def build_demo_review_runtime() -> ReviewRuntime: ...
```

`DevelopmentOperatorConfig` is the exact Pydantic settings record below; its
`SecretStr` token representation cannot appear in settings repr/logging:

```python
class DevelopmentOperatorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    token: SecretStr
    actor: str
    role: OperatorRole


class Settings(BaseSettings):
    review_dev_operators: tuple[DevelopmentOperatorConfig, ...] = ()
```

`Settings.review_dev_operators` parses the JSON environment array, maps
blank/unset input to an empty tuple, rejects duplicate tokens/invalid
roles/blank or overlong actors, and has no anonymous fallback.
`resolve_operator_token` uses `hmac.compare_digest` against every configured
`config.token.get_secret_value()` without logging the credential and raises
one safe unauthenticated error for missing/unknown credentials. Capability
functions are fixed Phase 6 checks, not a permissions framework. The FastAPI
transport uses `HTTPBearer(auto_error=False)`; its dependency rejects missing
or unknown credentials through the same safe error mapping and passes only the
server-created `OperatorContext` to application services. Request bodies and
headers never provide actor or role claims.

`compute_review_etag` hashes the exact UTF-8 canonical string
`review-state-v1 | order_id | current_state | failure_origin-or-null |
latest_review_revision_number-or-null | latest_review_revision_id-or-null |
latest_audit_event_id-or-null` as a quoted lowercase SHA-256 entity tag.
`require_if_match` maps missing to `ReviewPreconditionRequiredError` and any
non-single strong/malformed/stale value to `ReviewPreconditionFailedError`.
The parser rejects weak tags and wildcard `*`.

`build_demo_review_runtime` constructs exactly this explicit demo policy:

```python
ValidationPolicy(
    supported_currencies=("USD",),
    price_tolerance_fraction=Decimal("0.05"),
    high_value_threshold=Decimal("1000"),
)
```

It also constructs this network-free synthetic dataset, using `Decimal` for
every numeric value:

```text
customers:
  CUST-001 | Acme Industries     | active
  CUST-002 | Northstar Retail    | active
  CUST-003 | Inactive Industries | inactive
products:
  SKU-001 | Widget        | active   | USD | Decimal("10") | Decimal("100")
  SKU-002 | Gadget        | active   | USD | Decimal("25") | Decimal("10")
  SKU-003 | Legacy Widget | inactive | USD | Decimal("5")  | Decimal("0")
```

These records are synthetic demo/reference data, not private business data or
an external configuration/database. Tests inject a fixed policy/provider/date
provider directly. `main.create_app` stores the runtime and configured
operators on app state; no dependency-injection framework is added.

Add focused safe application errors for unauthenticated credential, forbidden
capability, review case integrity/unavailability, wrong lifecycle state,
missing/stale precondition, no changes, reference-data failure, changed facts,
invalid rejection reason, and persistence conflict. Their messages contain no
tokens, provider text, SQL, source body, or stack trace.

**Steps:**

- [ ] Write RED tests for three simultaneous configured operators, duplicate/invalid configuration rejection, missing/unknown credential behavior, role derivation, capability matrix, and actor/role claim non-authority.
- [ ] Write ETag tests for canonical input, quoted lowercase digest, null spelling, ordinary revision/approve/reject/retry generation changes, retry-state ABA prevention via latest audit ID, and unchanged ETag when only volatile reference data changes.
- [ ] Write composition tests asserting the exact synthetic policy/data values, one injectable date provider, network-free provider construction, and replacement of policy/provider/date dependencies without environment mutation.
- [ ] Run focused review unit suites and existing settings/application error tests; confirm failures are limited to the missing Phase 6 contracts.
- [ ] Implement settings parsing, constant-time token resolution, fixed capability checks, safe errors, ETag helpers, runtime composition, and FastAPI app-state wiring. Add only the empty `OPSFLOW_REVIEW_DEV_OPERATORS=` key.
- [ ] Run `uv run pytest tests/unit/review tests/unit/application/test_errors.py -q --no-cov`, Ruff, format, and mypy. Inspect the secret scan surface and commit `feat: add review authentication and etags`.

### Task 5: Expose review queue, detail, and current-reference-data reads

**Files:**

- Create: `src/opsflow/application/review_reads.py`
- Create: `src/opsflow/api/review_schemas.py`
- Create: `src/opsflow/api/review.py`
- Create: `tests/unit/application/test_review_reads.py`
- Create: `tests/integration/test_phase6_reads.py`
- Modify: `src/opsflow/persistence/repositories.py` for bounded read queries only
- Modify: `src/opsflow/main.py` to include the review router and keep Task 4 app-state wiring intact

**Interfaces:**

- Consumes: Tasks 1–4, existing order/snapshot/issues/audit repositories, `BusinessDataProvider`, and server-resolved `OperatorContext`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class ReviewQueueItem:
    id: UUID
    state: OrderState
    failure_origin: OrderState | None
    customer_reference: str | None
    po_number: str | None
    order_date: date | None
    requested_delivery_date: date | None
    currency: str | None
    created_at: datetime
    validation_issue_count: int
    high_value_approval_required: bool


@dataclass(frozen=True, slots=True)
class ReviewQueuePage:
    items: tuple[ReviewQueueItem, ...]
    states: tuple[OrderState, ...]
    limit: int
    offset: int
    total: int


@dataclass(frozen=True, slots=True)
class ReviewActions:
    can_edit: bool
    can_approve: bool
    can_reject: bool
    can_retry: bool


@dataclass(frozen=True, slots=True)
class ReviewDetailData:
    order: PersistedOrder
    source_snapshot: PersistedExtractionSnapshot | None
    effective_draft: ReviewDraft | None
    revisions: tuple[ReviewRevision, ...]
    latest_revision: ReviewRevision | None
    actions: ReviewActions
    operator: OperatorContext
    etag: str


async def list_review_orders(
    session: AsyncSession,
    states: tuple[OrderState, ...],
    limit: int,
    offset: int,
    operator: OperatorContext,
) -> ReviewQueuePage: ...


async def get_review_detail(
    session: AsyncSession,
    order_id: UUID,
    operator: OperatorContext,
) -> ReviewDetailData: ...


async def get_current_reference_data(
    session: AsyncSession,
    order_id: UUID,
    operator: OperatorContext,
    provider: BusinessDataProvider,
) -> TrustedBusinessData: ...
```

Queue defaults to `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, and
`FAILED_RETRYABLE`, accepts only those states, bounds `limit` to 1–100 and
`offset` to nonnegative, and orders `created_at ASC, id ASC`. Repository
queries must use one bounded aggregate/subquery for issue count and the
high-value warning rather than an unbounded per-row query pattern.

The read service requires `require_view_access(operator)` before every queue,
detail, and reference-data result. Detail reads one order, its owned single snapshot, latest/history revisions,
current issues, source metadata, original extraction, trusted order graph,
latest audit generation, and computed actions. Zero snapshots for a
pre-extraction retryable failure produce explicit null extraction/effective
draft sections; multiple/incorrect snapshots produce a safe integrity error.
Detail includes the ETag in the API header and envelope but never embeds audit
history. The existing `/v1/orders/{order_id}/audit` route remains authoritative.

The reference-data service reads and composes the effective draft, explicitly
rolls back the read transaction, asserts no active transaction at the provider
boundary, calls the provider once, validates the returned contract, and
returns volatile `TrustedBusinessData`. Provider failure maps to safe 503
codes; missing effective draft maps to safe 409; neither changes the detail
ETag.

The HTTP router exposes only:

```text
GET /v1/review/orders
GET /v1/review/orders/{order_id}
GET /v1/review/orders/{order_id}/reference-data
```

Each route resolves bearer credentials through the FastAPI standard security
dependency and passes the resulting `OperatorContext` to the application
service. Pydantic response models use `extra="forbid"`; no provider raw
response, prompt, SQL, credentials, or audit history is serialized.

**Steps:**

- [ ] Write RED repository/read tests for allowed queue states, oldest-first ordering, deterministic pagination, issue/high-value projections, detail source ownership, zero/multiple snapshot outcomes, revision history, action matrix, and ETag emission.
- [ ] Write a provider spy test that proves reference-data lookup begins after `session.rollback()` with `session.in_transaction() is False`, and failure leaves the request session usable.
- [ ] Write HTTP tests for missing/unknown bearer credentials, queue defaults/filters, detail safe errors, ETag header/envelope consistency, and reference-data unavailable/retryable behavior.
- [ ] Run focused tests and confirm the intended absent-router/read failures.
- [ ] Implement bounded repository reads, read DTOs, Pydantic schemas, router dependencies, ETag response headers, and safe mappings. Reuse the existing audit endpoint rather than adding a review audit endpoint.
- [ ] Run `uv run pytest tests/unit/review tests/unit/application/test_review_reads.py tests/integration/test_phase6_reads.py -q --no-cov`, existing order API tests, Ruff, format, mypy, and `uv build`.
- [ ] Inspect OpenAPI paths for exactly the three read routes plus existing order/audit routes and commit `feat: expose review read API`.

**M6B candidate gate:** Tasks 1–5 provide immutable contracts, migration,
append-only revision persistence, development auth, synthetic runtime,
read-side ETag machinery, and usable read APIs. Save & revalidate and all
mutation commands remain absent. Push the exact candidate, require Backend,
Frontend, and Secret scan success, obtain independent review, then create a
separate status-only commit marking M6B `COMPLETE` only after PASS. M6C stays
`NOT STARTED` until that closeout is independently verified.

## M6C — Human Correction & Deterministic Revalidation

M6C owns the narrow reviewed-data promotion path, Save & revalidate, complete
precondition enforcement for that command, deterministic runtime composition,
fact staleness, issue replacement, audit, API, and PostgreSQL atomicity. It
does not implement approve, reject, retry, or React.

### Task 6: Add narrow reviewed-data promotion

**Files:**

- Modify: `src/opsflow/domain/order.py`
- Do not modify: `src/opsflow/domain/__init__.py`; the method remains on the existing `Order` export
- Modify: `tests/unit/domain/test_order.py`

**Interfaces:**

- Consumes: existing immutable `Order`, `OrderLine`, Phase 1 invariants, and Phase 5 `ValidatedOrderData`/`ValidatedOrderLine`.
- Produces:

```python
def Order.promote_reviewed_data(
    self,
    data: ValidatedOrderData,
    line_ids: tuple[UUID, ...],
) -> Order: ...
```

The method requires `self.state is OrderState.NEEDS_REVIEW`, requires a
complete `ValidatedOrderData`, requires one application-created UUID per
validated line, constructs Phase 1-valid trusted lines, preserves order ID,
source documents, and current state, and does not transition state. It must
reject `ReviewDraft`, raw request fields, a result without promotable data,
wrong state, mutable IDs, wrong ID count, and invalid trusted line values.

**Steps:**

- [ ] Write RED tests for clean promotion from `NEEDS_REVIEW`, rejection from every other state including `EXTRACTED`, exact line-ID count/type, source/ID/state preservation, trusted field replacement, and Phase 1 invariant enforcement.
- [ ] Run `uv run pytest tests/unit/domain/test_order.py -q --no-cov` and confirm only the missing reviewed-data operation fails.
- [ ] Implement the separate narrow method without changing `promote_validated_data`, the state table, `Order.retry()`, `Order.reopen()`, or Phase 2 intake.
- [ ] Run the domain suite and existing scenario/transition tests; inspect the import remains infrastructure-independent.
- [ ] Commit `feat: promote reviewed order data`.

### Task 7: Implement Save & revalidate application operation

**Files:**

- Create: `src/opsflow/application/review_revalidation.py`
- Create: `tests/unit/application/test_review_revalidation.py`

**Interfaces:**

- Consumes: Tasks 1–6, Task 3 repository functions, Task 4 ETag/runtime contracts, Task 5 read dependencies, existing Phase 5 `build_validation_facts`, `validate_trusted_business_data`, `ValidationEngine`, `replace_validation_issues`, `get_order_for_update`, `update_order_snapshot`, and `insert_audit_event`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class ReviewRevalidationResult:
    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    revision_id: UUID
    revision_number: int
    validation_result: ValidationResult
    etag: str


async def save_and_revalidate(
    session: AsyncSession,
    order_id: UUID,
    candidate: ReviewDraft,
    if_match: str | None,
    operator: OperatorContext,
    provider: BusinessDataProvider,
    policy: ValidationPolicy,
    date_provider: ReviewDateProvider,
    recorded_at: datetime,
) -> ReviewRevalidationResult: ...
```

The operation must implement this exact sequence:

1. Receive only the immutable typed candidate; reject client actor, role, old values, revision, state, evidence, source, and changes at transport before this function.
2. Require server-resolved `REVIEWER`, then capture `evaluation_date =
   date_provider.current_date()` exactly once at command start. No later clock
   read is permitted in this command.
3. In the first short read transaction, load order, owned Phase 5 snapshot, latest revision, latest audit ID, and effective draft.
4. Compute the current strong ETag and compare `If-Match` before provider work. Missing is `ReviewPreconditionRequiredError`; malformed/stale is `ReviewPreconditionFailedError`; rollback before returning.
5. Require order state `NEEDS_REVIEW`.
6. Compute server-side changes against the effective draft and reject a no-op before provider work.
7. Compose the candidate `ExtractionDraft` with immutable source
   identity/notes/evidence and candidate business fields; the previously
   captured `evaluation_date` remains the only review-time date for this
   command.
8. Explicitly `await session.rollback()` to close the preflight transaction; early errors leave the supplied session rolled back or closed.
9. Assert `session.in_transaction() is False`; build the candidate lookup and call `provider.get_validation_data(...)` exactly once; validate its result; never call a provider in a transaction.
10. Read `ValidationFacts` in a second short transaction using the candidate PO/source SHA and canonical customer reference only when exactly one active customer candidate exists.
11. Explicitly roll back the second read transaction.
12. Assert `session.in_transaction() is False`; construct one `ValidationContext(evaluation_date=evaluation_date)` and call `validation_engine.validate(composed_draft, trusted_data, facts, policy, context)` exactly once.
13. Begin the final transaction and lock the order with `SELECT ... FOR UPDATE` through `get_order_for_update`.
14. Recheck state, source ownership/identity, owned snapshot, latest revision, latest audit generation, and recomputed current ETag against `If-Match`.
15. Re-read local facts inside the final transaction. If they differ, raise the safe facts-changed error and write nothing; do not rerun the engine.
16. Allocate `latest_revision_number + 1` under the order lock, insert the immutable candidate payload and server-computed changes, and replace current validation issues.
17. For errors, preserve the trusted graph and route `NEEDS_REVIEW → VALIDATED → NEEDS_REVIEW`.
18. For a clean result, call `promote_reviewed_data` only with `ValidatedOrderData` and fresh application UUIDs, then route `NEEDS_REVIEW → VALIDATED → READY_FOR_APPROVAL`.
19. Insert `REVIEW_REVISION_RECORDED`, `REVIEW_REVALIDATION_COMPLETED`, and exactly one route event with the approved descriptions and server actor; commit once; compute/return the fresh ETag after the final audit generation is known.

`recorded_at` must be timezone-aware and is the application-supplied base for
successive microsecond audit timestamps. No provider, engine, AI, network, or
external adapter runs inside the final transaction. Invalid corrections store
the revision/issues but never replace trusted order fields/lines. Clean
corrections promote only engine-produced validated data. All writes roll back
together on any failure.

**Steps:**

- [ ] Write RED unit tests for typed candidate use, reviewer authorization, initial ETag/precondition ordering, no-op before provider, candidate composition, exactly-once provider/engine calls, one review-time date, supplied policy identity, and rollback of early errors.
- [ ] Add provider and engine spies that inspect the same `AsyncSession` and assert `session.in_transaction() is False`; assert provider lookup uses candidate fields rather than the previous effective draft.
- [ ] Add tests for invalid correction preserving the trusted graph, clean correction promoting only `ValidatedOrderData`, effective revision history, aggregate line changes, high-value warning persistence, and exact audit events/descriptions/actor/timestamps.
- [ ] Add race tests for state/source/snapshot/revision/latest-audit ETag changes and local facts changing between the second read and final lock; assert zero writes and no engine replay.
- [ ] Run the focused application suite and confirm intended RED failures before implementation.
- [ ] Implement the service with explicit `rollback()` boundaries, one final `async with session.begin()`, order lock, fresh checks, append-only revision, issue replacement, legal transitions, reviewed promotion, and audit.
- [ ] Run `uv run pytest tests/unit/application/test_review_revalidation.py tests/unit/application/test_validation.py tests/unit/domain -q --no-cov`, then the focused PostgreSQL suite in Task 8 after it exists; run Ruff, format, mypy, and build.
- [ ] Inspect the transaction diff and commit `feat: add deterministic review revalidation`.

### Task 8: Expose Save & revalidate HTTP and PostgreSQL atomic/concurrency coverage

**Files:**

- Modify: `src/opsflow/api/review_schemas.py`
- Modify: `src/opsflow/api/review.py`
- Create: `tests/integration/test_phase6_revalidation.py`
- Do not modify: `tests/integration/test_phase6_reads.py`; Task 8 owns its integration fixtures

**Interfaces:**

- Consumes: Task 7 `save_and_revalidate`, Task 5 `ReviewDetailData`, Task 4 safe errors, and the existing router/session dependency pattern.
- Produces the exact route:

```text
PUT /v1/review/orders/{order_id}/draft
```

Request models are strict and contain only the seven editable draft fields;
line payloads contain only `sku`, `description`, `quantity`, and
`submitted_price`. Lists map to immutable tuples. `If-Match` is a required
header. The endpoint maps `ReviewDraftRequest` to `ReviewDraft`, reads runtime
provider/policy/date dependencies from app state, captures `recorded_at`, and
returns the refreshed detail with ETag header/envelope after commit. The
router obtains that detail by calling `get_review_detail` in a separate
post-commit read; it never holds the final write transaction open for response
serialization.

Status/error mapping is locked: `200` for committed invalid or clean
revalidation; `401` credential failure; `403` wrong role; `404` missing order;
`409` integrity/wrong-state/no-op/facts conflict where applicable; `412` stale
or malformed ETag; `428` missing `If-Match`; `503` provider/reference failure;
`422` invalid typed draft or transport shape. Error bodies use `{detail:
{code, message}}` with bounded safe messages.

**Steps:**

- [ ] Write RED transport tests for exact editable fields, rejection of actor/role/revision/old-values/state/evidence/source/change claims, missing/malformed/stale `If-Match`, and safe error envelopes.
- [ ] Write PostgreSQL integration tests for invalid correction, clean correction, no-op, stale revision, stale audit generation, state/source/snapshot mismatch, stale local facts, provider/engine outside transaction, fresh ETag, and all-or-nothing rollback after each final write stage.
- [ ] Add explicit assertions that invalid corrections leave trusted scalar/line rows unchanged while revisions/issues/audits persist, and clean corrections reach `READY_FOR_APPROVAL` with the durable high-value warning when appropriate.
- [ ] Run focused tests and confirm RED identifies the absent route/transaction behavior.
- [ ] Implement strict request/response schemas, header handling, safe mappings, and route registration without adding a generic patch/state endpoint.
- [ ] Run `uv run pytest tests/integration/test_phase6_revalidation.py tests/integration/test_phase5_application.py tests/integration/test_orders_api.py -q --no-cov`, all relevant unit suites, Ruff, format, mypy, and build.
- [ ] Inspect OpenAPI and commit `feat: expose review draft command`.

**M6C candidate gate:** Tasks 6–8 provide reviewed promotion, complete Save &
revalidate preconditions, provider/engine transaction safety, atomic issue and
graph behavior, audit, and HTTP coverage. Approve/reject/retry remain absent.
Push the exact candidate, require all CI jobs, obtain independent review, then
make the separate status-only M6C closeout commit after PASS.

## M6D — Approval, Rejection & Retry Commands/API

M6D owns command services and HTTP routes for approval, rejection, and retry.
It reuses the ETag/precondition machinery implemented in M6B and enforced for
Save & revalidate in M6C. It does not duplicate concurrency code or add React.

### Task 9: Add approve, reject, and retry application commands

**Files:**

- Create: `src/opsflow/application/review_commands.py`
- Create: `tests/unit/application/test_review_commands.py`

**Interfaces:**

- Consumes: Task 1 operator/capability contracts, Task 3 revision/audit repositories, Task 4 ETag helpers, Task 5 read-side projections, and existing `Order.transition_to`, `Order.retry`, `update_order_snapshot`, and `insert_audit_event`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class ReviewCommandResult:
    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    etag: str


async def approve_order(
    session: AsyncSession,
    order_id: UUID,
    if_match: str | None,
    operator: OperatorContext,
    recorded_at: datetime,
) -> ReviewCommandResult: ...


async def reject_order(
    session: AsyncSession,
    order_id: UUID,
    reason: str,
    if_match: str | None,
    operator: OperatorContext,
    recorded_at: datetime,
) -> ReviewCommandResult: ...


async def retry_order(
    session: AsyncSession,
    order_id: UUID,
    if_match: str | None,
    operator: OperatorContext,
    recorded_at: datetime,
) -> ReviewCommandResult: ...
```

Each command reuses the Task 4 read-side ETag helper and the existing
repository preflight-read conventions, ends that read transaction before the
final write transaction, requires
the current ETag, locks the order in the final transaction, recomputes the
current generation, rechecks `If-Match`, authorizes the current
role/state/high-value warning, then performs one legal domain operation and
audit write set. Approval requires `READY_FOR_APPROVAL`; `APPROVER` is allowed
only without `HIGH_VALUE_APPROVAL_REQUIRED`, while `ELEVATED_APPROVER` may
approve either. Both approver roles may reject ready high-value orders.
Reviewer rejection is limited to `NEEDS_REVIEW`; retry is reviewer-only and
calls `Order.retry()` without selecting a destination or rerunning processing.
Rejection trims a nonblank reason and rejects length greater than 500 Unicode
characters before writes. Retry records both requested/restored events. No
provider, network, orchestration, or external mutation is invoked.

**Steps:**

- [ ] Write RED unit tests for the fixed authorization matrix, high-value approval restriction, ordinary high-value rejection, reason trimming/bounds, legal state operations, `failure_origin` restoration, exact audit descriptions, and no external calls.
- [ ] Add command concurrency tests for missing/stale ETags, state changes after preflight, audit-generation changes, and final row-lock rechecks.
- [ ] Run focused command/domain tests and confirm missing service failures.
- [ ] Implement three explicit command functions sharing only small private helpers for current ETag loading and final safe error mapping; do not introduce a command bus or generic permission framework.
- [ ] Run `uv run pytest tests/unit/application/test_review_commands.py tests/unit/domain -q --no-cov` and inspect audit event ordering.
- [ ] Commit `feat: add review approval commands`.

### Task 10: Expose command HTTP routes and PostgreSQL hardening

**Files:**

- Modify: `src/opsflow/api/review_schemas.py`
- Modify: `src/opsflow/api/review.py`
- Create: `tests/integration/test_phase6_commands.py`
- Modify: `tests/integration/test_phase6_auth.py` to add command transport cases

**Interfaces:**

- Consumes: Task 9 command functions, Task 4 bearer dependency/errors, Task 5 ETag response conventions, and existing audit route.
- Produces exactly:

```text
POST /v1/review/orders/{order_id}/approve
POST /v1/review/orders/{order_id}/reject
POST /v1/review/orders/{order_id}/retry
```

Approval and retry accept an empty body; reject accepts only `{ "reason":
"bounded nonblank reason" }` with `extra="forbid"`. Every route requires
`If-Match`, returns `200` with order ID/state/failure origin/fresh ETag, and
maps safe errors without leaking SQL, provider data, source content, tokens,
or stack traces.

**Steps:**

- [ ] Write RED HTTP tests for endpoint shapes, `401`/`403`, missing/stale ETag, wrong state, high-value ordinary/elevated approvals, ordinary high-value rejection, bounded rejection reason, and retry response.
- [ ] Write PostgreSQL tests for each valid `failure_origin` (`PROCESSING`, `EXTRACTED`, `SYNCING`), invalid state actions, atomic audit/state writes, injected rollback, and the ABA sequence: old `FAILED_RETRYABLE` ETag → retry → test setup restores the same state/failure origin → old ETag still returns `412`.
- [ ] Assert that reference-data-only changes do not alter the review ETag and that the existing audit endpoint contains command events without duplication in detail.
- [ ] Run focused command integration tests and confirm intended RED route failures.
- [ ] Implement schemas/routes with shared Task 4/5 precondition helpers and no second ETag implementation.
- [ ] Run `uv run pytest tests/integration/test_phase6_commands.py tests/integration/test_phase6_auth.py tests/integration/test_orders_api.py -q --no-cov`, relevant unit suites, Ruff, format, mypy, and build.
- [ ] Commit `feat: expose review command API`.

**M6D candidate gate:** Tasks 9–10 provide approval/rejection/retry commands,
fixed authorization, state locking, atomic audits, ABA protection, and HTTP
contracts. Frontend remains absent. Push, require CI, obtain independent
review, and create the separate status-only M6D closeout commit only after
PASS.

## M6E — React Review Application & Cross-Boundary Hardening

M6E is the first business-critical frontend milestone. It remains a lightweight
React/Vite application with ordinary local state and a typed API layer. It does
not become a second authority.

### Task 11: Add frontend test/router/API/access foundation

**Files:**

- Create: `web/src/app/Router.tsx`
- Create: `web/src/api/review.ts`
- Create: `web/src/auth/operatorAccess.ts`
- Create: `web/src/auth/OperatorAccessForm.tsx`
- Create: `web/src/test/setup.ts`
- Create: `web/src/test/fixtures.ts`
- Create: `web/vitest.config.ts`
- Modify: `web/package.json`
- Modify: `web/package-lock.json`
- Modify: `web/vite.config.ts`
- Modify: `web/src/App.tsx`
- Modify: `web/src/main.tsx`
- Modify: `web/src/index.css`
- Modify: `Makefile`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**

- Consumes: Task 5/8/10 HTTP contracts and current React/Vite foundation.
- Produces:

```typescript
export type ReviewState =
  | "NEEDS_REVIEW"
  | "READY_FOR_APPROVAL"
  | "FAILED_RETRYABLE";

export type OrderState =
  | "RECEIVED"
  | "PROCESSING"
  | "EXTRACTED"
  | "VALIDATED"
  | "NEEDS_REVIEW"
  | "READY_FOR_APPROVAL"
  | "APPROVED"
  | "SYNCING"
  | "COMPLETED"
  | "REJECTED"
  | "FAILED_RETRYABLE"
  | "FAILED_FINAL";

export type OperatorRole = "REVIEWER" | "APPROVER" | "ELEVATED_APPROVER";

export type CanonicalJsonValue =
  | null
  | string
  | number
  | boolean
  | CanonicalJsonValue[]
  | { [key: string]: CanonicalJsonValue };

export interface ReviewQueueQuery {
  states: ReviewState[];
  limit: number;
  offset: number;
}

export interface ReviewQueueItem {
  id: string;
  state: ReviewState;
  failureOrigin: OrderState | null;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  createdAt: string;
  validationIssueCount: number;
  highValueApprovalRequired: boolean;
}

export interface ReviewQueuePage {
  items: ReviewQueueItem[];
  states: ReviewState[];
  limit: number;
  offset: number;
  total: number;
}

export interface ReviewLine {
  sku: string | null;
  description: string | null;
  quantity: string | null;
  submittedPrice: string | null;
}

export interface ReviewDraft {
  customerName: string | null;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  lines: ReviewLine[];
}

export interface ReviewChange {
  fieldPath: string;
  oldValue: CanonicalJsonValue;
  newValue: CanonicalJsonValue;
}

export interface ReviewRevision {
  id: string;
  orderId: string;
  extractionSnapshotId: string;
  revisionNumber: number;
  payload: ReviewDraft;
  changes: ReviewChange[];
  actor: string;
  createdAt: string;
}

export interface SourceDocument {
  id: string;
  documentType: string;
  name: string;
  mimeType: string;
  sha256: string;
  messageId: string | null;
  storageReference: string | null;
  metadata: Array<[string, string]>;
}

export interface ExtractionEvidence {
  fieldPath: string;
  sourceLocation: string;
  quote: string;
}

export interface OriginalExtraction {
  snapshotId: string;
  sourceSha256: string;
  sourceDocumentType: string;
  customerName: string | null;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  lines: ReviewLine[];
  notes: string | null;
  evidence: ExtractionEvidence[];
}

export interface TrustedOrderLine {
  id: string;
  sku: string;
  description: string;
  quantity: string;
  submittedPrice: string;
  trustedCataloguePrice: string | null;
}

export interface TrustedOrder {
  id: string;
  state: OrderState;
  failureOrigin: OrderState | null;
  createdAt: string;
  customerReference: string | null;
  poNumber: string | null;
  orderDate: string | null;
  requestedDeliveryDate: string | null;
  currency: string | null;
  lines: TrustedOrderLine[];
  sourceDocuments: SourceDocument[];
}

export interface ValidationIssue {
  ruleCode: string;
  severity: string;
  field: string;
  expected: CanonicalJsonValue;
  actual: CanonicalJsonValue;
  explanation: string;
}

export interface ReviewActions {
  canEdit: boolean;
  canApprove: boolean;
  canReject: boolean;
  canRetry: boolean;
}

export interface ReviewDetail {
  order: TrustedOrder;
  sourceSnapshot: OriginalExtraction | null;
  effectiveDraft: ReviewDraft | null;
  revisions: ReviewRevision[];
  latestRevision: ReviewRevision | null;
  validationIssues: ValidationIssue[];
  actions: ReviewActions;
  operator: { actor: string; role: OperatorRole };
  etag: string;
}

export interface ReferenceData {
  customerCandidates: Array<{
    reference: string;
    name: string;
    active: boolean;
  }>;
  productsByLine: Array<{
    sku: string;
    description: string | null;
    active: boolean;
    currency: string;
    cataloguePrice: string | null;
    availableQuantity: string | null;
  } | null>;
}

export interface AuditEvent {
  id: string;
  orderId: string;
  eventType: string;
  actor: string;
  occurredAt: string;
  description: string;
}

export interface ReviewCommandResult {
  orderId: string;
  state: OrderState;
  failureOrigin: OrderState | null;
  etag: string;
}

export interface ReviewApiError {
  status: number;
  code: string;
  message: string;
}

export interface ReviewApiClient {
  listOrders(query: ReviewQueueQuery): Promise<ReviewQueuePage>;
  getDetail(orderId: string): Promise<ReviewDetail>;
  getReferenceData(orderId: string): Promise<ReferenceData>;
  saveDraft(orderId: string, draft: ReviewDraft, etag: string): Promise<ReviewDetail>;
  approve(orderId: string, etag: string): Promise<ReviewCommandResult>;
  reject(orderId: string, reason: string, etag: string): Promise<ReviewCommandResult>;
  retry(orderId: string, etag: string): Promise<ReviewCommandResult>;
  getAudit(orderId: string): Promise<AuditEvent[]>;
}

export interface OperatorSession {
  credential: string;
  operator: { actor: string; role: OperatorRole } | null;
}

export function createReviewApiClient(
  session: OperatorSession,
  fetchImpl: typeof fetch = fetch,
): ReviewApiClient;
```

The API client uses native `fetch`, sends only the session bearer credential,
reads the ETag response header/envelope, sends `If-Match` for every mutation,
decodes `{detail:{code,message}}`, and throws `ReviewApiError` without raw
response/credential disclosure. `operatorAccess.ts` stores the credential in
React state and may mirror it only to `sessionStorage`; it never stores actor
or role as authority and never uses localStorage, URL, source, or production
constants for credentials.

Use Declarative Mode with exactly `/review` and `/review/:orderId`. Add the
Vite `/v1` proxy to the local FastAPI server. Add only `react-router`,
`vitest`, `@testing-library/react`, `@testing-library/user-event`,
`@testing-library/jest-dom`, and `jsdom`-support packages required by the
approved test setup. Add `npm run test -- --run` to `frontend-check` and the
existing GitHub Frontend job. Do not add a frontend data/state framework.

**Steps:**

- [ ] Write RED tests for API URL/headers/body parsing, ETag capture, safe API errors, session-only credential handling, router paths, and access-form/backend-resolved operator display.
- [ ] Configure Vitest jsdom/setup matchers and add synthetic fixtures with no usable credentials. Run `npm --prefix web test -- --run`; the initial failure must identify missing test configuration or clients.
- [ ] Install only approved packages with npm so `package-lock.json` records the exact resolved graph; do not add production backend packages.
- [ ] Implement the typed API module, access session helper, router shell, Vite proxy, test setup, and package/CI scripts. Keep `App.tsx` as a small composition root.
- [ ] Run `npm --prefix web test -- --run`, `npm --prefix web run lint`, and `npm --prefix web run build`; run `make frontend-check` after its script is updated.
- [ ] Inspect package diff for unapproved packages and commit `feat: add review frontend foundation`.

### Task 12: Build the review queue page

**Files:**

- Create: `web/src/pages/ReviewQueuePage.tsx`
- Create: `web/src/pages/ReviewQueuePage.test.tsx`
- Modify: `web/src/app/Router.tsx`
- Modify: `web/src/index.css`

**Interfaces:**

- Consumes: Task 11 `ReviewApiClient`, `ReviewState`, `ReviewQueuePage`, operator session, and route shell.
- Produces: a `/review` page that requests default states `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, `FAILED_RETRYABLE`, preserves allowed filter selection, uses backend `limit/offset/total`, navigates by `order_id`, and displays state, customer/PO, age/date, exception count, and high-value warning.

The page must expose labelled state filters, bounded pagination, loading,
success, empty, and error states. It does not locally decide action authority
or validation. Unknown server states and API failures render safe bounded
messages. Navigation uses React Router links/commands, not hand-built global
state.

**Steps:**

- [ ] Write user-level RTL tests first for loading, queue success, empty, error, state filters, deterministic pagination parameters, and navigation to `/review/:orderId`.
- [ ] Run the focused test and observe the missing page behavior.
- [ ] Implement the queue page with native semantic controls, accessible labels, and ordinary component state.
- [ ] Run `npm --prefix web test -- --run web/src/pages/ReviewQueuePage.test.tsx`, lint, and build; inspect CSS for focused application styling.
- [ ] Commit `feat: add review queue interface`.

### Task 13: Build the review detail inspection surface

**Files:**

- Create: `web/src/pages/ReviewDetailPage.tsx`
- Create: `web/src/components/review/ReviewEvidencePanel.tsx`
- Create: `web/src/components/review/ReviewEvidencePanel.test.tsx`
- Create: `web/src/components/review/ReviewReferencePanel.tsx`
- Create: `web/src/components/review/ReviewReferencePanel.test.tsx`
- Create: `web/src/components/review/ReviewHistoryPanel.tsx`
- Create: `web/src/components/review/ReviewHistoryPanel.test.tsx`
- Create: `web/src/pages/ReviewDetailPage.test.tsx`
- Modify: `web/src/app/Router.tsx`
- Modify: `web/src/index.css`

**Interfaces:**

- Consumes: Task 11 typed `ReviewDetail`, `ReferenceData`, `AuditEvent`, ETag/session behavior and Task 5/10 response contracts.
- Produces: a `/review/:orderId` page with explicit sections for original AI extraction/evidence, human-reviewed effective values, trusted persisted order, deterministic validation issues, current trusted reference data, revision history, and existing audit history.

The evidence panel displays source name/type/MIME/hash/reference and original
evidence location/quote but never renders or implies persisted raw files. It
labels evidence as original AI provenance and never presents it as proof of a
later human edit. The reference panel independently loads current trusted data,
labels it exactly, shows success/unavailable/retry states, and does not alter
the detail ETag. Detail loading, safe errors, and action flags remain explicit.

**Steps:**

- [ ] Write RTL tests for detail loading/success/error, original extraction/evidence labels, trusted values, validation issues, source limitation, revision history, audit fetch, reference-data success, unavailable, and retry.
- [ ] Run the focused tests and confirm missing detail behavior.
- [ ] Implement the detail page and three focused panels with semantic headings/regions; keep audit retrieval on the existing endpoint.
- [ ] Run detail tests, full frontend tests, lint, and build. Inspect rendered labels for the evidence/human/trusted distinction.
- [ ] Commit `feat: add review detail interface`.

### Task 14: Add human correction and Save & revalidate UI

**Files:**

- Create: `web/src/components/review/ReviewDraftForm.tsx`
- Create: `web/src/components/review/ReviewDraftForm.test.tsx`
- Modify: `web/src/pages/ReviewDetailPage.tsx`
- Modify: `web/src/index.css`

**Interfaces:**

- Consumes: Task 11 `saveDraft`, Task 13 detail data/ETag, and the editable fields from the approved `ReviewDraft` contract.
- Produces: a form available only when backend `can_edit` is true, with labelled scalar fields and ordered lines supporting value edit, add, remove, and reorder. Submission sends the complete candidate draft and the last server ETag exactly once.

The form must preserve null/empty semantics compatible with the backend,
display server validation issues, distinguish no-op errors, show invalid
correction remaining in `NEEDS_REVIEW`, show clean correction reaching
`READY_FOR_APPROVAL`, and handle `412` by showing stale-case messaging with a
reload action. It never locally promotes data or silently merges/replays a
submission.

**Steps:**

- [ ] Write user-level tests for editable whitelist, add/remove/reorder lines, complete body submission, ETag header, invalid correction response, clean response, no-op error, and stale `412` without replay.
- [ ] Run the focused test and observe the absent form behavior.
- [ ] Implement controlled local form state, native labels, field errors, error summary, keyboard-accessible reorder controls, and one Save & revalidate request path.
- [ ] Run the form test, detail tests, full frontend tests, lint, and build. Confirm a read-only detail cannot submit a draft.
- [ ] Commit `feat: add human correction interface`.

### Task 15: Add command actions and cross-boundary hardening

**Files:**

- Create: `web/src/components/review/ReviewActions.tsx`
- Create: `web/src/components/review/ReviewActions.test.tsx`
- Modify: `web/src/pages/ReviewDetailPage.tsx`
- Modify: `web/src/auth/operatorAccess.ts` to support credential sign-out and switching
- Modify: `web/src/api/review.ts` to preserve fresh ETags and safe command errors across the full workflow
- Modify: `tests/integration/test_phase6_auth.py` for two-credential transport coverage
- Modify: `tests/integration/test_phase6_commands.py` for command/action regressions
- Modify: `tests/integration/test_phase6_revalidation.py` for stale-screen and invalid-correction regressions

**Interfaces:**

- Consumes: Task 9 command services, Task 10 command routes, Task 11 API/session contracts, Task 13 action flags, and Task 14 refreshed ETag behavior.
- Produces: approve/reject/retry controls that are shown or disabled only from backend action flags, but always call authoritative endpoints. Approve distinguishes ordinary/high-value restrictions; elevated approval is explained; reject requires a bounded reason; retry shows that resumed orchestration is outside Phase 6.

The UI must support signing out/changing from a reviewer credential to an
approver or elevated credential in one running server without restart. The
backend-resolved actor/role is displayed; browser claims never grant actions.
Every stale `412`, `401`, `403`, wrong-state response, provider error, and
safe API error remains visible without replay. The task adds no Playwright or
Cypress.

**Steps:**

- [ ] Write RTL tests for allowed/hidden actions, ordinary approval, high-value restriction, elevated approval, ordinary high-value rejection, rejection reason, retry, API errors, stale ETag, and switching between two configured credentials in one running test application.
- [ ] Add/extend backend integration tests for the complete role/state matrix, high-value rejection, ABA, privacy, rollback, and review-detail/read regressions discovered during cross-boundary review.
- [ ] Run frontend tests, backend focused Phase 6 suites, the complete backend suite, lint, format, mypy, build, `make frontend-check`, and `make check` when PostgreSQL is available.
- [ ] Inspect the complete diff for evidence/trust confusion, client authority, future-phase leakage, unapproved dependencies, and generated files. Run `git diff --check`.
- [ ] Commit `test: harden Phase 6 review workflow`.

**M6E candidate gate:** Tasks 11–15 provide the two React routes, typed fetch
layer, development access interaction, queue/detail/evidence/reference-data
surface, editing, actions, stale-screen behavior, frontend tests, CI, and
cross-boundary hardening. Push the exact candidate, require Backend, Frontend,
and Secret scan success, obtain independent review, and create the separate
status-only closeout commit only after PASS. M6F remains `NOT STARTED`.

## M6F — Independent Phase 6 Audit & Closeout Boundary

M6F is not an implementation task in this plan. After M6E implementation,
milestone closeout, exact-head CI, and independent review pass, M6F performs a
fresh read-only audit from the main baseline through the exact Phase 6
candidate. It verifies authority boundaries, persistence ownership, migration,
ETag/ABA, authorization, transactions, state semantics, UI evidence
distinction, privacy, non-goals, full regression coverage, exact-head CI, and
truthful status. It creates `docs/audits/phase-6-audit.md` only after that
audit and any required remediation/re-audit pass. Phase 6 is not marked
complete before M6F passes.

## Safe Error Taxonomy and HTTP Mapping

The implementation must use a focused set of transport-independent application
errors and one router mapping table. Reuse existing Phase 2/5 errors where
semantics match; do not add one exception class per endpoint.

| Semantic class | Safe code | HTTP status | Owning task |
| --- | --- | ---: | --- |
| Missing/unknown credential | `UNAUTHENTICATED` | 401 | Task 4 |
| Role/state capability denied | `FORBIDDEN` | 403 | Task 4/9 |
| Missing order | `ORDER_NOT_FOUND` | 404 | Task 5 |
| Review integrity failure | `REVIEW_CASE_UNAVAILABLE` | 409 | Task 5 |
| Wrong lifecycle state | `INVALID_REVIEW_STATE` | 409 | Task 7/9 |
| Missing `If-Match` | `PRECONDITION_REQUIRED` | 428 | Task 4 helper; Task 7/8 enforcement |
| Malformed/stale `If-Match` | `PRECONDITION_FAILED` | 412 | Task 4 helper; Task 7/8 enforcement |
| No actual draft change | `NO_REVIEW_CHANGES` | 409 | Task 7/8 |
| Invalid/unavailable reference provider | `REFERENCE_DATA_INVALID` / `REFERENCE_DATA_UNAVAILABLE` | 503 | Task 5 |
| Local facts changed | `VALIDATION_FACTS_CHANGED` | 409 | Task 7/8 |
| Invalid rejection reason | `REJECTION_REASON_INVALID` | 422 | Task 9/10 |
| Safe persistence conflict | `REVIEW_PERSISTENCE_CONFLICT` | 409 | Task 3/7/9 |

Every mapping uses a bounded message and excludes credentials, provider raw
exceptions, source text, private cross-order payloads, SQL, SDK objects, and
stack traces. Pydantic transport failures remain standard 422 responses with
the repository's existing FastAPI behavior.

## Audit-Event Ownership and Exact Contracts

Task 7 introduces the human-correction event constants and exact descriptions:

```text
REVIEW_REVISION_RECORDED
  Human review revision recorded.

REVIEW_REVALIDATION_COMPLETED
  Deterministic revalidation completed for the effective human review draft.

ORDER_REMAINS_NEEDS_REVIEW
  Deterministic revalidation found blocking issues; human review remains required.

ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION
  Deterministic revalidation passed; order is ready for approval after human correction.

ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION
  Deterministic revalidation passed; elevated approval is required after human correction.
```

The two ready events share a type and are distinguished by the exact approved
description. Task 9 introduces command constants:

```text
ORDER_APPROVED
  Order approved by operator.

ORDER_REJECTED
  Order rejected. Reason: {trimmed_reason}

ORDER_RETRY_REQUESTED
  Retry requested by operator.

ORDER_RETRY_RESTORED
  Retryable failure cleared; order restored to its recorded failure origin.
```

All actors come from `OperatorContext`; timestamps use application-supplied
timezone-aware `recorded_at` plus successive microseconds within one command.
Structured review changes hold complete corrected values, so audit descriptions
do not duplicate them. Rejection reason remains in its audit description as
the command justification. Event insertion, state/graph changes, issue
replacement, revision insert, and audit writes share one transaction.

## Frontend Design Discipline

The frontend remains an internal operator application, not a component-library
project. The planned tree is intentionally small:

```text
web/src/
  App.tsx
  main.tsx
  index.css
  app/Router.tsx
  api/review.ts
  auth/operatorAccess.ts
  pages/ReviewQueuePage.tsx
  pages/ReviewDetailPage.tsx
  components/review/ReviewEvidencePanel.tsx
  components/review/ReviewReferencePanel.tsx
  components/review/ReviewHistoryPanel.tsx
  components/review/ReviewDraftForm.tsx
  components/review/ReviewActions.tsx
  test/setup.ts
  test/fixtures.ts
```

Only focused repeated/complex components are created. There is no global state
library, generic hook framework, generated client, generic table, form
framework, UI toolkit, or meta-framework. User-level queries and interactions
drive component tests; tests do not depend on private DOM structure.

## Verification Ladder

### Task-level commands

Backend tasks use focused commands before broader checks:

```bash
uv run pytest <focused paths> -q --no-cov
uv run ruff check <focused paths>
uv run ruff format --check <focused paths>
uv run mypy src/opsflow
uv build
git diff --check
```

PostgreSQL-backed tasks use:

```bash
uv run pytest tests/integration/test_phase6_persistence.py -q --no-cov
uv run pytest tests/integration/test_phase6_reads.py -q --no-cov
uv run pytest tests/integration/test_phase6_revalidation.py -q --no-cov
uv run pytest tests/integration/test_phase6_commands.py -q --no-cov
```

Frontend tasks use the exact final script name:

```bash
npm --prefix web test -- --run
npm --prefix web run lint
npm --prefix web run build
```

At M6E, run `make check` only after `frontend-check` and CI include the test
command. If PostgreSQL is unavailable locally, do not claim local integration
success; rely on exact-head CI evidence and state the limitation.

### Milestone candidate gates

At each M6B–M6E candidate:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
uv run pytest -q
uv build
npm --prefix web test -- --run
npm --prefix web run lint
npm --prefix web run build
git diff --check
```

GitHub CI must report Backend SUCCESS, Frontend SUCCESS, and Secret scan
SUCCESS at the exact pushed candidate SHA. A CI annotation is reported but is
not treated as a job failure unless the job conclusion is not `success`.

## Commit Strategy

Use one coherent commit per task after its focused verification and diff
inspection:

1. `feat: add review draft contracts`
2. `feat: add canonical review serialization`
3. `feat: persist immutable review revisions`
4. `feat: add review authentication and etags`
5. `feat: expose review read API`
6. `feat: promote reviewed order data`
7. `feat: add deterministic review revalidation`
8. `feat: expose review draft command`
9. `feat: add review approval commands`
10. `feat: expose review command API`
11. `feat: add review frontend foundation`
12. `feat: add review queue interface`
13. `feat: add review detail interface`
14. `feat: add human correction interface`
15. `test: harden Phase 6 review workflow`

Status-only milestone closeout commits remain separate and occur only after
independent review and exact-head CI. They must not be folded into task
commits. The M6A closeout commit is also separate from this plan candidate and
is not authorized until this plan passes independent review.

## Status-Only Closeout Protocol

This plan candidate does not mark M6A complete. After this plan is committed
and independently reviewed:

1. If findings exist, modify only this plan in a remediation commit and repeat the plan review/verification gate.
2. After independent plan PASS, create a separate status-only M6A closeout commit marking M6A `COMPLETE`, keeping Phase 6 `IN PROGRESS`, M6B–M6F `NOT STARTED`, and Phase 7–12 `NOT STARTED`.
3. Only after that exact-head closeout is independently verified may Task 1 begin.

For M6B–M6E, the sequence is:

```text
implementation candidate
→ exact-head CI
→ independent review PASS
→ status-only milestone closeout
→ exact-head CI for closeout
→ next milestone
```

At M6E closeout, Phase 6 remains `IN PROGRESS`, M6A–M6E are `COMPLETE`, and
M6F is `NOT STARTED`. Phase 6 is not marked complete before M6F passes.

## Plan Self-Review

Before committing this plan, perform a fresh read-only review and repair the
document in place:

- Map every approved design section to an owning task: authority boundary, state routes, immutable snapshot/effective draft, canonical revisions, policy/context/demo provider, migration/ownership, transactions, auth matrix, ETag/ABA, reads, commands, audits, frontend evidence distinction, source limitation, non-goals, tests, and milestone boundaries.
- Confirm every later interface name, parameter, return type, error code, audit constant, route, and frontend client method matches its defining task.
- Confirm all five Review Focus risks have exact test ownership.
- Confirm no implementation task changes status documentation and no task creates M6F artifacts.
- Confirm only approved frontend dependencies are named and no backend runtime dependency is added.
- Search for unresolved implementation markers, vague task instructions, unspecified error behavior, and accidental generic abstractions; replace each with a concrete interface, branch, command, or test.
- Confirm the plan contains no credentials, token values, private business data, generated files, or future-phase implementation.
- Re-read the design's candidate/precondition sequence and verify M6B read-side ETag machinery → M6C Save & revalidate enforcement → M6D command reuse has no gap or duplicate implementation.

## Scope and Plan-Candidate Boundary

This task creates only
`docs/superpowers/plans/2026-09-19-phase-6-human-review-application.md`.
It does not modify the approved design, README, roadmap, production source,
migration, dependency, lockfile, frontend source, test, audit report, status,
or PR. The plan authorizes later implementation planning only. M6A remains
`IN PROGRESS` until the separate status-only closeout gate.
