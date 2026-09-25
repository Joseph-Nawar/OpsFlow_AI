# Phase 7 — n8n Workflow Orchestration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL:
> `superpowers:executing-plans`.
> Single-agent sequential execution is mandatory for this repository. Do not
> use subagents, parallel agents, or `subagent-driven-development` unless the
> user explicitly changes that rule.

**Status:** Implementation plan only. No Phase 7 production implementation,
test, runtime, dependency, Compose change, workflow export, audit file,
milestone closeout, or PR is created by this document.

**Planning baseline:**
`phase/7-n8n-workflow-orchestration` at
`54d84b46ba3bdeecbd3a4b69b976589dde4e5a99`, 2 commits ahead of
`809d201555af1afe5f79c202dfbc2bb259425e6b`, 0 behind.

**Goal:** Build the approved thin n8n orchestration workflow around a
backend-owned, idempotent document-processing, extraction, and validation
pipeline without moving business authority into n8n.

**Architecture:** n8n receives one synthetic multipart document, forwards the
stable source event identity, calls one authenticated OpsFlow command, and
routes only on the returned persisted `OrderState`. Python composes the
existing Phase 2–5 services, owns idempotency, claims, retry-generation
consumption, failure persistence, validation, and audit. PostgreSQL remains
the concurrency authority; all provider work happens after short claim
transactions commit.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async,
PostgreSQL 16, pytest, Docker Compose, n8n Community Edition, the current
React review application only for its existing Retry interaction,
`FakeProvider`, synthetic trusted-data fixtures, and GitHub Actions.

**Spec:**
`docs/superpowers/specs/2026-09-22-phase-7-n8n-workflow-orchestration-design.md`

## Global Constraints

- n8n orchestrates; Python owns business authority.
- AI interprets unstructured input; deterministic software decides validation, routing, lifecycle transitions, and side effects.
- `/v1/orchestration/intakes` is the single Phase 7 orchestration command.
- The request is multipart with exactly one binary `document`, required `document_type`, and optional `message_id`.
- A separate configured service Bearer credential is required and resolves the fixed actor `orchestration:n8n`.
- A stable, nonblank `Idempotency-Key` is required and is the unchanged source-event identity.
- The caller supplies no trusted business fields, actor, role, lifecycle destination, failure origin, validation result, or audit content.
- Python derives the source filename basename, normalized MIME, and SHA-256 from received bytes.
- `FORM` is rejected by the Phase 7 transport contract.
- The Phase 2 `order_creation_idempotency` table, canonical request fingerprint, and unique-key race resolver remain authoritative.
- No second generic idempotency table, job table, event bus, distributed lock, retry framework, or service locator is added.
- `idempotent_replay` is true only when the command returned an already-created idempotent order, including when it loses a concurrent unique-key insertion race; no unsafe pre-read derives this value.
- The exact Phase 1 `OrderState` set and legal transitions remain unchanged.
- An ordinary claim is `RECEIVED -> PROCESSING` with `ORDER_PROCESSING_STARTED` committed before work.
- No parsing, extraction, trusted-data lookup, network provider call, or validation provider call runs under the claim transaction or order lock.
- A duplicate observing ordinary `PROCESSING` stands down without parsing, extraction, or provider work.
- Human retry remains reviewer-authorized through the existing Phase 6 command; n8n never invokes `Order.retry()`.
- A human-restored `PROCESSING` or `EXTRACTED` generation can be consumed exactly once by a matching same-document redelivery.
- `ORDER_PROCESSING_RESUMED` and `ORDER_EXTRACTION_RESUMED` are the durable consumed markers.
- Extracted-origin recovery reparses and re-extracts from identical bytes; the in-memory `ExtractionDraft` is not treated as durable.
- A restored `SYNCING` order is outside Phase 7 resume handling.
- Abandoned initial or consumed resume claims remain duplicate-safe but are not reclaimed; leases, heartbeats, and stale-claim recovery belong to Phase 10.
- Existing Phase 5 `validate_order(...)` remains the validation, immutable snapshot, promotion, and route authority.
- Business validation issues route to `NEEDS_REVIEW`; they are not operational failures.
- Phase 7 adds no raw-document persistence or object storage.
- Phase 7 adds no Gmail, Slack, Odoo, HubSpot, ERP, CRM, or external side effect.
- Phase 7 adds no Redis, queue mode, Kubernetes, cloud deployment, or separate n8n database unless a fresh runtime check proves a direct requirement; the approved design expects none.
- n8n contains no direct Gemini call, AI Agent node, business-rule Code node, approval logic, validation logic, or trusted-data decision.
- n8n transport retry is bounded to connection/node transport errors and HTTP `503` only after the exact pinned-runtime capability is proven; it never blindly retries HTTP `500`, `401`, `409`, `422`, or a persisted `FAILED_RETRYABLE` 2xx business response.
- Exported workflow JSON and local documentation contain no usable credentials, private execution data, customer data, or raw document.
- Live Gemini is never required by CI; M7B/M7C tests use `FakeProvider` and synthetic trusted-data fixtures.
- Mandatory Phase 7 development cost remains effectively `$0` through local PostgreSQL, local n8n Community Edition, Docker, synthetic fixtures, and existing CI.
- M7D must freshly verify the authoritative stable n8n release and required configuration immediately before runtime work; never use `latest`.
- Every implementation task follows RED → intended failure → minimum implementation → focused GREEN → relevant regression suite → diff inspection → one coherent commit.
- No task weakens assertions, skips tests, adds sleeps, swallows broad exceptions, calls live providers in automated tests, or changes milestone status.

## Review Focus

1. **Identity and duplicate delivery:** the same event/key/document returns the same order, never duplicates AI calls, snapshots, promotions, or business execution; a different canonical fingerprint returns `409`. Task 4 owns the created-versus-replayed race tests, Task 5 owns locked claim tests, and Task 9 owns the end-to-end HTTP assertions.
2. **Retry-generation concurrency:** one reviewer-authorized restore is consumed by exactly one matching redelivery, while concurrent resumers stand down. Tasks 5 and 9 own PostgreSQL-backed `PROCESSING`/`EXTRACTED` generation tests; Task 13 owns the cross-boundary demo evidence.
3. **Provider/database boundary and abandoned claims:** no provider runs under an open mutation transaction, and a post-claim crash is visible and duplicate-safe rather than falsely reclaimed. Tasks 6–8 own boundary/classification tests; Task 9 owns persistence-outage and abandoned-claim integration tests; Task 14 owns local smoke evidence.
4. **Failure classification:** business validation issues remain `NEEDS_REVIEW`, typed provider/reference failures become retryable at the correct origin, and malformed or invalid contracts become `FAILED_FINAL`. Tasks 6 and 7 own the typed-provider and persistence matrix; Task 9 owns HTTP status mapping.
5. **n8n trust and export safety:** the workflow forwards binary plus stable identity, routes only on backend state, contains no usable secret or private execution data, performs no business logic, and proves selective retry capability against the exact pinned runtime. Task 11 owns genuine RED/GREEN JSON contract tests; Task 12 owns runtime option evidence; Tasks 13–14 own bounded retry, seed tooling, secret scan, clean-clone, and runtime evidence.

## Repository Findings and File Map

The repository uses router-local transport error mapping, a shared
`SessionDependency` exported from `src/opsflow/api/orders.py`, application
modules for transaction orchestration, and caller-owned async repository
transactions. Integration tests create PostgreSQL engines directly and wrap
async scenarios in `asyncio.run`; there is no shared `tests/conftest.py`.
Phase 6 already provides the reviewer Retry command and React Retry control,
so Phase 7 reuses them without adding a frontend component.

### M7B planned files

- Create `src/opsflow/orchestration/__init__.py` for narrow Phase 7 exports.
- Create `src/opsflow/orchestration/auth.py` for the fixed machine actor and constant-time service-token dependency.
- Create `src/opsflow/orchestration/contracts.py` for the immutable intake command/result and handler seam.
- Create `src/opsflow/orchestration/transport.py` for bounded filename, message-ID, MIME-declaration, and upload-byte checks.
- Create `src/opsflow/api/orchestration.py` for the `/v1/orchestration/intakes` router and safe transport mapping.
- Create `src/opsflow/api/orchestration_schemas.py` for the four-field response DTO.
- Modify `src/opsflow/settings.py` for secret-aware `OPSFLOW_ORCHESTRATION_TOKEN`.
- Modify `src/opsflow/application/errors.py` for safe orchestration authentication, input, source-conflict, and unavailable errors.
- Modify `src/opsflow/main.py` to attach the handler seam, include the router, and register the separate 401/503 handlers.
- Modify `.env.example` with an empty orchestration-token setting.
- Modify `pyproject.toml` and `uv.lock` only for the single required `python-multipart` transport dependency after Task 2 verifies FastAPI’s selected implementation requires it.
- Create `tests/unit/orchestration/test_auth.py`, `tests/unit/orchestration/test_transport.py`, and `tests/unit/orchestration/test_contracts.py`.
- Create `tests/integration/test_phase7_auth.py` and `tests/integration/test_phase7_orchestration_api.py`.

### M7C planned files

- Modify `src/opsflow/application/orders.py` with a backward-compatible created-versus-replayed wrapper around the current `create_order(...)` authority.
- Create `src/opsflow/orchestration/claims.py` for the narrow locked ordinary/retry-generation claim protocol.
- Create `src/opsflow/orchestration/composition.py` for injectable extraction/trusted-data/policy runtime composition.
- Create `src/opsflow/orchestration/failures.py` for typed failure classification and atomic failure persistence.
- Create `src/opsflow/application/orchestration.py` for the end-to-end intake application service.
- Modify `src/opsflow/extraction/errors.py` and `src/opsflow/extraction/gemini.py` to map the installed SDK's typed `google.genai.errors.ServerError` to one provider-availability boundary while preserving timeout and fail-closed unknown-error behavior.
- Modify `src/opsflow/main.py` to wire the real application handler around the composed runtime.
- Create `tests/unit/application/test_orders.py`, `tests/unit/orchestration/test_claims.py`, `tests/unit/orchestration/test_composition.py`, `tests/unit/orchestration/test_failures.py`, and `tests/unit/application/test_orchestration.py`.
- Modify `tests/integration/test_phase2_concurrency.py` only to prove the new disposition wrapper preserves Phase 2 behavior.
- Create `tests/integration/test_phase7_pipeline.py`, `tests/integration/test_phase7_concurrency.py`, and `tests/integration/test_phase7_failure_matrix.py`.

