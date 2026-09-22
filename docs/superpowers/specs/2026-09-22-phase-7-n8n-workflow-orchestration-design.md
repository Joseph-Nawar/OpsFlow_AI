# Phase 7 — n8n Workflow Orchestration Contract & Design

## Document control

| Field | Value |
| --- | --- |
| Repository | `Joseph-Nawar/OpsFlow_AI` |
| Phase | Phase 7 — n8n Workflow Orchestration |
| Current milestone | M7A — Orchestration Contract & Design |
| Design date | 2026-09-22 |
| Branch | `phase/7-n8n-workflow-orchestration` |
| Starting main SHA | `809d201555af1afe5f79c202dfbc2bb259425e6b` |
| Phase 6 status | Fully merged and independently audited |
| Design authority | Authoritative design boundary; it does not authorize implementation by itself |
| Runtime status | No Phase 7 runtime behavior exists merely because this specification exists |

This is the M7A design candidate. M7A remains `IN PROGRESS` until the design
and its later separately reviewed implementation plan are approved. This file
does not contain that implementation plan. The repository status is tracked in
the [project roadmap](../../roadmap/project-roadmap.md).

### Governing sources

- [Project roadmap](../../roadmap/project-roadmap.md)
- [System overview](../../architecture/system-overview.md)
- [Phase 1 domain model](../../architecture/domain-model.md)
- [Development guide](../../development/development-guide.md)
- [Phase 2 design](2026-09-14-phase-2-persistence-api-design.md) and [Phase 2 audit](../../audits/phase-2-audit.md)
- [Phase 3 design](2026-09-14-phase-3-document-ingestion-design.md) and [Phase 3 audit](../../audits/phase-3-audit.md)
- [Phase 4 design](2026-09-17-phase-4-structured-ai-extraction-design.md) and [Phase 4 audit](../../audits/phase-4-audit.md)
- [Phase 5 design](2026-09-17-phase-5-deterministic-validation-design.md) and [Phase 5 audit](../../audits/phase-5-audit.md)
- [Phase 6 design](2026-09-19-phase-6-human-review-application-design.md) and [Phase 6 audit](../../audits/phase-6-audit.md)

## 1. Purpose, baseline, and current repository evidence

Phase 7 introduces a locally demonstrable n8n orchestration boundary for one
synthetic document intake. It does not turn n8n into a second business-logic
runtime and it does not broaden the Phase 1 order state machine.

The design is based on the starting repository, not on a presumed future API:

- `src/opsflow/api/orders.py` exposes the existing JSON `POST /v1/orders`
  creation/read API, list API, and audit read. Its create operation persists a
  `RECEIVED` order and uses the Phase 2 idempotency authority.
- `src/opsflow/api/review.py` exposes Phase 6 human-review reads and commands.
  Its bearer credentials resolve to configured human operator roles and are not
  suitable as machine credentials.
- `src/opsflow/documents/processor.py` owns deterministic canonical parsing and
  rejects `FORM`; supported Phase 3 types are email body/plain text, PDF, XLSX,
  and CSV.
- `src/opsflow/extraction/extractor.py` owns the `CanonicalDocument` to
  `ExtractionDraft` boundary through `OrderExtractor.extract(...)` and strict
  response/evidence grounding.
- `src/opsflow/application/validation.py` owns trusted-data lookup,
  deterministic validation, extraction-snapshot persistence, legal state
  transitions, and atomic routing to `NEEDS_REVIEW` or
  `READY_FOR_APPROVAL`.
- `src/opsflow/main.py` currently composes only the existing orders and review
  routers. `docker-compose.yml` currently contains only the API and PostgreSQL.

The current public HTTP API therefore does **not** expose a safe end-to-end
document-processing, extraction, and validation command for n8n. Exposing the
existing internal stages one at a time would leak internal value objects and
would make transport choreography responsible for business correctness. Phase
7 defines one dedicated boundary instead.

## 2. Architectural decision

Use a thin n8n workflow backed by a dedicated authenticated OpsFlow
orchestration HTTP boundary:

```text
synthetic sandbox trigger
        |
        v
     n8n Webhook
        |
        v
 authenticated HTTP Request
        |
        v
OpsFlow orchestration intake API
        |
        v
existing Python processing/extraction/validation pipeline
        |
        v
authoritative persisted Order state
        |
        v
n8n Switch on server-returned state
        |
        v
 sandbox response branch
```

The durable rule is:

> n8n orchestrates; Python owns business authority.

n8n may receive triggers, carry a binary document between integration
boundaries, call OpsFlow, perform simple routing, and perform bounded safe
transport retries. Python owns document processing, extraction, validation,
trusted-data policy, persistence, lifecycle legality, idempotency truth,
auditability, and side-effect safety.

### Rejected alternatives

1. **Fine-grained network endpoints such as `/process`, `/extract`, and
   `/validate`.** These would require passing internal `CanonicalDocument` and
   `ExtractionDraft` objects through n8n or adding persistence merely for
   workflow plumbing. The existing Python service composition is the smaller
   and safer boundary.
2. **Document parsing, LLM extraction, or business rules in n8n.** A canvas
   expression or JavaScript node cannot become the authority for parsing,
   evidence grounding, trusted business data, validation, approval, or state
   transitions. It would duplicate Phases 3–5 and make correctness dependent
   on workflow editing.
3. **A generic Python workflow engine alongside n8n.** The current product has
   one workflow tool and one business application. A second orchestration
   engine would add state, scheduling, and failure semantics without a current
   requirement.

## 3. Authority boundary and scope

### n8n owns only

- synthetic webhook receipt in the Phase 7 sandbox;
- stable event-header forwarding;
- multipart transport to the OpsFlow boundary;
- simple state-based routing of the response;
- branch-specific sandbox responses;
- bounded transport retries for network/5xx conditions before a durable
  application result is available.

### OpsFlow/Python owns