### M7D/M7E planned files

- Modify `docker-compose.yml` with one pinned n8n Community service and one named n8n data volume; no API dependency is added.
- Modify `.env.example` only with empty local n8n configuration entries verified for the selected n8n release; no usable secret is committed.
- Create `fixtures/phase7/synthetic-order.txt` containing the fixed sanitized text document used by the local Webhook demonstration.
- Create `workflows/n8n/opsflow-sandbox-intake.json` from the actual pinned n8n runtime export.
- Create `workflows/n8n/README.md` with credential relinking, Webhook URL, synthetic fixture, recovery redelivery, and clean-clone instructions.
- Create `tests/unit/workflows/test_n8n_contract.py` using standard-library JSON inspection and no live SaaS dependency.
- Create `tests/integration/test_phase7_transport.py` for local cross-boundary transport scenarios that do not require a public webhook.
- Create `scripts/phase7_seed_retryable_demo.py` as local-only synthetic demo tooling, never imported by the API.
- Create `tests/integration/test_phase7_demo_seed.py` for the deterministic processing/extracted seed seam.
- Modify `workflows/n8n/README.md` with verified runtime, retry, and recovery evidence; do not add browser automation or a new frontend package.

### Explicitly not in the file map

No migration, generic workflow engine, command bus, distributed-lock
abstraction, retry framework, event-sourcing layer, attempt/lease table,
raw-document repository, Phase 8+ integration, public status endpoint, PR,
status file, or pre-written Phase 7 audit file is part of this plan.

## Implementation Order and Review Gates

Execute Tasks 1–14 strictly in numerical order, one task at a time. Each task
ends with its focused RED/GREEN or verification cycle, relevant regression
checks, diff inspection, and one coherent commit. No task begins until the
preceding gate and commit are present and its named interfaces are stable.

The plan gate is explicit: this implementation-plan candidate must receive an
independent PASS first. Only then may a separate docs-only M7A closeout commit
mark `M7A COMPLETE` and `M7B NOT STARTED`. That closeout must itself be
independently verified before Task 1 begins. No Tasks 1–3 execution occurs
before that closeout.

Milestone gates:

1. **M7B — Tasks 1–3:** execute only after the independently verified M7A closeout; push the exact candidate, run exact-head CI, obtain independent review, and if PASS create a separate status-only M7B closeout before M7C begins.
2. **M7C — Tasks 4–9:** produce the backend pipeline candidate, run exact-head CI, obtain independent review, and if PASS create a separate M7C closeout before M7D begins.
3. **M7D — Tasks 10–12:** produce the pinned runtime/workflow candidate, run exact-head CI plus real runtime/import evidence, obtain independent review, and if PASS create a separate M7D closeout before M7E begins.
4. **M7E — Tasks 13–14:** produce the hardening/demo candidate, run exact-head CI plus cross-boundary evidence, obtain independent review, and if PASS create a separate M7E closeout before M7F begins.
5. **M7F:** perform the later fresh read-only audit, remediate only findings that require focused changes, and create the audit artifact/status closeout only after the audit PASS.

An implementation worker stops and reports when code contradicts the approved
design, a new product-level decision appears, scope would expand, or the fresh
n8n verification invalidates the approved runtime pin. Routine implementation
does not silently revise the design.

## M7B — Orchestration Service Authentication & HTTP Contract

### Task 1: Add the isolated orchestration service credential

**Files:**

- Create: `src/opsflow/orchestration/__init__.py`
- Create: `src/opsflow/orchestration/auth.py`
- Modify: `src/opsflow/settings.py`
- Modify: `src/opsflow/application/errors.py`
- Modify: `.env.example`
- Test: `tests/unit/orchestration/test_auth.py`

**Interfaces:**

- Consumes: `Settings`/`SecretStr`, existing `HTTPBearer` dependency conventions, `hmac.compare_digest`, and `OperatorContext` authentication patterns only as a safety reference.
- Produces:

```python
ORCHESTRATION_ACTOR: Final[str] = "orchestration:n8n"


class OrchestrationUnauthenticatedError(Exception): ...


def resolve_orchestration_token(
    token: str,
    configured: SecretStr | None,
) -> str: ...


def get_orchestration_actor(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = _bearer_dependency,
) -> str: ...
```

`Settings` gains `orchestration_token: SecretStr | None = None`, which maps to
`OPSFLOW_ORCHESTRATION_TOKEN` through the existing `OPSFLOW_` prefix. The
resolver returns only `ORCHESTRATION_ACTOR`; it never returns a caller actor,
role, or selector. A missing setting, blank configured secret, missing Bearer
header, non-Bearer credential, blank token, or wrong token raises
`OrchestrationUnauthenticatedError`. The comparison uses UTF-8 bytes and
`hmac.compare_digest` exactly once per configured secret value; no credential
value enters the exception text or `repr(Settings())`.

**Steps:**

- [ ] Write RED tests for `Settings` parsing of `OPSFLOW_ORCHESTRATION_TOKEN`, `SecretStr` masking, missing/blank configuration, missing credentials, wrong credentials, constant-time comparison, and the fixed actor value.
- [ ] Run `uv run pytest tests/unit/orchestration/test_auth.py -q --no-cov`; expected RED is `ModuleNotFoundError` for the new package and missing `Settings.orchestration_token`.
- [ ] Implement the settings field, safe error class, fixed actor constant, and dependency using the existing Phase 6 `HTTPBearer(auto_error=False)` shape. Do not add machine roles or reuse `review_dev_operators`.
- [ ] Add tests proving arbitrary `X-Actor`, `X-Role`, and request body claims do not alter the returned actor, and proving the token is absent from all safe error strings.
- [ ] Run `uv run pytest tests/unit/orchestration/test_auth.py tests/unit/review/test_auth.py tests/unit/application/test_errors.py -q --no-cov`.
- [ ] Run `uv run ruff check src/opsflow/orchestration src/opsflow/settings.py src/opsflow/application/errors.py tests/unit/orchestration/test_auth.py` and `uv run mypy src/opsflow`.
- [ ] Inspect the diff for secret exposure and commit:

```bash
git add src/opsflow/orchestration src/opsflow/settings.py src/opsflow/application/errors.py .env.example tests/unit/orchestration/test_auth.py
git commit -m "feat: add orchestration service authentication"
```

### Task 2: Define the multipart command seam and narrow response contract

**Files:**

- Create: `src/opsflow/orchestration/contracts.py`
- Create: `src/opsflow/orchestration/transport.py`
- Create: `src/opsflow/api/orchestration_schemas.py`
- Modify: `pyproject.toml` and `uv.lock` only when the verification below confirms the FastAPI multipart path requires the package
- Test: `tests/unit/orchestration/test_contracts.py`
- Test: `tests/unit/orchestration/test_transport.py`

**Interfaces:**

- Consumes: `SourceDocumentType`, `DEFAULT_DOCUMENT_LIMITS`, `UploadFile`, `Request`, and the Task 1 authentication error boundary.
- Produces:

```python
class IntakeExecution(Enum):
    COMPLETED = "COMPLETED"
    STANDING_DOWN = "STANDING_DOWN"


@dataclass(frozen=True, slots=True)
class OrchestrationIntakeCommand:
    content: bytes
    document_type: SourceDocumentType
    filename: str
    mime_type: str
    message_id: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class OrchestrationIntakeResult:
    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    idempotent_replay: bool
    execution: IntakeExecution


class OrchestrationIntakeHandler(Protocol):
    async def __call__(
        self,
        session: AsyncSession,
        command: OrchestrationIntakeCommand,
        actor: str,
        recorded_at: datetime,
    ) -> OrchestrationIntakeResult: ...


class OrchestrationIntakeResponse(BaseModel):
    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None
    idempotent_replay: bool


async def read_bounded_upload(upload: UploadFile, max_input_bytes: int) -> bytes: ...
```

`OrchestrationIntakeCommand` carries bytes only for the current request. The
transport helper must call `read_bounded_upload(...)`, which requests at most
`max_input_bytes + 1` bytes from `UploadFile.read(size)` and rejects as soon as
the returned buffer exceeds `max_input_bytes`; it never performs an unbounded
read followed by a size check. The helper must reject a missing/blank basename,
a basename longer than 255 characters after both `/` and `\\` path components
are discarded, a missing/blank uploaded MIME declaration, `FORM`, a blank or
over-256-character `message_id`, a blank/over-128-character idempotency key,
and content larger
than `DEFAULT_DOCUMENT_LIMITS.max_input_bytes`. It preserves valid message-ID
and filename characters rather than silently changing source identity. The
backend application later normalizes MIME and computes SHA-256.

Before editing dependencies, inspect the installed FastAPI `UploadFile`/`File`/
`Form` route implementation and its multipart requirement, inspect the direct
dependencies in `pyproject.toml`, and inspect `uv tree` plus `uv.lock` for
transitive ownership. The selected route uses FastAPI multipart parsing; when
that implementation directly relies on `python-multipart`, OpsFlow declares
the direct dependency `python-multipart>=0.0.20,<1` even if the package is
already importable transitively. When the implementation does not directly
rely on it, both project files remain unchanged. No unrelated dependency is
added.

**Steps:**

- [ ] Write RED unit tests for immutable command/result records, exact response fields with `extra="forbid"`, file basename normalization, MIME presence, `FORM` rejection, message-ID/idempotency bounds, bounded-read size `max_input_bytes + 1`, and the max-byte boundary using a fake `UploadFile`.
- [ ] Run `uv run pytest tests/unit/orchestration/test_contracts.py tests/unit/orchestration/test_transport.py -q --no-cov`; expected RED identifies the absent contracts, response model, and transport helpers.
- [ ] Inspect FastAPI’s installed `File`/`Form`/`UploadFile` implementation and route dependency with `uv run python -c 'import inspect; from fastapi import File, Form, UploadFile; from fastapi.dependencies.utils import ensure_multipart_is_installed; print(inspect.getsource(File)); print(inspect.getsource(Form)); print(inspect.getsource(ensure_multipart_is_installed)); print(inspect.signature(UploadFile.read))'`; inspect `pyproject.toml`, run `uv tree --package python-multipart`, and inspect matching `uv.lock` entries. Add the direct dependency with `uv add 'python-multipart>=0.0.20,<1'` only when the FastAPI implementation directly requires it, then run `uv sync --frozen`.
- [ ] Implement the dataclasses, protocol, Pydantic response model, and bounded upload helper without database access, provider calls, raw-file persistence, or HTTP status decisions. The helper reads at most `DEFAULT_DOCUMENT_LIMITS.max_input_bytes + 1`, accepts exactly-max content, rejects max-plus-one content, and retains only the accepted current-request bytes.
- [ ] Add tests proving response serialization contains exactly `order_id`, `state`, `failure_origin`, and `idempotent_replay`, and proving malformed transport input fails before any application handler can be called.
- [ ] Add explicit transport/API tests for exactly `DEFAULT_DOCUMENT_LIMITS.max_input_bytes` bytes accepted, max-plus-one bytes rejected safely, and the handler not called after oversized rejection.
- [ ] Run `uv run pytest tests/unit/orchestration/test_contracts.py tests/unit/orchestration/test_transport.py tests/unit/api/test_schemas.py -q --no-cov` and `uv run ruff format --check src/opsflow/orchestration src/opsflow/api/orchestration_schemas.py tests/unit/orchestration`.
- [ ] Inspect dependency diff for unrelated packages and commit:

```bash
git add src/opsflow/orchestration src/opsflow/api/orchestration_schemas.py pyproject.toml uv.lock tests/unit/orchestration
git commit -m "feat: define orchestration intake transport contracts"
```

### Task 3: Expose the authenticated HTTP boundary without claiming a pipeline

**Files:**

- Create: `src/opsflow/api/orchestration.py`
- Modify: `src/opsflow/main.py`
- Test: `tests/integration/test_phase7_auth.py`
- Test: `tests/integration/test_phase7_orchestration_api.py`

**Interfaces:**

- Consumes: `OrchestrationIntakeCommand`, `OrchestrationIntakeHandler`, `OrchestrationIntakeResult`, `OrchestrationIntakeResponse`, `get_orchestration_actor`, and the existing `SessionDependency` imported from `src/opsflow/api/orders.py`.
- Produces:

```python
router = APIRouter(prefix="/v1/orchestration", tags=["orchestration"])

@router.post("/intakes", response_model=OrchestrationIntakeResponse)
async def create_orchestration_intake_endpoint(...) -> OrchestrationIntakeResponse: ...
```

The endpoint accepts `document`, `document_type`, optional `message_id`, and
`Idempotency-Key` plus the service Bearer dependency. It calls the handler in
`request.app.state.orchestration_intake_handler`; M7B initializes that state
to `None`, and a missing handler returns safe `503 ORCHESTRATION_UNAVAILABLE`
rather than a fake successful result. The route maps an in-progress
`STANDING_DOWN` result whose state is `PROCESSING` or `EXTRACTED` to `202`; a
terminal/business/failure `STANDING_DOWN` result to `200`; a newly created
durable routed or failure result to `201`; and any replayed existing result,
including a successful retry resume, to `200`. It maps idempotency/source
conflicts to `409`, safe transport validation to `422`, and unavailable
application state to `503`. It never logs or echoes
multipart content, credentials, provider details, SQL, or stack traces.

Use a router-local `APIRoute` wrapper, following `src/opsflow/api/review.py`,
to convert malformed multipart/request validation into one bounded `422`
contract. Register the router and a separate
`OrchestrationUnauthenticatedError` handler in `create_app`; preserve the
existing human-review 401 message and handler unchanged.

**Steps:**

- [ ] Write RED integration tests for the exact OpenAPI path, missing/wrong service credential `401`, safe malformed multipart `422`, `FORM` `422`, blank idempotency key `422`, injected-handler `503`, and a stub handler returning each of the `201`/`200`/`202` status cases.
- [ ] Run `uv run pytest tests/integration/test_phase7_auth.py tests/integration/test_phase7_orchestration_api.py -q --no-cov`; expected RED identifies the absent router, app state, and route.
- [ ] Implement the router using the existing session dependency and app-state seam. Use `datetime.now(UTC)` only at the boundary; pass the captured timestamp into the handler.
- [ ] Add tests proving the command forwarded to the stub contains the original binary, declared type, filename basename, uploaded MIME, message ID, and unchanged idempotency key, while the response contains no extra fields.
- [ ] Add safe exception mapping tests for conflict and unavailable errors, including no source bytes or token in the response body.
- [ ] Run `uv run pytest tests/integration/test_phase7_auth.py tests/integration/test_phase7_orchestration_api.py tests/integration/test_orders_api.py tests/integration/test_phase6_auth.py -q --no-cov`, then `uv run ruff check .`, `uv run ruff format --check .`, and `uv run mypy src/opsflow`.
- [ ] Inspect OpenAPI and error-handler changes, then commit:

```bash
git add src/opsflow/api/orchestration.py src/opsflow/main.py tests/integration/test_phase7_auth.py tests/integration/test_phase7_orchestration_api.py
git commit -m "feat: expose orchestration intake HTTP contract"
```

## M7C — Idempotent Intake Pipeline

### Task 4: Add a backward-compatible created-versus-replayed Phase 2 result

**Files:**

- Modify: `src/opsflow/application/orders.py`
- Create: `tests/unit/application/test_orders.py`
- Modify: `tests/integration/test_phase2_concurrency.py`

**Interfaces:**

- Consumes: the existing `CreateOrderInput`, `PersistedOrder`, `create_order(...)` transaction, `insert_idempotency_record(...)`, `_resolve_idempotency_race(...)`, and the existing Phase 2 unique-key constraint.
- Produces:

```python
class CreateOrderDisposition(Enum):
    CREATED_BY_THIS_COMMAND = "CREATED_BY_THIS_COMMAND"
    REPLAYED_EXISTING = "REPLAYED_EXISTING"


@dataclass(frozen=True, slots=True)
class CreateOrderResult:
    persisted: PersistedOrder
    disposition: CreateOrderDisposition


async def create_order_with_disposition(
    session: AsyncSession,
    request: CreateOrderInput,
    idempotency_key: str,
    now: datetime | None = None,
) -> CreateOrderResult: ...
```

Keep the existing public `create_order(...) -> PersistedOrder` behavior as a
compatibility wrapper returning `.persisted`, so Phase 2 callers and tests do
not change semantics. Refactor only the internal success/race return path so a
successful insert returns `CREATED_BY_THIS_COMMAND` and the committed-row
unique-key race resolver returns `REPLAYED_EXISTING`. Fingerprint bytes,
database uniqueness, order/audit atomicity, and conflict behavior are
unchanged.

**Steps:**

- [ ] Write RED unit tests for both dispositions and the compatibility wrapper; assert the created result contains the inserted order and the replay result contains the committed order without a new UUID.
- [ ] Run `uv run pytest tests/unit/application/test_orders.py tests/integration/test_phase2_creation.py -q --no-cov`; expected RED identifies the absent result type/helper.
- [ ] Implement the enum, frozen result, and one internal create path. Do not add a pre-read, alter `fingerprint_order_request`, alter `OrderCreationIdempotencyModel`, or add a table.
- [ ] Extend the existing PostgreSQL barrier test so two simultaneous identical calls to `create_order_with_disposition(...)` return one `CREATED_BY_THIS_COMMAND` and one `REPLAYED_EXISTING`, with one order, one source document set, one `ORDER_RECEIVED`, and one idempotency row.
- [ ] Add the conflicting unique-key race assertion that the loser raises `IdempotencyConflictError` and never reports replay success.
- [ ] Run `uv run pytest tests/unit/application/test_orders.py tests/integration/test_phase2_creation.py tests/integration/test_phase2_concurrency.py -q --no-cov`, then `uv run ruff check src/opsflow/application/orders.py tests/unit/application/test_orders.py tests/integration/test_phase2_concurrency.py`.
- [ ] Inspect the Phase 2 diff for unchanged fingerprint/database behavior and commit:

```bash
git add src/opsflow/application/orders.py tests/unit/application/test_orders.py tests/integration/test_phase2_concurrency.py
git commit -m "feat: expose order creation replay disposition"
```

### Task 5: Implement the locked ordinary and human-retry generation claims

**Files:**

- Create: `src/opsflow/orchestration/claims.py`
- Create: `tests/unit/orchestration/test_claims.py`
- Create: `tests/integration/test_phase7_concurrency.py`

**Interfaces:**

- Consumes: `OrderState`, `AuditEvent`, `SourceDocument`, `PersistedOrder`, `get_order_for_update(...)`, `get_idempotency_record(...)`, `get_audit_events(...)`, `update_order_snapshot(...)`, `insert_audit_event(...)`, and the Task 2 command/source fields.
- Produces:

```python
class IntakeClaimKind(Enum):
    INITIAL = "INITIAL"
    RESUME_PROCESSING = "RESUME_PROCESSING"
    RESUME_EXTRACTED = "RESUME_EXTRACTED"
    STAND_DOWN = "STAND_DOWN"


@dataclass(frozen=True, slots=True)
class OrchestrationSourceIdentity:
    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    message_id: str | None


@dataclass(frozen=True, slots=True)
class IntakeClaim:
    kind: IntakeClaimKind
    persisted: PersistedOrder
    source_document_id: UUID


async def claim_intake_execution(
    session: AsyncSession,
    *,
    order_id: UUID,
    idempotency_key: str,
    request_fingerprint: str,
    source: OrchestrationSourceIdentity,
    actor: str,
    recorded_at: datetime,
) -> IntakeClaim: ...
```

The function owns one short `async with session.begin()` transaction. It locks
the order with `get_order_for_update(...)`, loads the Phase 2 idempotency row
for the supplied key, and requires that row to point to the locked order and
contain the supplied canonical request fingerprint. It then verifies the
persisted single source document against SHA-256, type, normalized MIME,
basename, and message-ID identity, and loads the chronological audit events
ordered by `occurred_at ASC, id ASC`. It writes and flushes
`ORDER_PROCESSING_STARTED`
for `RECEIVED`, `ORDER_PROCESSING_RESUMED` for an unconsumed
`ORDER_RETRY_RESTORED` at `PROCESSING`, and `ORDER_EXTRACTION_RESUMED` for an
unconsumed restore at `EXTRACTED`. A restore is consumed when the latest
relevant `ORDER_RETRY_RESTORED` has a later matching resume event. Ordinary
`PROCESSING`, ordinary `EXTRACTED`, consumed retry generations, failures not
restored by a reviewer, completed/business-routed states, and `SYNCING` return
`STAND_DOWN` without provider work. A mismatch raises a safe source conflict
and writes no resume event. The transaction commits before the caller parses or
calls any provider.