- source identity and SHA-256 computation;
- filename and uploaded MIME handling;
- Phase 3 document processing and limits;
- Phase 4 provider-neutral extraction and evidence grounding;
- Phase 5 trusted business-data lookup, rules, and routing;
- Phase 1 legal `OrderState` transitions;
- Phase 2 idempotency records and fingerprint conflicts;
- extraction snapshot persistence;
- audit records and failure-origin recording;
- all future external side-effect safety contracts.

n8n must not own parsing, extraction semantics, validation, trusted business
data, lifecycle legality, approval authority, trusted-order mutation,
business idempotency, audit authority, retry destinations, or external
side-effect policy.

## 4. Orchestration HTTP boundary

### 4.1 Primary command

The future dedicated namespace is:

```text
POST /v1/orchestration/intakes
```

It is a single-document sandbox intake command. It is not a general-purpose
workflow API and it does not expose Phase 3, 4, or 5 internal objects.

#### Request headers

| Header | Required | Contract |
| --- | --- | --- |
| `Authorization` | Yes | `Bearer <configured orchestration service token>` |
| `Idempotency-Key` | Yes | Stable source-event identifier, nonblank, at most 128 characters |
| `Content-Type` | Yes | `multipart/form-data` with one `document` part |

The service rejects missing, malformed, or unknown bearer credentials with the
same bounded authentication error. The caller cannot provide an actor, role,
permission, lifecycle destination, or failure origin.

#### Multipart fields

| Field | Required | Contract |
| --- | --- | --- |
| `document` | Yes | Exactly one binary file part; the server derives bytes and filename |
| `document_type` | Yes | One of `EMAIL_BODY`, `PDF`, `XLSX`, `CSV` |
| `message_id` | No | One nonblank UTF-8 source identifier, at most 256 characters |

The uploaded filename must be nonblank and at most 255 characters after the
backend discards path components. The server derives the source document name
from that filename. The uploaded MIME declaration is read from the transport,
normalized using the existing Phase 3 rules, and validated against the
declared type by `process_document(...)`. The backend computes the SHA-256
from the exact received bytes; a client hash is not accepted.

`FORM` is intentionally not a valid value for this sandbox contract. Phase 3
currently rejects it, so Phase 7 does not pretend to support it.

The request must not contain trusted or authoritative fields, including:

- `customer_reference`, PO number, trusted price, inventory, or any other
  trusted business value;
- approval role, actor, lifecycle destination, failure origin, validation
  result, extraction evidence, or audit content.

### 4.2 Backend-derived values

The orchestration application builds the existing Phase 2 create input with:

- all business fields set to `None` and no client-supplied lines;
- exactly one `SourceDocument` containing the supported type, backend-derived
  filename, transport MIME declaration, backend-derived lowercase SHA-256,
  optional `message_id`, and no storage reference;
- the server-owned orchestration actor for new orchestration audit events;
- the initial `RECEIVED` lifecycle state through `Order.received(...)`.

The later Phase 4 draft and Phase 5 trusted promotion are the only sources for
business fields in the persisted trusted order. The orchestration request
cannot seed trusted order data.

### 4.3 Endpoint response

The successful response is exactly this narrow envelope, subject to the
existing `OrderState` enum:

```json
{
  "order_id": "8a5f2a42-4f7a-4ab4-8ef3-3fc7f8b0d444",
  "state": "READY_FOR_APPROVAL",
  "failure_origin": null,
  "idempotent_replay": false
}
```

Fields are:

| Field | Meaning |
| --- | --- |
| `order_id` | Authoritative persisted order identity |
| `state` | Current authoritative `OrderState` |
| `failure_origin` | Current domain failure origin, only non-null for a failure state |
| `idempotent_replay` | `true` when this command returned an already-created Phase 2 idempotent order rather than creating the order/idempotency record itself; this includes losing a concurrent unique-key insertion race |

The response contains no client-computed route, permission, approval decision,
validation issue set, extraction evidence, token, or retry destination. n8n
branches only on `state`.

`idempotent_replay` is a result of the create authority, not an unsafe
pre-read. M7C must introduce the smallest wrapper or helper around the
existing `create_order(...)` operation needed to distinguish
`CREATED_BY_THIS_COMMAND` from `REPLAYED_EXISTING`. The wrapper must preserve
the Phase 2 fingerprint, unique-key constraint, atomic creation transaction,
and unique-key race resolver.

### 4.4 HTTP semantics