The Phase 6 `ORDER_RETRY_RESTORED` event is accepted as a restore marker only
when it is the reviewer-produced event in the persisted audit history; n8n has
no code path that can create it. The implementation does not add a retry
counter, lease, heartbeat, attempt table, or state-machine transition from
`EXTRACTED` to `PROCESSING`.

**Steps:**

- [ ] Write pure RED tests for audit sequences: ordinary `ORDER_PROCESSING_STARTED`, unconsumed `ORDER_RETRY_RESTORED`, consumed restore followed by `ORDER_PROCESSING_RESUMED`, consumed extraction restore, ordinary `ORDER_EXTRACTION_COMPLETED`, and restored `SYNCING`.
- [ ] Add pure RED tests proving a missing idempotency row, wrong order binding, or canonical-fingerprint mismatch fails closed before any retry generation can be consumed.
- [ ] Run `uv run pytest tests/unit/orchestration/test_claims.py -q --no-cov`; expected RED identifies the absent claim types and decision helper.
- [ ] Implement the pure audit-generation decision first, including `(occurred_at, id)` ordering and fail-closed stand-down for an unrecognized sequence.
- [ ] Add a transaction-owned claim implementation that locks only the order row, compares source identity, writes one fixed audit event, updates `PROCESSING` only for the initial claim, and returns the typed `IntakeClaim`.
- [ ] Add RED PostgreSQL tests for duplicate ordinary `PROCESSING`, one reviewer-restored `PROCESSING`, two concurrent redeliveries after one restore, restored `EXTRACTED`, mismatched binary/type/message/fingerprint, double consumption, and restored `SYNCING`.
- [ ] Run `uv run pytest tests/unit/orchestration/test_claims.py tests/integration/test_phase7_concurrency.py -q --no-cov`; expected GREEN proves the second locked caller sees the committed resume marker and stands down.
- [ ] Run `uv run ruff check src/opsflow/orchestration/claims.py tests/unit/orchestration/test_claims.py tests/integration/test_phase7_concurrency.py` and inspect event names/descriptions before committing:

```bash
git add src/opsflow/orchestration/claims.py tests/unit/orchestration/test_claims.py tests/integration/test_phase7_concurrency.py
git commit -m "feat: add locked orchestration claim protocol"
```

### Task 6: Compose injectable providers and preserve typed extraction failures

**Files:**

- Create: `src/opsflow/orchestration/composition.py`
- Modify: `src/opsflow/extraction/errors.py` with `ProviderUnavailableError(ProviderError)`
- Modify: `src/opsflow/extraction/gemini.py` to map `google.genai.errors.ServerError` to `ProviderUnavailableError`
- Create: `tests/unit/orchestration/test_composition.py`
- Modify: `tests/unit/extraction/test_gemini.py`

**Interfaces:**

- Consumes: `Settings.gemini_api_key`, `Settings.gemini_model`, `Settings.gemini_timeout_seconds`, `GeminiConfig`, `GeminiProvider`, `FakeProvider`, `OrderExtractor`, `ReviewRuntime`, `BusinessDataProvider`, and `ValidationPolicy`.
- Produces:

```python
@dataclass(frozen=True, slots=True)
class OrchestrationRuntime:
    extraction_provider_factory: Callable[[], LLMProvider]
    business_data_provider: BusinessDataProvider
    policy: ValidationPolicy
    date_provider: ReviewDateProvider


def build_orchestration_runtime(
    settings: Settings,
    *,
    extraction_provider_factory: Callable[[], LLMProvider] | None = None,
    review_runtime: ReviewRuntime | None = None,
) -> OrchestrationRuntime: ...
```

The default no-key local runtime uses a fresh `FakeProvider` per intake with a
synthetic valid structured payload (`CUST-001`, `PO-SYNTHETIC`, `USD`, one
`SKU-001` line, fixed non-future order/delivery dates, and an empty evidence
list). This permits repeated synthetic redelivery without sharing a
destructive provider queue. If all Gemini settings are present, the factory
creates `GeminiProvider(GeminiConfig(...))`; tests always pass an explicit
factory. The existing `build_demo_review_runtime()` supplies the deterministic
trusted provider, policy, and date source unless an explicit test runtime is
passed.

Inspect the installed `google.genai.errors` classes before changing Phase 4
and confirm the current `ServerError` hierarchy. Add exactly one
`ProviderUnavailableError(ProviderError)` and map only `ServerError` to it.
Preserve `ProviderTimeoutError` for timeout classes, preserve malformed
response and client/contract errors as `ProviderError`, and leave unknown
exceptions fail closed. Do not classify by human-readable exception text.

**Steps:**

- [ ] Write RED tests for runtime construction with the default fake factory, explicit fake factory, complete Gemini configuration, missing Gemini configuration, and the exact synthetic provider payload.
- [ ] Run `uv run pytest tests/unit/orchestration/test_composition.py tests/unit/extraction/test_gemini.py -q --no-cov`; expected RED identifies the absent runtime and any missing typed error mapping.
- [ ] Inspect `google.genai.errors` and the installed SDK exception hierarchy with `uv run python -c 'from google.genai import errors; print(errors.__dict__.keys())'`; confirm `ServerError` is the typed temporary availability boundary before implementing the mapping.
- [ ] Implement the small runtime dataclass and factory without changing the Phase 5 review runtime or introducing a provider registry.
- [ ] Add tests proving the fake factory returns a new provider for each execution and that no API key, private data, or provider payload is logged or serialized.
- [ ] Add RED/GREEN tests in `tests/unit/extraction/test_gemini.py` for timeout, `ServerError` availability, malformed JSON, client/contract failure, and unknown exception mapping; run the complete existing extraction unit suite.
- [ ] Run `uv run pytest tests/unit/orchestration/test_composition.py tests/unit/extraction -q --no-cov`, `uv run ruff check src/opsflow/orchestration/composition.py src/opsflow/extraction tests/unit/orchestration/test_composition.py tests/unit/extraction/test_gemini.py`, and `uv run mypy src/opsflow`.
- [ ] Inspect that the Phase 4 provider contract is not weakened and commit:

```bash
git add src/opsflow/orchestration/composition.py src/opsflow/extraction/errors.py src/opsflow/extraction/gemini.py tests/unit/orchestration/test_composition.py tests/unit/extraction/test_gemini.py
git commit -m "feat: compose orchestration provider runtime"
```

### Task 7: Freeze typed failure classification and atomic failure persistence

**Files:**

- Create: `src/opsflow/orchestration/failures.py`
- Create: `tests/unit/orchestration/test_failures.py`
- Create: `tests/integration/test_phase7_failure_matrix.py`

**Interfaces:**

- Consumes: Phase 3 document exceptions, Phase 4 `ProviderTimeoutError`, `ProviderError`, `ProviderUnavailableError`, `ExtractionResponseError`, Phase 5 `BusinessDataProviderError`, `InvalidTrustedDataError`, `ValidationFactsChangedError`, `OrderState.transition_to(...)`, and existing persistence helpers.
- Produces:

```python
class FailureDisposition(Enum):
    RETRYABLE = "RETRYABLE"
    FINAL = "FINAL"


@dataclass(frozen=True, slots=True)
class FailureClassification:
    disposition: FailureDisposition
    origin: OrderState
    target: OrderState
    event_type: str
    description: str


def classify_processing_failure(error: BaseException) -> FailureClassification: ...


def classify_extracted_failure(error: BaseException) -> FailureClassification: ...


async def persist_orchestration_failure(
    session: AsyncSession,
    *,
    order_id: UUID,
    classification: FailureClassification,
    actor: str,
    recorded_at: datetime,
) -> PersistedOrder: ...
```

The processing map is: typed timeout and `ProviderUnavailableError` →
`FAILED_RETRYABLE` with origin `PROCESSING`; malformed/unsafe/ungrounded
provider responses, generic `ProviderError`, document MIME/parse/limit
errors, and unknown extraction errors → `FAILED_FINAL` with origin
`PROCESSING`. The extracted map is: `BusinessDataProviderError` and
`ValidationFactsChangedError` → `FAILED_RETRYABLE` with origin `EXTRACTED`;
`InvalidTrustedDataError` and other known validation-contract failures →
`FAILED_FINAL` with origin `EXTRACTED`. Business `ValidationResult` issues are
not passed to this classifier.

`persist_orchestration_failure(...)` opens one short transaction, locks the
order, verifies the expected origin is still current, applies the legal
transition, updates the order snapshot, writes exactly one fixed
`ORDER_PROCESSING_FAILED` or `ORDER_VALIDATION_FAILED` event, and commits.
Any SQLAlchemy persistence failure rolls back and is surfaced as the safe
unavailable boundary; the caller must not claim a durable `FAILED_*` result.
No provider text, raw document, exception message, token, or client field is
copied into the audit description.

**Steps:**

- [ ] Write RED unit tests for every classification row: timeout, typed availability, malformed response, grounding error, generic provider error, document mismatch/parse/limit, trusted provider unavailable, validation-facts conflict, invalid trusted contract, and unknown provider error.
- [ ] Run `uv run pytest tests/unit/orchestration/test_failures.py -q --no-cov`; expected RED identifies the absent classifier and persistence boundary.
- [ ] Implement the enum, immutable classification, explicit exception-type mapping, and fixed audit descriptions. Do not inspect exception messages or catch all exceptions as retryable.
- [ ] Add PostgreSQL tests that verify state plus audit commit atomically for processing and extracted origins, rollback together on injected audit/state failure, and return the unavailable boundary without a false `FAILED_*` response when the commit cannot complete.
- [ ] Add tests proving `NEEDS_REVIEW`/`READY_FOR_APPROVAL` business validation results do not enter the failure classifier.
- [ ] Run `uv run pytest tests/unit/orchestration/test_failures.py tests/integration/test_phase7_failure_matrix.py tests/integration/test_phase5_application.py -q --no-cov`, then `uv run ruff check src/opsflow/orchestration/failures.py tests/unit/orchestration/test_failures.py tests/integration/test_phase7_failure_matrix.py`.
- [ ] Inspect the transition/event matrix against Phase 1 and Phase 5 and commit:

```bash
git add src/opsflow/orchestration/failures.py tests/unit/orchestration/test_failures.py tests/integration/test_phase7_failure_matrix.py
git commit -m "feat: classify orchestration failures safely"
```

### Task 8: Compose the normal and retry-reconstruction intake application service

**Files:**

- Create: `src/opsflow/application/orchestration.py`
- Create: `tests/unit/application/test_orchestration.py`

**Interfaces:**