| Situation | Status | Semantics |
| --- | ---: | --- |
| This command created the order and reached its current durable routed or failure result | `201` | `CREATED_BY_THIS_COMMAND`; the body reports `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, `FAILED_RETRYABLE`, or `FAILED_FINAL` |
| An existing same-fingerprint order/result is returned without new execution, or a valid human-authorized retry resume completes and returns its current result | `200` | `REPLAYED_EXISTING`; a successful resumed retry deliberately uses `200` because no new order was created, and its body has `idempotent_replay: true` |
| An existing same-fingerprint order is currently owned by another ordinary execution or claimed retry generation in `PROCESSING` or `EXTRACTED` | `202` | The duplicate stands down and performs no provider work; `202` does not promise that an abandoned claim will later recover |
| Same key with a different fingerprint | `409` | `IDEMPOTENCY_CONFLICT`; no current-request business mutation is accepted |
| Missing/invalid service credential | `401` | `ORCHESTRATION_UNAUTHENTICATED` with a bounded message and `WWW-Authenticate: Bearer` |
| Invalid multipart shape or invalid command field before order creation | `422` | Safe transport-contract error; no order is created |
| Infrastructure is unavailable without this request proving a new durable lifecycle result | `503` | `ORCHESTRATION_UNAVAILABLE`; n8n may apply bounded transport retry, but the response does not say whether a prior claim committed |

The `200` replay body may expose any already-persisted state, including a
failure or a safe in-progress-adjacent state left by an interrupted execution.
That is an observation, not a command to choose a destination. A persisted
`FAILED_RETRYABLE` result is a business response, not an HTTP transport error;
it must not trigger an unbounded n8n loop.

If a `503` occurs before the short `RECEIVED -> PROCESSING` claim commits, a
bounded same-key transport retry may safely repeat the request. If it occurs
after that claim or after a retry-generation claim commits, the same-key
redelivery remains duplicate-safe but may return `202 PROCESSING` or
`202 EXTRACTED` rather than recover the work. HTTP transport retry is never a
claim that lifecycle work will resume.

Error responses never include source content, provider payloads, SQL, stack
traces, credentials, or the idempotency key.

No separate orchestration status endpoint is included in M7A. The command
already returns the authoritative state needed by the sandbox, and adding a
symmetrical read endpoint would not solve the raw-document durability limit.
The existing broad `/v1/orders/{order_id}` read remains a human/development
read surface, not a substitute machine contract.

## 5. Machine authentication

Phase 7 uses a separate development/service credential. It does not reuse
human `REVIEWER`, `APPROVER`, or `ELEVATED_APPROVER` credentials.

The configured secret is conceptually:

```text
OPSFLOW_ORCHESTRATION_TOKEN
```

The future settings field is secret-aware and loaded only from ignored local
environment configuration. The authentication dependency:

1. requires an HTTP Bearer credential;
2. fails closed when the server setting is absent or blank;
3. compares the supplied and configured UTF-8 bytes with
   `hmac.compare_digest`;
4. derives the fixed actor `orchestration:n8n` on success;
5. ignores all caller-provided actor, role, and selector fields.

There is no OAuth/OIDC/JWT framework in Phase 7 and no meaningful machine-role
distinction to invent. The token is never returned, logged, written to an
audit description, or embedded in an exported workflow. Safe auth failures
are deliberately indistinguishable to callers.

## 6. Idempotency and duplicate-trigger contract

### 6.1 Reuse Phase 2 authority

The orchestration boundary reuses the existing
`order_creation_idempotency` table and `create_order(...)` operation. It does
not add a second generic idempotency table, event bus, workflow job table, or
distributed-lock framework.

The n8n Webhook's stable `X-OpsFlow-Event-Id` value is forwarded unchanged as
the OpsFlow `Idempotency-Key`. A retry never generates a new random key.

For this boundary, the existing Phase 2 request fingerprint is computed from
the canonical server-composed `CreateOrderInput` containing only:

```text
customer_reference = None
po_number = None
order_date = None
requested_delivery_date = None
currency = None
lines = ()
source_documents = (
    document_type,
    canonical basename,
    normalized transport MIME,
    backend SHA-256,
    message_id,
    storage_reference = None,
    metadata = (),
)
```

The existing deterministic JSON serialization and SHA-256 fingerprinting are
the authority. The raw bytes are represented only by the backend-derived SHA;
the key, document type, filename, MIME, and optional message ID are relevant
canonical request metadata. The idempotency key itself is the lookup key and is
not added into its own fingerprint.

The future M7C intake service must consume the `CREATED_BY_THIS_COMMAND` or
`REPLAYED_EXISTING` result from the wrapper described above. It must not issue
an unsafe pre-read to infer whether the order existed. The Phase 2 unique-key
insert and its committed-row race resolver remain the only source of that
distinction.

### 6.2 Claim and recheck protocol

The protocol distinguishes an ordinary initial claim from a human-authorized
retry claim. The audit generation is ordered by the existing audit index's
`(occurred_at ASC, id ASC)` order. For one order, a retry generation is the
latest `ORDER_RETRY_RESTORED` event that has no later
`ORDER_PROCESSING_RESUMED` or `ORDER_EXTRACTION_RESUMED` event. The resume
event is the durable consumed marker; no retry counter or separate attempt
table is introduced.

For every request, the service performs this sequence:

1. Create or replay the Phase 2 order through its existing short transaction.
   The same stable key and canonical fingerprint are required. A different
   binary, filename, MIME, type, or message ID is a `409` and cannot reach a
   resume claim.
2. Open a separate short transaction and lock only the order row with the
   existing `get_order_for_update(...)` pattern.
3. Under that lock, recheck the persisted source-document record against the
   supplied document's backend-derived SHA-256 and type. The persisted source
   document identity is the source-document record selected from this order;
   the canonical fingerprint additionally binds its name, MIME, and message
   ID. Any mismatch stands down with conflict and does not consume a retry
   generation.
4. If the locked state is `RECEIVED`, apply the legal
   `RECEIVED -> PROCESSING` transition, write `ORDER_PROCESSING_STARTED`, and
   commit immediately. This is an ordinary initial claim, whether the request
   created the order or is safely retrying a pre-claim transport failure.
5. If the locked state is `PROCESSING` and the latest relevant claim is the
   ordinary `ORDER_PROCESSING_STARTED` generation, with no unconsumed human
   retry restore, return `202 PROCESSING`. This is an active/ordinary claim:
   the duplicate performs no parsing, extraction, or provider call.
6. If the locked state is `PROCESSING` and the latest relevant generation is
   an unconsumed `ORDER_RETRY_RESTORED`, write
   `ORDER_PROCESSING_RESUMED`, commit, and make this request the sole owner of
   that restored processing execution.
7. If the locked state is `EXTRACTED` and the latest relevant generation is
   an unconsumed `ORDER_RETRY_RESTORED`, write `ORDER_EXTRACTION_RESUMED` and
   commit. The order remains `EXTRACTED` because the existing state machine
   has no `EXTRACTED -> PROCESSING` transition; the event protects this one
   recovery execution before it calls parsing or extraction.
8. If a matching retry restore already has a later resume event, or if the
   current state is `EXTRACTED` from an ordinary execution, return the current
   `202` in-progress state and perform no provider work. A restored
   `SYNCING` order is also returned without Phase 7 resume handling.
9. If the state is a completed or business-routed result, or a persisted
   failure that has not been human-restored, return its current result without
   provider work.
10. Run all parsing, extraction, trusted-provider, and validation work only
    after the claim transaction has committed.

The first valid resumer therefore writes its narrow resume event under the
short order lock and commits before any provider call. A concurrent second
redelivery sees that event as the consumed marker and stands down. The lock is
never held while parsing or waiting for Gemini, a provider, or any network
operation.

`ORDER_RETRY_RESTORED` is written only by the existing reviewer-authorized
Phase 6 `Order.retry()` command. n8n cannot create it and cannot call
`Order.retry()` itself. The Phase 7 resume contract begins only after that
human command and only for a redelivery carrying the same original source
bytes.

For a restored `PROCESSING` generation, the resumer reruns Phase 3 and Phase 4
from the supplied bytes, persists the legal `PROCESSING -> EXTRACTED`
transition, and calls Phase 5 `validate_order(...)`. For a restored
`EXTRACTED` generation, it reruns Phase 3 and Phase 4 from the supplied bytes
while the order remains `EXTRACTED`, verifies the reconstructed draft's source
identity, and calls the existing `validate_order(...)`. This does not claim an
in-memory `ExtractionDraft` was persisted: a successful Phase 5 snapshot may
not exist because the trusted-data/provider failure can occur before Phase 5's
final snapshot transaction commits.

The required invariants are:

- same key, same canonical fingerprint, and same source identity return the
  same order identity;
- ordinary `PROCESSING` redelivery never issues a second provider call;
- only one valid redelivery can consume one human retry generation;
- retry restoration for `PROCESSING` or `EXTRACTED` never bypasses reviewer
  authorization;
- no duplicate source order, extraction snapshot, trusted promotion, or
  business execution is created by an ordinary replay;
- the unique Phase 2 idempotency key and the locked audit-generation check
  remain the concurrency authorities.

## 7. Backend pipeline composition

The future orchestration application service composes existing subsystems;
it does not reimplement their semantics:

| Step | Operation | Transaction/provider boundary |
| ---: | --- | --- |
| 1 | Read the one uploaded binary, derive filename/MIME/SHA, and build the server-owned source envelope | No business transaction; deterministic local work |
| 2 | Call Phase 2 `create_order(...)` or resolve its replay | Short existing creation transaction |
| 3 | Claim ordinary intake or one human-restored resume generation | Separate short locked transaction; commit the ordinary or narrow resume event before any provider call |
| 4 | Call Phase 3 `process_document(...)` for the original, processing-restored, or extracted-restored execution | Outside a database transaction; the exact redelivered bytes are required |
| 5 | Call Phase 4 `OrderExtractor.extract(...)` | Outside a database transaction; provider errors are classified by the orchestration service |
| 6 | Persist `PROCESSING -> EXTRACTED` only for an execution that owns `PROCESSING` | Short locked transaction; an extracted-restored execution remains `EXTRACTED` and writes no second lifecycle transition here |
| 7 | Call existing Phase 5 `validate_order(...)` | Trusted provider and pure engine execute outside the final write transaction; existing service owns its final lock/recheck/write boundary and creates the first successful immutable snapshot |
| 8 | Return the committed current state | Response is derived from the committed order; a successful human-authorized resume uses `200` |

`validate_order(...)` remains the validation authority. It persists the
immutable extraction snapshot, validation issues, trusted promotion when
appropriate, legal `VALIDATED` transition, final route, and its existing
Phase 5 audit events. The orchestration service does not create a second
snapshot or second `ORDER_VALIDATED`, `ORDER_NEEDS_REVIEW`, or
`ORDER_READY_FOR_APPROVAL` event.

An `EXTRACTED`-origin recovery deliberately reconstructs an untrusted
`ExtractionDraft` in memory and then invokes the existing Phase 5 service. It
does not add draft persistence or a second snapshot path. If the prior
trusted-data/provider failure occurred before Phase 5's final transaction,
there is no successful snapshot to reuse; the normal Phase 5 final transaction
records the reconstructed draft only after validation succeeds.

The existing Phase 1 `OrderState` set remains unchanged. Phase 7 does not add
`ORCHESTRATING`, `WAITING_FOR_N8N`, `AI_PROCESSING`, `WORKFLOW_FAILED`, or any
other lifecycle value.

### Orchestration audit events

New orchestration-owned events are narrow and non-sensitive:

| Event type | When | Actor | Fixed description |
| --- | --- | --- | --- |
| `ORDER_PROCESSING_STARTED` | The short claim commits `RECEIVED -> PROCESSING` | `orchestration:n8n` | `Orchestration intake claimed the order for processing.` |
| `ORDER_PROCESSING_RESUMED` | A locked, unconsumed human retry generation restores a `PROCESSING` execution and commits before parsing/provider work | `orchestration:n8n` | `Human-authorized processing retry redelivery claimed for execution.` |
| `ORDER_EXTRACTION_RESUMED` | A locked, unconsumed human retry generation restores an `EXTRACTED` execution and commits before parsing/provider work | `orchestration:n8n` | `Human-authorized extraction retry redelivery claimed for execution.` |
| `ORDER_EXTRACTION_COMPLETED` | Document processing and extraction complete and `PROCESSING -> EXTRACTED` commits | `orchestration:n8n` | `Document processing and structured extraction completed; validation is pending.` |
| `ORDER_PROCESSING_FAILED` | A processing-origin operational failure is persisted | `orchestration:n8n` | `Orchestration processing stopped with a persisted operational failure.` |
| `ORDER_VALIDATION_FAILED` | An extracted-origin operational failure is persisted | `orchestration:n8n` | `Deterministic validation could not complete; a persisted operational failure was recorded.` |

The existing Phase 2 `ORDER_RECEIVED` event remains governed by the Phase 2
creation contract. Failure descriptions contain no raw source, provider text,
secret, customer payload, or caller-controlled role. The `failure_origin`
column remains the domain source of truth.

## 8. Transaction and provider boundaries

The pipeline is not one SQL transaction. In particular:

- document parsing does not require a database transaction;
- an ordinary claim or human-retry resume claim commits before parsing or
  provider work, and its order lock is never held across that work;
- Gemini or another extraction provider is called only after any mutation
  transaction has committed;
- trusted business-data lookup remains outside the final Phase 5 write
  transaction;
- the Phase 5 final write uses its existing lock, local-fact recheck, snapshot,
  issue, promotion, state, and audit atomicity;
- if a final write fails, its transaction rolls back as one unit and no partial
  trusted business graph is accepted;
- if persistence is unavailable before a failure state can be committed, the
  API returns a safe `503` and does not claim that a failure was durably
  recorded.

The implementation must prove provider calls observe
`session.in_transaction() is False` at the provider boundary. A lock or
transaction may protect a short claim or final commit, never a network wait.

## 9. Failure classification and lifecycle matrix

The API distinguishes a **business validation result** from an
**operational failure**.

| Condition | Classification | Persisted state | `failure_origin` | Retry decision |
| --- | --- | --- | --- | --- |
| Unsupported `FORM`/unknown transport type | Request contract error | No order before transport rejection | None | No automatic retry; correct the request |
| Valid command with MIME/type mismatch | Processing failure | `FAILED_FINAL` | `PROCESSING` | Deterministic input mismatch; do not repeat blindly |
| Corrupt PDF, unreadable PDF, invalid UTF-8, malformed CSV, corrupt XLSX | Processing failure | `FAILED_FINAL` | `PROCESSING` | Source bytes are not processable under the current contract |
| Document input, page, sheet, row, cell, archive, table, or canonical-text limit | Processing failure | `FAILED_FINAL` | `PROCESSING` | Bound exceeded; no infinite repeat |
| Extraction provider timeout | Operational failure | `FAILED_RETRYABLE` | `PROCESSING` | Transient provider/transport condition |
| Extraction provider unavailable | Operational failure | `FAILED_RETRYABLE` | `PROCESSING` | Transient provider/transport condition |
| Malformed provider response, unsafe schema, invalid date/decimal, or ungrounded evidence | Processing failure | `FAILED_FINAL` | `PROCESSING` | Provider contract or source-grounding defect, not a blind retry |
| Trusted business-data provider unavailable | Operational failure | `FAILED_RETRYABLE` | `EXTRACTED` | Transient reference-data condition |
| Invalid trusted provider contract | Operational failure | `FAILED_FINAL` | `EXTRACTED` | Provider contract violation must be corrected |
| Validation-fact/concurrency conflict | Operational failure | `FAILED_RETRYABLE` | `EXTRACTED` | Re-evaluation may be safe after the current conflict is resolved |
| Unknown SKU, inactive customer/product, unacceptable price, unavailable quantity, missing required business value, duplicate PO, or other Phase 5 rule issue | Business validation result | `NEEDS_REVIEW` | None | Human correction/review; not a system retry |
| Clean deterministic validation | Business validation result | `READY_FOR_APPROVAL` | None | Human approval is required |
| Database or final persistence failure before a durable outcome | Transport/application failure | No new claimed result is asserted | None | Return `503`; n8n may retry the same key a bounded number of times |

`FAILED_RETRYABLE` and `FAILED_FINAL` are selected by backend exception class
and lifecycle position, never by an n8n expression or client field. A business
rule violation is never converted into `FAILED_*` merely because it is an
exception case. M7C must preserve typed distinction between transient provider
availability/timeout errors and provider-response or grounding errors; it must
not classify by matching human-readable exception messages. The existing
`ProviderError` family is the Phase 4 boundary, so any adapter-specific
availability distinction needed for a retryable result must be made at that
provider boundary before the orchestration service maps failures. Unknown or
untyped provider errors fail closed as `FAILED_FINAL`.

For a `FAILED_RETRYABLE` processing-origin result, the reviewer must first
authorize `Order.retry()` and restore `PROCESSING`; a subsequent matching
same-document redelivery may consume one `ORDER_RETRY_RESTORED` generation and
rerun Phases 3–5. For an extracted-origin result, the same sequence restores
`EXTRACTED` and reconstructs the in-memory draft before calling Phase 5 again.
Neither route is a machine-selected failure destination.

## 10. Raw-document durability and retry boundary

Phase 3 and the current persistence model store source metadata and identity,
not durable raw-document object storage. Phase 7 therefore does not introduce
S3, MinIO, a blob volume, or a new raw-document table.

The precise Phase 7 posture is:

- raw bytes exist only for the current intake execution; no raw-document
  storage or durable `ExtractionDraft` is added;
- a retry redelivery must supply the identical original binary, stable event
  ID, document identity, SHA-256, and type;
- `FAILED_RETRYABLE` remains a real persisted lifecycle state;
- n8n and the caller may not choose or rewrite `failure_origin`;
- `Order.retry()` remains authoritative for clearing a retryable failure to its
  recorded origin, and n8n must never call it;
- the two owned recovery forms are
  `FAILED_RETRYABLE(failure_origin=PROCESSING) -> PROCESSING` and
  `FAILED_RETRYABLE(failure_origin=EXTRACTED) -> EXTRACTED`, both produced by
  the reviewer-authorized Phase 6 command before any Phase 7 redelivery;
- a persisted `FAILED_RETRYABLE` response is routed visibly to the
  retryable/review branch, not fed into an automatic infinite intake loop;
- the sandbox recovery flow is exactly:
  `provider/reference failure -> FAILED_RETRYABLE -> visible n8n
  retryable/review branch -> reviewer requests Retry in the existing review
  UI -> backend restores PROCESSING or EXTRACTED -> sandbox caller
  redelivers the same original document and stable event ID -> the locked
  intake consumes the unconsumed retry-restored generation -> exactly one
  resume execution`;
- the browser Retry click alone does not contain the raw bytes. The subsequent
  same-document redelivery is required. No polling and no long-running n8n
  workflow is required; a future Gmail or automation integration may provide
  the redelivery mechanism, while M7A uses explicit synthetic resubmission;
- an `EXTRACTED` retry is allowed to rerun Phase 3 parsing and Phase 4
  extraction because no successful Phase 5 validation snapshot may have been
  committed. The prior in-memory draft is not treated as durable;
- a restored `SYNCING` case is outside Phase 7 because Phase 7 implements no
  external synchronization;
- Phase 7 does not automatically reclaim an ordinary initial `PROCESSING`
  claim. If `RECEIVED -> PROCESSING` committed and the process, server, or
  database failed before a result or failure could commit, a same-key
  redelivery observes `PROCESSING`, returns it visibly, and does not start a
  second provider execution. That order may remain abandoned;
- the same no-lease limitation applies if a human-retry resume claim commits
  and its executor dies before a result or failure commits: the generation is
  consumed, and a later redelivery stands down rather than executing it twice;
- there is no lease, heartbeat, or attempt table that can prove the first
  executor is dead. Stale-claim leasing, heartbeat, and automatic recovery
  belong to Phase 10;
- pre-claim transport failure is safely repeatable with bounded n8n transport
  retry. A post-claim ambiguous failure remains duplicate-safe but may return
  `PROCESSING` or `EXTRACTED`; transport retry does not falsely claim that it
  recovered the work.

This bounded recovery is intentionally limited to a reviewer-authorized
`PROCESSING` or `EXTRACTED` restore followed by explicit same-document
redelivery. It does not create an unowned storage system or silently rerun AI
with different input.

## 11. n8n sandbox trigger contract

The Phase 7 trigger is synthetic and independent of Gmail:

- n8n uses a Webhook trigger;
- the incoming caller supplies one stable `X-OpsFlow-Event-Id` header;
- the header is required, nonblank, and is forwarded unchanged as
  `Idempotency-Key`;
- the webhook carries one binary `document`, `document_type`, and optional
  `message_id` field;
- retries preserve the original event ID and document;
- n8n does not generate a new UUID on retry;
- no Gmail polling, message search, attachment policy, mailbox credential, or
  email behavior is implemented in Phase 7.

The sandbox recovery interaction is explicit synthetic resubmission, not a
polling loop: the original provider or reference-data failure is returned on a
visible retryable/review branch; a reviewer clicks Retry in the existing review
UI; the backend restores `PROCESSING` or `EXTRACTED`; and the sandbox caller
then submits the same original document with the same stable event ID. The
browser action cannot carry the original raw bytes by itself, so the second
submission is required. The intake consumes the restored generation exactly
once or returns the already-current state to a concurrent duplicate.

## 12. n8n workflow topology and routing

The exported workflow is intentionally small:

```text
Webhook
  -> minimal transport field preparation, only if n8n requires it
  -> HTTP Request: POST http://api:8000/v1/orchestration/intakes
  -> Switch on backend response.state
  -> Respond to Webhook branch
```

The HTTP Request node:

- sends the binary as multipart form-data under `document`;
- forwards `document_type` and optional `message_id`;
- forwards the exact `X-OpsFlow-Event-Id` value as `Idempotency-Key`;
- uses an n8n credential for the OpsFlow Bearer token;
- targets the Compose service URL `http://api:8000`, never host-only
  `localhost` from inside the n8n container;
- uses bounded transport retries only for connection failures and selected
  `5xx` responses, with a maximum of two retry attempts and no retry for
  authentication, validation, or idempotency conflicts.

The Switch may compare only the server-returned `state` value. Conceptual
branches are:

- `NEEDS_REVIEW` → safe review-needed response;
- `READY_FOR_APPROVAL` → safe human-approval-needed response;
- `FAILED_RETRYABLE` → visible retryable-failure/review response; n8n does not
  call `Order.retry()` or choose a failure origin;
- `FAILED_FINAL` → safe final-failure response;
- `PROCESSING` and any other existing/in-progress/default state → safe
  current-state response without selecting a lifecycle destination.

The `FAILED_RETRYABLE` branch is a visible handoff to the existing human
review flow. n8n transport retries are separate from lifecycle retry and do not
wait for, poll for, or manufacture a reviewer authorization. A later explicit
same-document webhook submission is the only Phase 7 sandbox resume trigger.