- Consumes: Task 2 `OrchestrationIntakeCommand`/`OrchestrationIntakeResult`, Task 4 `create_order_with_disposition(...)` and `fingerprint_order_request(...)`, Task 5 `claim_intake_execution(...)`, Task 6 `OrchestrationRuntime`, `DocumentInput`, `process_document(...)`, `OrderExtractor`, existing `validate_order(...)`, Task 7 classification/persistence, and `ORCHESTRATION_ACTOR`.
- Produces:

```python
async def execute_orchestration_intake(
    session: AsyncSession,
    command: OrchestrationIntakeCommand,
    runtime: OrchestrationRuntime,
    actor: str,
    recorded_at: datetime,
) -> OrchestrationIntakeResult: ...
```

The service derives the basename, normalized MIME, lowercase SHA-256, and one
server-owned `CreateSourceDocumentInput` with all business fields and lines
set to `None`/empty, `storage_reference=None`, and `metadata=()`. It builds a
`CreateOrderInput`, computes its canonical `fingerprint_order_request(...)`,
builds a `DocumentInput` from the same bytes and identity, calls
`create_order_with_disposition(...)`, and passes the unchanged fingerprint and
idempotency key to the locked claim function.

For `STAND_DOWN`, it returns the current persisted state with no provider
call. For `INITIAL` or `RESUME_PROCESSING`, it calls `process_document(...)`,
creates a fresh `OrderExtractor(runtime.extraction_provider_factory())`,
asserts the session is outside a transaction, calls `extract(...)`, and in a
new short transaction persists `PROCESSING -> EXTRACTED` plus
`ORDER_EXTRACTION_COMPLETED`. For `RESUME_EXTRACTED`, it calls the same Phase 3
and Phase 4 steps while leaving the lifecycle state `EXTRACTED`; it checks the
draft SHA/type against the claimed source and does not create a second
snapshot. Both paths then call:

```python
validate_order(
    session,
    order_id,
    source_document_id,
    draft,
    runtime.business_data_provider,
    runtime.policy,
    ValidationContext(runtime.date_provider.current_date()),
    recorded_at,
)
```

The service catches only the typed processing/extracted exceptions owned by
Task 7, persists the legal failure, and returns the committed state. It lets
unexpected programming errors surface in tests. SQLAlchemy failures during
claim, extraction persistence, validation persistence, or failure persistence
become `OrchestrationUnavailableError` without claiming recovery. A successful
new order returns `execution=COMPLETED` and `idempotent_replay=False`; an
existing order, including a successful retry resume, returns
`idempotent_replay=True`; a duplicate owner returns `STANDING_DOWN`.

**Steps:**

- [ ] Write RED unit tests for server-owned input composition, exact SHA/MIME/source fields, no trusted client fields, ordinary pipeline call order, provider boundary assertions, and `STAND_DOWN` short-circuiting before `process_document(...)`.
- [ ] Run `uv run pytest tests/unit/application/test_orchestration.py -q --no-cov`; expected RED identifies the absent application service.
- [ ] Implement source composition and the normal `INITIAL` pipeline with separate claim, extraction-transition, and validation transactions. Do not hold the claim lock while invoking the extractor or validation provider.
- [ ] Add tests for processing-origin provider timeout/final errors and extracted-origin trusted-provider/validation-facts errors using `FakeProvider` and a synthetic provider; assert the classifier is called only after the failed provider boundary.
- [ ] Add RED tests for `RESUME_PROCESSING` rerunning Phase 3/4 then Phase 5, and `RESUME_EXTRACTED` reparsing/re-extracting while remaining `EXTRACTED` before Phase 5; assert no previous in-memory draft is read and no extra snapshot path exists.
- [ ] Implement the retry reconstruction path using the exact redelivered bytes and the already-claimed source identity. Do not call Phase 6 `retry_order(...)` or `Order.retry()` from this service.
- [ ] Run `uv run pytest tests/unit/application/test_orchestration.py tests/unit/documents/test_processor.py tests/unit/extraction/test_extractor.py tests/unit/application/test_validation.py -q --no-cov`, then `uv run ruff check src/opsflow/application/orchestration.py tests/unit/application/test_orchestration.py` and `uv run mypy src/opsflow`.
- [ ] Inspect the service for transaction boundaries, exception narrowing, and no raw/provider payload logging, then commit:

```bash
git add src/opsflow/application/orchestration.py tests/unit/application/test_orchestration.py
git commit -m "feat: compose idempotent document intake pipeline"
```

### Task 9: Wire the real handler and prove PostgreSQL/HTTP behavior end to end

**Files:**

- Modify: `src/opsflow/main.py`
- Modify: `tests/integration/test_phase7_orchestration_api.py`
- Modify: `tests/integration/test_phase7_concurrency.py`
- Create: `tests/integration/test_phase7_pipeline.py`
- Modify: `tests/integration/test_phase7_failure_matrix.py`

**Interfaces:**

- Consumes: `build_orchestration_runtime(...)`, `execute_orchestration_intake(...)`, Task 3 handler seam, and current `create_app(Settings(...))` integration construction.
- Produces: application startup sets `app.state.orchestration_runtime` and installs a closure matching `OrchestrationIntakeHandler` that passes the shared runtime into `execute_orchestration_intake(...)`. The closure never accepts a runtime, actor, or destination from HTTP input.

**Steps:**

- [ ] Write RED integration tests for a valid synthetic document reaching `READY_FOR_APPROVAL` with `201`, a business issue reaching `NEEDS_REVIEW`, same-key terminal replay returning `200` with `idempotent_replay=true`, a created command returning `idempotent_replay=false`, and a fingerprint conflict returning `409`.
- [ ] Run `uv run pytest tests/integration/test_phase7_pipeline.py tests/integration/test_phase7_orchestration_api.py -q --no-cov`; expected RED identifies the missing runtime wiring and real handler.
- [ ] Wire the runtime in `create_app` using the existing demo trusted-data runtime and no-key fake extraction default. Preserve the existing review runtime state and all Phase 6 routes.
- [ ] Add a PostgreSQL-backed simultaneous same-key test that proves one order, one `ORDER_PROCESSING_STARTED`, one provider execution, and one replay disposition for the loser. Use a barrier in the fake provider or claim boundary; do not add sleeps.
- [ ] Add PostgreSQL-backed tests for ordinary `PROCESSING` duplicate stand-down, reviewer-restored `PROCESSING` exactly-once resume, two concurrent retry redeliveries with one provider call, reviewer-restored `EXTRACTED` reconstruction, mismatched source identity, consumed-generation redelivery, and `SYNCING` stand-down.
- [ ] Add tests that inject a persistence failure after an ordinary claim and after a resume claim; assert the HTTP response is `503` when no durable result is proven, and a later duplicate is visible `PROCESSING`/`EXTRACTED` rather than falsely reported recovered.
- [ ] Run `uv run pytest tests/integration/test_phase7_pipeline.py tests/integration/test_phase7_orchestration_api.py tests/integration/test_phase7_concurrency.py tests/integration/test_phase7_failure_matrix.py -q --no-cov`, then `uv run pytest tests/integration/test_phase2_concurrency.py tests/integration/test_phase5_application.py tests/integration/test_phase6_commands.py -q --no-cov`.
- [ ] Run `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/opsflow`, and `uv build`.
- [ ] Inspect the complete M7C diff and query persisted audit sequences for the listed duplicate, resume, and failure cases before committing:

```bash
git add src/opsflow/main.py tests/integration/test_phase7_orchestration_api.py tests/integration/test_phase7_concurrency.py tests/integration/test_phase7_pipeline.py tests/integration/test_phase7_failure_matrix.py
git commit -m "feat: wire Phase 7 intake pipeline"
```

## M7D — n8n Runtime & Version-Controlled Sandbox Workflow

### Task 10: Freshly verify the n8n release and add the minimal local runtime

**Files:**

- Modify: `docker-compose.yml`
- Modify: `.env.example`
- Test/verify: local Docker Compose configuration and the official n8n release/configuration sources; no application test file is required for the configuration-only portion

**Interfaces:**

- Consumes: the resolved M7D pin `n8nio/n8n:2.40.5`, current Docker Compose API service name `api`, PostgreSQL health dependency, and the exact n8n version documentation/release channel checked immediately before runtime work.
- Produces: one `n8n` Community Edition service reachable from a browser at `http://localhost:5678`, able to reach the API at `http://api:8000`, with one named data volume and local ignored encryption/configuration secrets. The API service explicitly receives `OPSFLOW_ORCHESTRATION_TOKEN: ${OPSFLOW_ORCHESTRATION_TOKEN:-}` and `OPSFLOW_REVIEW_DEV_OPERATORS: ${OPSFLOW_REVIEW_DEV_OPERATORS:-}` alongside its database URL.

**2026-09-23 pin resolution:** The original M7A pin was `2.39.10`. Fresh
official stable-channel verification found `stable` targeting
`release/2.40.5` with `prerelease=false`, so independent resolution selected
`2.40.5`. Future work must consume the exact `n8nio/n8n:2.40.5` pin unless
another explicit independent pin resolution occurs.

Before editing `docker-compose.yml`, inspect the authoritative n8n Releases
page and version-specific configuration documentation, record the stable
channel result in the runtime README task, and confirm that `2.40.5` remains
stable. Do not infer stability from an inconsistent `releases/latest` REST
field. If the authoritative channel does not label `2.40.5` stable, stop and
report a pin-resolution conflict; do not silently choose another version.
Never use `latest`.

The Compose service must not depend on the API for startup, must not add Redis,
queue workers, a separate n8n PostgreSQL database, Kubernetes, or cloud
configuration, and must keep the API’s existing PostgreSQL dependency intact.
Use only environment names verified for the exact n8n version. The repository
`.env.example` gets empty entries for `OPSFLOW_ORCHESTRATION_TOKEN`,
`OPSFLOW_REVIEW_DEV_OPERATORS`, and the local n8n encryption configuration;
the actual values exist only in ignored `.env` or the n8n credential store.
No actual token, reviewer operator JSON, or encryption key is written to
`docker-compose.yml`, `.env.example`, or workflow JSON.

**Steps:**