The Switch contains no business-rule expressions. There is no Code node unless
a concrete n8n transport limitation is proven during M7D. JavaScript is not
allowed to hash files, parse documents, inspect prices, validate products,
calculate approval, generate lifecycle destinations, or call an AI provider.
There is no AI Agent node and no direct Gemini node.

`READY_FOR_APPROVAL` means that a human approval is required. n8n does not
approve it, call a review command as a machine, or start `APPROVED -> SYNCING`.
`NEEDS_REVIEW` means that a human must correct or review it. No Phase 7 branch
mutates ERP, CRM, email, Slack, or any other external system.

## 13. n8n runtime and Compose boundary

Phase 7 selects self-hosted n8n Community Edition with one instance. As of
2026-09-22, the stable version selected for implementation is:

```text
n8nio/n8n:2.39.10
```

The design never uses `latest`. `2.40.5` is pre-release on the design date;
M7D must re-verify the stable release immediately before runtime work and may
change the pin only after recording that decision.

The intended local runtime is deliberately portfolio-sized:

- one n8n service in Docker Compose;
- one named n8n data volume;
- no Redis, queue workers, Kubernetes, cloud deployment, or n8n Enterprise;
- no separate n8n PostgreSQL requirement;
- no API dependency on n8n for startup or business correctness;
- no unnecessary mutual service dependency.