- [ ] Write a runtime checklist with the exact release URL, version documentation URL, selected image tag, and verified configuration names before editing Compose.
- [ ] Run `docker manifest inspect n8nio/n8n:2.40.5` or the equivalent exact-tag image inspection; an unavailable registry is recorded as an environment blocker and never becomes a reason to retag as `latest`.
- [ ] Add the one n8n service, one named volume, port `5678:5678`, and only the verified local environment values. Do not add an API `depends_on` edge.
- [ ] Add empty/non-usable `OPSFLOW_ORCHESTRATION_TOKEN=`, `OPSFLOW_REVIEW_DEV_OPERATORS=`, and the version-verified `N8N_ENCRYPTION_KEY=` entry to `.env.example` without a bearer token, reviewer JSON, Gemini key, or usable encryption key; map the actual n8n setting from ignored `.env` only.
- [ ] Add the API environment mappings exactly as `OPSFLOW_ORCHESTRATION_TOKEN: ${OPSFLOW_ORCHESTRATION_TOKEN:-}` and `OPSFLOW_REVIEW_DEV_OPERATORS: ${OPSFLOW_REVIEW_DEV_OPERATORS:-}`; keep the existing database mapping and do not place literal values in Compose.
- [ ] Run `docker compose --env-file .env.example config --format json` and assert the rendered service uses the exact pin, no Redis/worker service exists, the n8n volume is named, the API service remains reachable by service name, and the two API auth settings render empty rather than as committed secrets.
- [ ] With ignored local `.env` values set, start the API and verify a blank/missing orchestration token receives `401`; then verify the nonblank token reaches the API container without printing it and the configured `OPSFLOW_REVIEW_DEV_OPERATORS` value reaches the API container without printing it.
- [ ] Assert the local review credential can authenticate to the existing review endpoint using the container-propagated reviewer configuration; the recovery demo depends on this mapping.
- [ ] Run the existing backend checks without starting n8n: `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/opsflow`, and `uv build`.
- [ ] Inspect the Compose diff and commit:

```bash
git add docker-compose.yml .env.example
git commit -m "feat: add pinned local n8n runtime"
```

### Task 11: Create and sanitize the actual n8n sandbox workflow

**Files:**

- Create: `fixtures/phase7/synthetic-order.txt`
- Create: `workflows/n8n/opsflow-sandbox-intake.json`
- Create: `workflows/n8n/README.md`
- Create: `tests/unit/workflows/test_n8n_contract.py`
- Test/verify: the pinned local n8n UI or version-specific import/export command

**Interfaces:**

- Consumes: the live M7B/M7C endpoint, the actual pinned n8n node schema, the local credential store, and the stable Webhook event-header contract.
- Produces: a sanitized export with this topology and no business authority:

```text
Webhook (POST /webhook/opsflow-sandbox-intake)
  -> minimal transport field preparation only for a proven pinned-runtime transport limitation
  -> HTTP Request (POST http://api:8000/v1/orchestration/intakes)
  -> Switch on response.state
  -> Respond to Webhook branches
```

The workflow must forward one binary `document`, `document_type`, optional
`message_id`, and the exact incoming `X-OpsFlow-Event-Id` as
`Idempotency-Key`. The HTTP Request node uses an n8n credential reference for
the OpsFlow Bearer token, not a literal token. The Switch compares only the
server-returned state and has explicit `NEEDS_REVIEW`, `READY_FOR_APPROVAL`,
`FAILED_RETRYABLE`, `FAILED_FINAL`, `PROCESSING`, `EXTRACTED`, and safe default
branches. The retryable branch visibly tells the operator to use the existing
review UI; it does not invoke `Order.retry()`.

Create/import/configure the workflow in the running pinned n8n instance and
export the result from that instance. Do not invent node JSON from memory.
After export, remove execution history, private data, embedded headers with
secrets, usable credential values, and raw document content while preserving
the credential reference and required node settings. The README must document
that a clean clone starts n8n, creates/relinks the local credential in the UI,
imports the sanitized export, and never edits the bearer token into JSON.

**Steps:**

- [ ] Write `tests/unit/workflows/test_n8n_contract.py` first. Its named assertions load `workflows/n8n/opsflow-sandbox-intake.json` and check the required node types, POST URL, multipart fields, event-ID header forwarding, credential reference, state branches, absence of AI/business nodes, absence of execution history/private data, and absence of secret-looking values.
- [ ] Run `uv run pytest tests/unit/workflows/test_n8n_contract.py -q --no-cov` while the export is absent; expected RED is a file-not-found or named contract assertion, and no unsafe workflow is committed.
- [ ] Start the exact runtime with `docker compose up -d postgres api n8n` and open the n8n editor at `http://localhost:5678`; do not proceed with a different image tag.
- [ ] Add the fixed sanitized text fixture at `fixtures/phase7/synthetic-order.txt`; keep it free of customer data, credentials, and provider-specific response content.
- [ ] Create the local OpsFlow Bearer credential in n8n using the ignored `OPSFLOW_ORCHESTRATION_TOKEN` value, and record the UI relinking steps in `workflows/n8n/README.md` without recording the value.
- [ ] Create the Webhook, HTTP Request, Switch, and Respond to Webhook nodes in the actual n8n version; configure the binary multipart field and stable header forwarding through the UI. Do not configure retry behavior in this task.
- [ ] Run one synthetic known-good document through the active workflow and inspect the API request in local logs without copying its token or raw content into the export.
- [ ] Export the workflow, sanitize it, and write the clean-clone import and stable Webhook path instructions. Include the exact synthetic document type, filename, MIME, event ID reuse rule, and the browser Retry plus subsequent same-document resubmission flow.
- [ ] Run `uv run pytest tests/unit/workflows/test_n8n_contract.py -q --no-cov`, `uv run ruff check tests/unit/workflows/test_n8n_contract.py`, `uv run ruff format --check tests/unit/workflows/test_n8n_contract.py`, `jq empty workflows/n8n/opsflow-sandbox-intake.json`, and the full JSON secret/private-data inspection; expected GREEN proves the export satisfies the generated-node contract.
- [ ] Commit the fixture, workflow export, contract tests, and README as one coherent M7D workflow task:

```bash
git add fixtures/phase7/synthetic-order.txt workflows/n8n/opsflow-sandbox-intake.json workflows/n8n/README.md tests/unit/workflows/test_n8n_contract.py
git commit -m "feat: add n8n sandbox intake workflow and contract tests"
```

### Task 12: Verify the pinned n8n runtime, import, and selective-retry capability

**Files:**

- Modify: `workflows/n8n/README.md` with exact pinned-runtime evidence and clean-clone import instructions
- Test/verify: `docker-compose.yml`, the pinned n8n editor/runtime, local credential store, and the committed workflow export

**Interfaces:**

- Consumes: the committed JSON and contract suite from Task 11, the exact `n8nio/n8n:2.40.5` runtime, and local ignored credentials; no n8n Cloud, public Webhook, or live provider.
- Produces: README evidence that the pinned runtime imports and executes the sanitized workflow and a frozen retry-capability decision for Task 13.

Task 12 must inspect the exact pinned n8n version's HTTP Request node and
node-error options before any workflow retry setting is changed. Capture in
`workflows/n8n/README.md` the n8n version, HTTP Request node version, the exact
option names/values for full-response status output, never-error/error-output
behavior, retry controls, and standard-node connections available for handling
connection errors and HTTP statuses. The evidence must distinguish normal 2xx
responses, HTTP `401`, `409`, `422`, HTTP `503`, and connection/node transport
errors. It must show that persisted `FAILED_RETRYABLE` is a normal 2xx business
response whose body routes by state, not a transport retry.

The Task 12 decision is one of two explicit outcomes. If native Retry On Fail
can filter only connection errors and HTTP `503` with a maximum of two retry
attempts while excluding `401`, `409`, `422`, persisted `FAILED_RETRYABLE`,
and generic HTTP `500`, record the exact proven settings. Otherwise, record the
standard-node-only fallback supported by the pinned runtime: full response
status output or never-error behavior, error-output handling for connection
failures, Switch/If status checks, Edit Fields for a bounded attempt value, and
Wait before a second request. The fallback retries only connection errors and
HTTP `503`; it does not retry generic `500` or any `401`/`409`/`422` response.
If neither native filtering nor the standard-node-only fallback can satisfy
this matrix without Code/AI/business logic or a new architecture, stop and
report a design/runtime contradiction before Task 13. In either supported
outcome, exhaustion of the two-attempt budget produces a visible unavailable
response and never claims that lifecycle work recovered.

**Steps:**

- [ ] Run `docker compose --env-file .env.example config`, `docker compose ps`, `jq empty workflows/n8n/opsflow-sandbox-intake.json`, and the Task 11 contract suite; record the exact image tag, node versions, service health, and clean-clone import result in the README.
- [ ] In the pinned n8n editor, inspect the HTTP Request node's actual Retry On Fail, response, error-output, and full-response controls and record the exact evidence before changing the workflow.
- [ ] Exercise the approved status matrix with the local API's safe `401`, `409`, and `422` responses, a deterministic `503` application-unavailable response, the M7C integration response for persisted `FAILED_RETRYABLE` as a 2xx business response, and a connection failure; record only bounded status/outcome observations, never credentials or raw content.
- [ ] Decide and document native filtered retry or the standard-node-only fallback using the exact pinned-version options. A generic blanket Retry On Fail setting is not an acceptable result.
- [ ] Commit only the verified runtime/import/retry evidence:

```bash
git add workflows/n8n/README.md
git commit -m "docs: verify pinned n8n runtime contract"
```

## M7E — Cross-Boundary Reliability & Demo Hardening

### Task 13: Harden bounded transport retry and visible recovery routing

**Files:**

- Modify: `workflows/n8n/opsflow-sandbox-intake.json`
- Modify: `workflows/n8n/README.md`
- Create: `tests/integration/test_phase7_transport.py`
- Modify: `tests/unit/workflows/test_n8n_contract.py`
- Create: `scripts/phase7_seed_retryable_demo.py`
- Create: `tests/integration/test_phase7_demo_seed.py`

**Interfaces:**

- Consumes: the actual M7D export and retry-capability evidence, the HTTP status contract, the M7C persistence/runtime behavior, the committed synthetic fixture, and the existing Phase 6 review UI/API.
- Produces: a bounded cross-boundary behavior with at most two n8n transport retry attempts for connection failures and HTTP `503` only; no retry for `401`, `409`, `422`, generic HTTP `500`, or persisted `FAILED_RETRYABLE`; a visible unavailable response after budget exhaustion; visible current-state/default branches; and one executable synthetic retryable-case seed helper.

```python
type DemoRetryOrigin = Literal["processing", "extracted"]


@dataclass(frozen=True, slots=True)
class DemoSeedResult:
    order_id: UUID
    state: OrderState
    failure_origin: OrderState | None


async def seed_retryable_demo(
    origin: DemoRetryOrigin,
    settings: Settings,
) -> DemoSeedResult: ...
```

The CLI exposes only `--origin processing` and `--origin extracted`, builds a
database engine/sessionmaker from the supplied `Settings.database_url` (the
same local `OPSFLOW_DATABASE_URL` used by the Docker API), and calls the real
`execute_orchestration_intake(...)` service. The processing
runtime uses `FakeProvider([ProviderUnavailableError(...)])`. The extracted
runtime uses the deterministic successful fake extraction and a local
`BusinessDataProvider` implementation whose sole method raises
`BusinessDataProviderError()`. No SQL row is manually inserted or edited.

The workflow must preserve the same binary and `X-OpsFlow-Event-Id` on every
transport retry. A pre-claim HTTP `503` may be repeated safely. A post-claim
ambiguous `503` must not be described as recovered; the next delivery can
return `PROCESSING` or `EXTRACTED` and must not execute a second provider call.
Connection/node transport errors receive the same bounded retry budget. No
generic HTTP `500` is retried. The visible `FAILED_RETRYABLE` branch is a
review handoff and is a normal 2xx business response. The browser Retry click
uses the existing review API and does not carry raw bytes; the caller must
explicitly resubmit the same document and stable event ID.

`scripts/phase7_seed_retryable_demo.py` is local synthetic demo tooling only;
it is never imported by the API and never edits persistence rows directly. It
accepts exactly `--origin processing` or `--origin extracted`, uses the real
`execute_orchestration_intake(...)` service with deterministic injected
providers, reads the committed `fixtures/phase7/synthetic-order.txt`, and
uses these exact redelivery identities:

| Seed origin | Event/idempotency key | Message ID | Document identity |
| --- | --- | --- | --- |
| `processing` | `phase7-processing-001` | `phase7-message-processing-001` | `synthetic-order.txt`, `EMAIL_BODY`, `text/plain` |
| `extracted` | `phase7-extracted-001` | `phase7-message-extracted-001` | `synthetic-order.txt`, `EMAIL_BODY`, `text/plain` |

The processing seed injects a typed temporary extraction-provider failure and
must finish `FAILED_RETRYABLE` with `failure_origin=PROCESSING`. The extracted
seed injects a successful deterministic extraction followed by a typed
retryable trusted-business-data failure and must finish
`FAILED_RETRYABLE` with `failure_origin=EXTRACTED`. The helper uses no network,
live Gemini, or credentials; it prints only the bounded synthetic origin,
order ID, state, and failure origin. The subsequent n8n request uses the same
fixture bytes, filename, type, MIME, message ID, and event ID for that origin.

**Steps:**

- [ ] Write RED transport tests for connection/HTTP-503 bounded retry, no retry on `401`, `409`, `422`, generic `500`, or persisted `FAILED_RETRYABLE`, stable event ID/binary preservation, current-state handling for `202`, and safe default handling for an unknown state.
- [ ] Run `uv run pytest tests/integration/test_phase7_transport.py tests/integration/test_phase7_demo_seed.py tests/unit/workflows/test_n8n_contract.py -q --no-cov`; expected RED identifies missing retry/default assertions, an over-broad retry policy, or an absent deterministic seed seam.
- [ ] Write `scripts/phase7_seed_retryable_demo.py` with an argparse CLI accepting exactly `--origin processing` and `--origin extracted`; compose the real application service with a `FakeProvider` temporary extraction failure for processing and a deterministic successful extraction plus retryable trusted-data provider failure for extracted.
- [ ] Add `tests/integration/test_phase7_demo_seed.py` proving both CLI/application seams create the intended persisted `FAILED_RETRYABLE` origin, audit sequence, source identity, and no bypassed lifecycle transition.
- [ ] Run `uv run pytest tests/integration/test_phase7_demo_seed.py -q --no-cov`; expected GREEN requires the real service to create both retryable states without direct SQL row editing or network access.
- [ ] Before changing the workflow retry configuration, run both seed commands, capture their 2xx `FAILED_RETRYABLE` responses and persisted origins, and record that the workflow must route those responses without transport retry.
- [ ] Apply the exact Task 12 retry decision to the pinned n8n export: use native status-filtered retry only when the recorded runtime evidence proves it retries connection errors and HTTP `503` only; otherwise use the recorded standard-node-only full-response/error-output, Switch/If, Edit Fields, and Wait fallback. Do not enable blanket Retry On Fail.
- [ ] Add integration assertions that a persisted retryable failure is returned as a business response and does not cause an unbounded transport loop.
- [ ] Add a recovery-path test that performs `FAILED_RETRYABLE(failure_origin=PROCESSING) -> reviewer Retry -> PROCESSING`, resubmits identical bytes/key, and proves one `ORDER_PROCESSING_RESUMED`; repeat for `EXTRACTED` and prove parse/extraction reconstruction before Phase 5.
- [ ] Add a duplicate recovery test proving the browser command alone is insufficient and a second same-document redelivery is required; a concurrent second redelivery sees the consumed marker.
- [ ] Run `uv run pytest tests/integration/test_phase7_transport.py tests/integration/test_phase7_demo_seed.py tests/integration/test_phase7_pipeline.py tests/integration/test_phase7_concurrency.py -q --no-cov`, then rerun `uv run pytest tests/unit/workflows/test_n8n_contract.py -q --no-cov`.
- [ ] Inspect the workflow contract for a maximum of two attempts, exact HTTP-503-only status filtering or the proven standard-node fallback, no generic-500 retry, no lifecycle Retry call, and no scheduler/polling loop; commit:

```bash
git add workflows/n8n/opsflow-sandbox-intake.json workflows/n8n/README.md tests/integration/test_phase7_transport.py tests/unit/workflows/test_n8n_contract.py scripts/phase7_seed_retryable_demo.py tests/integration/test_phase7_demo_seed.py
git commit -m "test: harden Phase 7 transport recovery"
```

### Task 14: Perform the local Docker/n8n sandbox demonstration and clean-clone handoff

**Files:**

- Modify: `workflows/n8n/README.md` with verified commands/results only
- Test/verify: `docker-compose.yml`, the committed workflow export, the local API, the existing review UI, PostgreSQL, and synthetic fixtures; no runtime source change is authorized by this task

**Interfaces:**

- Consumes: all M7B–M7D commits, the approved M7E transport contract, the local ignored service token/encryption key, and the fixed synthetic document fixture.
- Produces: reproducible local evidence for normal intake, duplicate delivery, malformed input, unavailable API, retryable/final routing, reviewer Retry plus same-document redelivery, abandoned claim visibility, secret posture, and clean-clone import.

Run the following bounded manual sequence and record only sanitized outcomes
in `workflows/n8n/README.md`:

```bash
docker compose up -d --build postgres api n8n
uv run alembic upgrade head
curl -i -X POST http://localhost:5678/webhook/opsflow-sandbox-intake \
  -H 'X-OpsFlow-Event-Id: phase7-synthetic-001' \
  -F 'document=@fixtures/phase7/synthetic-order.txt;type=text/plain' \
  -F 'document_type=EMAIL_BODY' \
  -F 'message_id=phase7-message-001'
```

The known-good response must travel Webhook → API → state Switch → response
and reach the backend-authoritative route. Re-submit the exact same command
and event ID, then inspect the response/audit/provider evidence for no second
business execution. Submit an invalid `document_type` and a different binary
under the same event ID to prove safe `422`/`409` handling. Stop the API with
`docker compose stop api`, invoke the Webhook once to capture bounded
unavailable behavior, then restore the API and verify no transport response
claims durable recovery. The final-state and retryable-state API integration
tests provide the deterministic failure matrix; the workflow run verifies that
their server states are displayed without selecting lifecycle destinations.

The recovery demonstration uses the executable M7E seed helper, never a pytest
function as an implicit data-creation step. Start the existing Vite frontend
in a separate terminal because Compose has no frontend service:

```bash
npm --prefix web run dev -- --host 127.0.0.1
```

The existing Vite proxy sends `/v1` requests to `http://127.0.0.1:8000`. With
the ignored local reviewer credential assigned to `PHASE7_REVIEW_TOKEN`, verify
the proxy without printing the token:

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer ${PHASE7_REVIEW_TOKEN}" \
  http://127.0.0.1:5173/v1/review/orders
```

Run each seed against the same local database used by the Docker API:

```bash
processing_seed="$(uv run python scripts/phase7_seed_retryable_demo.py --origin processing)"
printf '%s\n' "$processing_seed"
PROCESSING_ORDER_ID="$(printf '%s' "$processing_seed" | jq -r '.order_id')"

extracted_seed="$(uv run python scripts/phase7_seed_retryable_demo.py --origin extracted)"
printf '%s\n' "$extracted_seed"
EXTRACTED_ORDER_ID="$(printf '%s' "$extracted_seed" | jq -r '.order_id')"
```

For `PROCESSING`, open the review UI, authenticate with the configured reviewer
credential, click Retry for `PROCESSING_ORDER_ID`, and confirm through the
review UI or its proxied detail request that the state is `PROCESSING`. Then
use the parallel redelivery pattern below with the processing identity.

For `EXTRACTED`, repeat the UI Retry action for `EXTRACTED_ORDER_ID`, confirm
the restored state is `EXTRACTED`, then use the same parallel redelivery pattern
with `phase7-extracted-001` and `phase7-message-extracted-001`. The first valid
redelivery set must produce exactly one `ORDER_PROCESSING_RESUMED` or
`ORDER_EXTRACTION_RESUMED` event and the final routed state. A parallel
redelivery uses two identical background requests and a wait, not a prose-only
concurrency claim. The first owner consumes the generation; the other request
observes the consumed marker or the already-current result and performs no
second resume.

```bash
curl -sS -X POST http://localhost:5678/webhook/opsflow-sandbox-intake \
  -H 'X-OpsFlow-Event-Id: phase7-processing-001' \
  -F 'document=@fixtures/phase7/synthetic-order.txt;type=text/plain' \
  -F 'document_type=EMAIL_BODY' \
  -F 'message_id=phase7-message-processing-001' > /tmp/phase7-replay-a.json &
first_pid=$!
curl -sS -X POST http://localhost:5678/webhook/opsflow-sandbox-intake \
  -H 'X-OpsFlow-Event-Id: phase7-processing-001' \
  -F 'document=@fixtures/phase7/synthetic-order.txt;type=text/plain' \
  -F 'document_type=EMAIL_BODY' \
  -F 'message_id=phase7-message-processing-001' > /tmp/phase7-replay-b.json &