M7D will extend the current `docker-compose.yml`; M7A makes no Compose edit.
n8n will reach the API through the Compose network at `http://api:8000`. Local
browser access is intended at `http://localhost:5678`, but this design does
not claim that URL is verified before M7D.

n8n credentials stay in n8n. The n8n encryption key and local configuration
secrets stay in ignored environment configuration. No workflow export contains
a bearer token, Gemini key, encryption key, real client data, or raw document.

## 14. Version-controlled workflow exports

M7D is expected to create, but M7A deliberately does not create:

```text
workflows/n8n/opsflow-sandbox-intake.json
workflows/n8n/README.md
```

Sanitized exports may contain workflow topology, node configuration, and safe
credential-reference metadata when necessary. They must not contain actual
credentials, API tokens, Gemini keys, n8n encryption keys, private business
data, raw documents, execution history, or real customer identifiers.

A clean-clone import procedure will be:

1. start the pinned local n8n service with ignored local secrets configured;
2. import the sanitized JSON through the n8n UI or the documented local import
   command;
3. create or select the local OpsFlow Bearer credential in n8n;
4. relink that credential to the HTTP Request node without editing any secret
   into the JSON;
5. set the local Webhook URL and run only synthetic fixtures.

## 15. Testing and verification design for later implementation

M7A creates no application tests. This section freezes the tests that M7B–M7E
must add; it is not evidence that those tests already exist.

### Backend unit and integration coverage

The future backend suite must cover missing, wrong, and valid service
credentials; secret-safe failures; multipart validation; supported and
unsupported types; MIME/type mismatch; malformed documents; size and parser
limits; backend-derived SHA; successful extraction; provider timeout and
availability errors; invalid provider responses and evidence grounding;
`NEEDS_REVIEW` and `READY_FOR_APPROVAL`; failure classification; same-key
replay; same-key conflict; no duplicate snapshot/promotion/audit on replay;
concurrent duplicate claim behavior; provider calls outside transactions;
rejection of client-supplied trusted authority; and legal-only lifecycle
transitions.

The future retry/resume suite must explicitly prove:

- duplicate delivery during ordinary `PROCESSING` does not call the provider
  twice;
- reviewer retry restores `PROCESSING`, and matching same-document redelivery
  resumes exactly once;
- two concurrent redeliveries after one human retry restore result in one
  resume claim and one provider execution;
- reviewer retry restores `EXTRACTED`, and same-document redelivery reruns
  parsing and extraction before revalidating through existing Phase 5
  `validate_order(...)`;
- mismatched binary, source SHA, document type, message ID, MIME, filename, or
  canonical fingerprint cannot consume a retry generation;
- one retry generation cannot be consumed twice, including after a committed
  resume event;
- n8n cannot directly invoke lifecycle retry or select `failure_origin`;
- a restored `SYNCING` order is outside Phase 7 resume handling;
- an abandoned ordinary `PROCESSING` claim remains duplicate-safe and visibly
  unrecovered rather than being automatically reclaimed;
- a post-claim persistence outage is not falsely described as recovered by
  bounded transport retry;
- `idempotent_replay` is false for the command that creates the order and true
  when a concurrent request loses the Phase 2 unique-key insertion race.

PostgreSQL integration must prove the existing Phase 2 uniqueness authority,
short claim transaction, no lock held during provider work, and atomic final
Phase 5 writes. Tests use `FakeProvider` and synthetic trusted-data fixtures;
ordinary CI never calls live Gemini.

### Workflow-contract automated coverage

Once `workflows/n8n/opsflow-sandbox-intake.json` exists, contract tests must
parse it and assert valid JSON; expected Webhook, HTTP Request, Switch, and
Respond to Webhook node types; the exact method and endpoint; multipart binary
forwarding; stable idempotency-header forwarding; a credential reference with
no secret; expected state branches; no prohibited Code/AI/business-logic
nodes; and no embedded private execution data.

### Real local smoke verification

M7D/M7E must manually or integrationally exercise the actual pinned n8n
container and sanitized workflow with synthetic data for:

- normal document → `READY_FOR_APPROVAL`;
- business exception → `NEEDS_REVIEW`;
- duplicate trigger;
- malformed input;
- temporarily unavailable backend;
- bounded transport retry;
- persisted retryable failure;
- persisted final failure.

Playwright/Cypress is not introduced solely to test n8n.

## 16. Cost, security, and data posture

Phase 7 development remains effectively `$0` mandatory cost:

- local PostgreSQL and local n8n Community Edition;
- synthetic documents and business data;
- the existing `FakeProvider` for automated tests and the default sandbox;
- Docker and existing CI;
- optional Gemini only outside ordinary CI and never as a required path.

No credentials, API keys, private customer data, real business documents,
execution history, or secrets may enter the repository. The backend derives
authority, state, fingerprints, and audit actors. n8n is an untrusted transport
and routing boundary for business decisions, not a source of truth.

## 17. Explicit non-goals

Phase 7 excludes:

- Gmail and Slack integrations;
- Odoo and HubSpot integrations;
- production OAuth/OIDC/JWT IAM;
- Redis, n8n queue mode, multiple workers, Kubernetes, and cloud deployment;
- event sourcing and a generic Python workflow engine;
- a generic permissions framework or custom n8n nodes;
- AI Agent nodes and Gemini calls from n8n;
- business validation, policy, approval, or trusted-order mutation in n8n;
- new `OrderState` values;
- S3, MinIO, or raw-document object storage;
- WebSockets and long-running approval polling;
- automatic Phase 8/9 notifications, ERP synchronization, or external side
  effects;
- production observability and broad security hardening belonging to Phase 10;
- an implementation plan, runtime code, tests, dependencies, migrations,
  workflow JSON, credentials, or Compose changes during M7A.

## 18. Phase 7 milestone sequence