second_pid=$!
wait "$first_pid" "$second_pid"
```

Inspect only persisted state, audit counts, and snapshot counts; do not require
a manual provider-call counter that the running application does not expose:

```bash
curl -fsS "http://127.0.0.1:8000/v1/orders/${PROCESSING_ORDER_ID}" \
  | jq '{state, failure_origin}'
curl -fsS "http://127.0.0.1:8000/v1/orders/${PROCESSING_ORDER_ID}/audit" \
  | jq '[.items[] | select(.event_type == "ORDER_PROCESSING_RESUMED")] | length'
docker compose exec -T postgres psql -U opsflow -d opsflow -Atc \
  "SELECT count(*) FROM extraction_snapshots WHERE order_id = '${PROCESSING_ORDER_ID}'"
```

Repeat the same state, audit, and snapshot inspection for `EXTRACTED`, selecting
`ORDER_EXTRACTION_RESUMED`. The Phase 5 validation path must reconstruct parsing
and extraction before creating the successful immutable snapshot. Automated
PostgreSQL concurrency tests, not manual logging, prove exactly-one provider
execution. The automated abandoned-claim integration evidence records that an
ordinary claim or consumed resume claim can remain visible without reclaim; the
local demo does not add a lease, heartbeat, recovery switch, scheduler,
mailbox integration, or raw storage to make that evidence possible.

**Steps:**

- [ ] Run the local command sequence against a clean local database, start the separate Vite frontend command, and confirm the API, PostgreSQL, n8n, Vite UI, and `/v1` proxy are reachable.
- [ ] Execute the normal, duplicate, malformed, conflicting, and unavailable-API scenarios; record response statuses and sanitized state results.
- [ ] Run both exact seed commands, complete reviewer Retry in the existing UI, redeliver the exact same document/event identity, and inspect persisted state, resume-event counts, and extraction-snapshot counts.
- [ ] Run the reproducible two-background-request pattern for each restored origin; assert one resume event and one current-state response after the locked generation is consumed.
- [ ] Record the automated PostgreSQL abandoned-claim evidence as the source for the limitation; do not claim a manual provider count or automatic reclaim.
- [ ] Run `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src/opsflow`, `uv build`, `npm --prefix web test -- --run`, `npm --prefix web run lint`, and `npm --prefix web run build`.
- [ ] Run the repository’s Gitleaks command from `.github/workflows/ci.yml`, the workflow JSON contract test, `docker compose config`, and a clean-clone import rehearsal using only ignored local secrets.
- [ ] Inspect the complete diff, the sanitized export, the README commands, and the working tree; commit:

```bash
git add workflows/n8n/README.md
git commit -m "docs: document Phase 7 sandbox verification"
```

## M7F — Later Audit / Closeout Boundary

M7F is not an implementation task in this plan and no audit file is created
here. After M7E’s exact-head candidate independently passes, a fresh read-only
whole-Phase-7 audit must inspect:

1. actual backend code, tests, migrations, settings, and transaction evidence;
2. the generated workflow JSON and n8n node configuration;
3. Docker Compose startup, service reachability, named volume, and ignored secrets;
4. PostgreSQL concurrency evidence for ordinary and retry-restored claims;
5. failure classification, `201`/`200`/`202`/`409`/`503` semantics, and no false recovery;
6. clean-clone import and synthetic normal/duplicate/recovery behavior;
7. secret scans, cost posture, scope, and absence of Phase 8+ integrations.

The audit reviewer creates `docs/audits/phase-7-audit.md` only after the
read-only audit passes and records findings from actual evidence. Any finding
is remediated minimally in a focused candidate; the audit is not a feature
task. Only a separate closeout commit may mark M7F and Phase 7 complete, and a
PR/PR CI/merge gate follows that closeout.

## Test / CI Strategy

The existing gates remain authoritative:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/opsflow
uv run pytest
uv build
npm --prefix web test -- --run
npm --prefix web run lint
npm --prefix web run build
```

PostgreSQL-backed integration tests run against the existing PostgreSQL 16
service and prove database uniqueness, row locking, audit ordering, atomic
failure writes, and retry-generation consumption. Unit tests use
`FakeProvider`, scripted synthetic trusted data, and deterministic document
bytes. No test calls live Gemini, n8n Cloud, Gmail, Slack, Odoo, or HubSpot.

The workflow contract suite runs from committed JSON without starting n8n and
has its genuine RED state before the export is created in Task 11. Task 12
records exact pinned-runtime retry-option evidence; Task 13 owns only HTTP
`503`/connection retry behavior, never generic `500`. The manual M7D/M7E
evidence starts the pinned local Docker service, starts the Vite frontend in a
separate terminal, and uses the internal API hostname `http://api:8000` from
n8n and `localhost` only from the host. No public Webhook, external SaaS
account, browser automation framework, or full end-to-end CI dependency is
added. The recovery demo uses the local seed script and persisted state/audit/
snapshot inspection; it does not require a manual provider-call counter.

## Failure-Matrix Ownership

| Design category | Required examples | Owning task/tests |
| --- | --- | --- |
| Pre-creation transport | Missing/wrong token, blank key, invalid type, missing binary, malformed multipart, `FORM` | Tasks 1–3: `test_phase7_auth.py`, `test_phase7_orchestration_api.py` |
| Processing final | MIME/type mismatch, corrupt PDF/XLSX/CSV/text, parser limits, malformed/unsafe provider result, grounding failure | Tasks 6–7 and `test_phase7_failure_matrix.py` |
| Processing retryable | Timeout and typed temporary provider availability | Tasks 6–7 and `test_phase7_failure_matrix.py` |
| Extracted retryable | Trusted provider unavailable and validation-facts conflict | Tasks 7–9 and `test_phase7_failure_matrix.py` |
| Extracted final | Invalid trusted provider contract | Tasks 7–9 and `test_phase7_failure_matrix.py` |
| Business result | Unknown SKU, price issue, other Phase 5 issue → `NEEDS_REVIEW`; clean order → `READY_FOR_APPROVAL` | Tasks 8–9 and `test_phase7_pipeline.py` |
| Persistence ambiguity | Failure before claim, after claim, after resume claim, and no false durable `FAILED_*` claim | Tasks 7–9, 13, and 14 |
| Transport retry selectivity | Connection error and HTTP `503` retry only; HTTP `500`, `401`, `409`, `422`, and persisted `FAILED_RETRYABLE` 2xx do not retry | Tasks 12–13: `test_phase7_transport.py`, workflow contract suite |

## Self-Review of This Plan

### Spec coverage

- Document control, scope, authority, and non-goals → Global Constraints, Tasks 1–3, and the file map.
- HTTP boundary, auth, multipart, response DTOs, and status semantics → Tasks 1–3 and 9.
- Phase 2 fingerprint/idempotency and replay disposition → Task 4.
- Ordinary claim, human-restored processing/extracted claims, audit-generation consumption, and lock boundary → Task 5.
- Phase 3 parsing, Phase 4 extraction, typed provider errors, Phase 5 validation, and runtime composition → Tasks 6–8.
- Failure classification, failure-origin persistence, business-result separation, and `503` ambiguity → Tasks 7–9 and 13.
- Raw-byte/no-snapshot retry reconstruction, no `SYNCING` resume, no leases, and abandoned claims → Tasks 5, 8, 9, 13, and 14.
- n8n pin, Compose topology, workflow export, credential handling, branch safety, and version verification → Tasks 10–12.
- Synthetic recovery UX, deterministic processing/extracted seed tooling, bounded transport retry, clean-clone verification, Vite startup, and persisted state/audit/snapshot evidence → Tasks 13–14.
- M7F independent audit and separate closeout/status boundary → M7F section.

### Type and interface consistency

The plan defines one command/result contract in Task 2, one created/replayed
wrapper in Task 4, one claim result in Task 5, one runtime in Task 6, one
failure classification boundary in Task 7, and one application service in
Task 8. Later tasks consume those exact names and do not introduce alternate
idempotency, retry, provider, or HTTP result types.

### Scope and safety review

The file map contains no migration, raw storage, lease/heartbeat table, job
queue, generic framework, external integration, direct AI workflow node, or
frontend feature. The only anticipated dependency is the multipart parser
required by the selected FastAPI transport implementation, and Task 2 verifies
that requirement before changing the lockfile. Every provider and trusted-data
test uses deterministic doubles; every workflow secret remains outside source
control.

### Independent-review refinement audit

- The plan gate is now before Task 1: independent plan PASS, separate docs-only M7A closeout marking `M7A COMPLETE`/`M7B NOT STARTED`, independent closeout verification, then Task 1.
- Task 2 declares `python-multipart` directly when FastAPI’s selected `File`/`Form`/`UploadFile` implementation directly requires it, inspects dependency ownership, and reads at most `max_input_bytes + 1` bytes with exact-max/max-plus-one tests.
- Task 10 freezes explicit API Compose mappings for `OPSFLOW_ORCHESTRATION_TOKEN` and `OPSFLOW_REVIEW_DEV_OPERATORS`, empty `.env.example` values, blank-token failure, nonblank container propagation, reviewer propagation, and no committed usable secret.
- Task 12 captures the exact pinned n8n HTTP Request/node-error capability before Task 13 workflow edits. Task 13 retries only connection errors and HTTP `503`, or stops on a proven capability contradiction; it never enables indiscriminate Retry On Fail.
- Task 11 creates the workflow contract suite before the export and records genuine RED followed by GREEN in one coherent workflow/test/README commit.
- Task 14 starts Vite separately, verifies its `/v1` proxy, runs the exact M7E seed helper for both origins, performs same-identity recovery and reproducible parallel redelivery, and inspects persisted state/audit/snapshot counts without requiring a provider-call counter.
- Tasks 10–14, the file map, failure matrix, CI strategy, and stop point use the same fourteen-task numbering and M7B/M7C/M7D/M7E/M7F ownership.
- The required pre-commit scans cover unfinished markers, vague wording, secrets, links, and diff whitespace; no runtime artifact or status change belongs to this refinement.

## Implementation Stop Point

This document stops at the implementation-plan candidate/refinement. It does
not authorize Task 1 execution, M7B start, M7F audit creation, milestone status
changes, or a PR. After this plan independently passes, a separate docs-only
M7A closeout may mark `M7A COMPLETE` and `M7B NOT STARTED`; only after that
closeout is independently verified may implementation proceed through the
stated task and review gates.