| Milestone | Objective | Inputs | Output/contract | Major tests | Non-goals | Exit gate |
| --- | --- | --- | --- | --- | --- | --- |
| M7A — Orchestration Contract & Design | Freeze the thin boundary and authority rules | Phases 0–6 source, code, tests, specs, and audits | This authoritative design candidate plus later separately reviewed implementation plan | Documentation links, status, scope, contradiction, secret, and diff checks | All runtime behavior and the implementation plan in this milestone | Design is independently reviewable; M7A remains in progress until its design and plan are approved |
| M7B — Orchestration Service Authentication & HTTP Contract | Implement the dedicated authenticated request/response boundary | Approved M7A contract | `/v1/orchestration/intakes`, service-token dependency, strict multipart/narrow response, safe errors | Auth matrix, multipart contract, status mapping, no trusted client authority | Pipeline composition, n8n runtime, external integrations | Contract tests pass and no human role credential is reused |
| M7C — Idempotent Intake Pipeline | Compose Phase 2–5 into one backend-owned intake operation | M7B HTTP contract and existing Phase 2–5 services | Claim/recheck protocol, extraction/validation composition, failure/audit mapping | Replay/conflict, concurrent duplicate, provider boundaries, lifecycle legality, failure matrix | Raw storage, delayed resume framework, Phase 8/9 effects | Fake/synthetic end-to-end backend scenarios pass with no duplicate business execution |
| M7D — n8n Runtime & Version-Controlled Sandbox Workflow | Run the pinned local n8n workflow against the API | M7B/M7C contract and approved runtime pin | Compose n8n service, sanitized workflow JSON, workflow README, local credential setup | JSON contract checks and real local container smoke path | Gmail, direct Gemini, queue mode, cloud deployment | Synthetic document travels through Webhook → API → state Switch → response |
| M7E — Cross-Boundary Reliability & Demo Hardening | Make transport failures visible and bounded for the local demo | Working backend and workflow | Bounded HTTP retries, visible error/default branches, sanitized demo fixtures and recovery notes | Unavailable API, duplicate trigger, malformed input, retryable/final result, no infinite loop | Durable delayed resume, Phase 10 production hardening, external SaaS | Local demo scenarios are repeatable and safe under declared limitations |
| M7F — Independent Phase 7 Audit & Closeout | Audit the complete phase before status closure | All M7A–M7E artifacts and verification evidence | Fresh independent audit, remediation if needed, and closeout report | Full scope, security, contract, workflow, Docker, cost, and clean-clone review | New features during audit unless a finding requires focused remediation | Zero unresolved blocking findings; only then can Phase 7 be marked complete |

M7A does not turn this table into a task-by-task implementation plan. The
implementation plan is a later artifact after independent design review.

## 19. Phase 7 definition of done

Phase 7 can be marked `COMPLETE` only when all of the following are true:

- a real local n8n Community workflow receives a synthetic document;
- n8n authenticates to OpsFlow with a separate service credential;
- the stable source event becomes the backend idempotency key;
- OpsFlow owns document processing, extraction, validation, and state;
- the order reaches the correct backend-authoritative state;
- n8n routes only on that state;
- duplicate triggers do not duplicate business execution;
- malformed and unavailable-backend scenarios fail visibly and safely;
- the workflow export is committed and sanitized;
- no future-phase external integration is smuggled in;
- automated backend and workflow tests pass;
- the real Docker/n8n sandbox path is manually or integrationally verified;
- a fresh independent M7F audit passes.

M7A itself is not complete merely because this document is committed. Its
status remains `IN PROGRESS` until the approved design and later approved plan
are both present.

## 20. Design consistency review

This design was reviewed against the existing contracts before the candidate
change:

- **Phase 1:** preserves the exact twelve-state `OrderState` set, legal
  transitions, approval-before-sync invariant, and `Order.retry()` failure
  origin semantics.
- **Phase 2:** reuses `create_order(...)`, the unique idempotency key, the
  canonical fingerprint, atomic initial order/audit creation, and existing
  row-lock repository patterns.
- **Phase 3:** calls `process_document(...)`, preserves backend SHA identity,
  respects document limits and MIME rules, and keeps `FORM` out of the
  sandbox.
- **Phase 4:** calls `OrderExtractor.extract(...)` outside a transaction and
  retains strict provider schema and evidence grounding as Python authority.
- **Phase 5:** calls `validate_order(...)` rather than duplicating trusted data,
  validation, snapshot, promotion, or route logic; business issues remain
  `NEEDS_REVIEW`.
- **Phase 6:** does not reuse human credentials, does not let n8n approve or
  invoke `Order.retry()`, and preserves the reviewer-only retry command. The
  forward-looking Phase 6 statement that later orchestration resumes the
  appropriate work is resolved here only for `PROCESSING` and `EXTRACTED`
  origins after a reviewer restore and explicit redelivery of the same source
  bytes; `SYNCING` remains outside Phase 7.
- **Retry generations:** ordinary initial `PROCESSING` claims are distinct
  from `ORDER_RETRY_RESTORED` generations. A locked resume event consumes one
  human-authorized generation exactly once, without holding a transaction
  during parsing or provider work.
- **Phase 5 timing:** an extracted-origin retry reconstructs an untrusted
  `ExtractionDraft` because the successful immutable snapshot may not exist
  until Phase 5's final transaction commits. No prior in-memory draft is
  treated as durable.
- **Recovery limit:** an ordinary claim that is abandoned after
  `RECEIVED -> PROCESSING` remains duplicate-safe but unrecovered in Phase 7;
  lease/heartbeat recovery belongs to Phase 10.
- **HTTP and idempotency:** `201`, `200`, `202`, `409`, and `503` distinguish
  creation, existing/resumed result, owned in-progress work, fingerprint
  conflict, and ambiguous infrastructure availability. `idempotent_replay`
  comes from the create authority's created-versus-replayed result, including
  a lost unique-key race, not from a pre-read.
- **Phase 7 scope:** makes no M7A production, test, package, migration,
  Compose, workflow, credential, or infrastructure change.

The refined design deliberately records the abandoned-claim limitation and the
absence of durable raw bytes rather than implying automatic recovery. Where the
current implementation does not yet provide an end-to-end entry point, this
document states the future boundary and defers its implementation to the named
M7B–M7E milestone rather than implying that it already exists. M7A remains
`IN PROGRESS`; this consistency review does not approve an implementation plan
or mark the milestone complete.
