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
| `idempotent_replay` | Whether the idempotency record existed before this command began |

The response contains no client-computed route, permission, approval decision,
validation issue set, extraction evidence, token, or retry destination. n8n
branches only on `state`.

### 4.4 HTTP semantics

| Situation | Status | Semantics |
| --- | ---: | --- |
| New key creates and this request owns processing through a persisted result | `201` | One order was created; the body reports `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, `FAILED_RETRYABLE`, or `FAILED_FINAL` |
| Existing key, same fingerprint, terminal/current result already available | `200` | Replay of the persisted order; no processing or business execution repeats |
| Existing key, same fingerprint, another request has claimed `PROCESSING` | `202` | A concurrent duplicate observed the authoritative in-progress state; it does not call extraction |
| Same key with a different fingerprint | `409` | `IDEMPOTENCY_CONFLICT`; no current-request business mutation is accepted |
| Missing/invalid service credential | `401` | `ORCHESTRATION_UNAUTHENTICATED` with a bounded message and `WWW-Authenticate: Bearer` |
| Invalid multipart shape or invalid command field before order creation | `422` | Safe transport-contract error; no order is created |
| Persistence or application availability failure before a durable outcome | `503` | `ORCHESTRATION_UNAVAILABLE`; n8n may apply its bounded transport retry policy |

The `200` replay body may expose any already-persisted state, including a
failure or a safe in-progress-adjacent state left by an interrupted execution.
That is an observation, not a command to choose a destination. A persisted
`FAILED_RETRYABLE` result is a business response, not an HTTP transport error;
it must not trigger an unbounded n8n loop.

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

### 6.2 Claim and recheck protocol

The smallest compatible concurrency protocol is:

1. Create or replay the Phase 2 `RECEIVED` order through its existing short
   transaction.
2. Open a separate short transaction and lock only the order row with the
   existing `get_order_for_update(...)` pattern.
3. If the locked state is `RECEIVED`, apply the legal
   `RECEIVED -> PROCESSING` transition, write the processing-start audit event,
   and commit immediately.
4. If the locked state is already `PROCESSING`, return the current state to
   this duplicate and perform no provider call.
5. If the locked state is a completed/business-routed state or a persisted
   failure, return its current state and perform no provider call.
6. Run all parsing, extraction, and trusted-provider work after the claim
   transaction has committed.

The row lock is never held while parsing or waiting for Gemini, a provider, or
any network operation. Exactly one concurrent duplicate can claim
`RECEIVED`; the others observe `PROCESSING` after the first claim commits.

The required invariants are:

- same key plus same request returns the same order identity;
- no duplicate source order, extraction snapshot, trusted promotion, or
  business execution is created by replay;
- same key plus a different binary, filename, type, MIME, or message ID is a
  bounded `409 IDEMPOTENCY_CONFLICT`;
- a concurrent duplicate never issues a second AI extraction call;
- the unique Phase 2 idempotency key remains the database concurrency
  authority.

## 7. Backend pipeline composition

The future orchestration application service composes existing subsystems;
it does not reimplement their semantics:

| Step | Operation | Transaction/provider boundary |
| ---: | --- | --- |
| 1 | Read the one uploaded binary, derive filename/MIME/SHA, and build the server-owned source envelope | No business transaction; deterministic local work |
| 2 | Call Phase 2 `create_order(...)` or resolve its replay | Short existing creation transaction |
| 3 | Claim `RECEIVED -> PROCESSING` | Separate short locked transaction; commit before any provider call |
| 4 | Call Phase 3 `process_document(...)` | Outside a database transaction |
| 5 | Call Phase 4 `OrderExtractor.extract(...)` | Outside a database transaction; provider errors are classified by the orchestration service |
| 6 | Persist `PROCESSING -> EXTRACTED` | Short locked transaction; no snapshot or Phase 5 route event is duplicated |
| 7 | Call existing Phase 5 `validate_order(...)` | Trusted provider and pure engine execute outside the final write transaction; existing service owns its final lock/recheck/write boundary |
| 8 | Return the persisted `NEEDS_REVIEW` or `READY_FOR_APPROVAL` state | Response is derived from the committed order |

`validate_order(...)` remains the validation authority. It persists the
immutable extraction snapshot, validation issues, trusted promotion when
appropriate, legal `VALIDATED` transition, final route, and its existing
Phase 5 audit events. The orchestration service does not create a second
snapshot or second `ORDER_VALIDATED`, `ORDER_NEEDS_REVIEW`, or
`ORDER_READY_FOR_APPROVAL` event.

The existing Phase 1 `OrderState` set remains unchanged. Phase 7 does not add
`ORCHESTRATING`, `WAITING_FOR_N8N`, `AI_PROCESSING`, `WORKFLOW_FAILED`, or any
other lifecycle value.

### Orchestration audit events

New orchestration-owned events are narrow and non-sensitive:

| Event type | When | Actor | Fixed description |
| --- | --- | --- | --- |
| `ORDER_PROCESSING_STARTED` | The short claim commits `RECEIVED -> PROCESSING` | `orchestration:n8n` | `Orchestration intake claimed the order for processing.` |
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

## 10. Raw-document durability and retry boundary

Phase 3 and the current persistence model store source metadata and identity,
not durable raw-document object storage. Phase 7 therefore does not introduce
S3, MinIO, a blob volume, or a new raw-document table.

The precise Phase 7 posture is:

- raw bytes exist only for the current intake execution;
- safe HTTP redelivery may resend the same binary under the same stable
  idempotency key;
- `FAILED_RETRYABLE` remains a real persisted lifecycle state;
- n8n and the caller may not choose or rewrite `failure_origin`;
- `Order.retry()` remains authoritative for clearing a retryable failure to
  its recorded origin;
- a persisted `FAILED_RETRYABLE` response is routed visibly to the review/
  recovery branch, not fed into an automatic infinite intake loop;
- Phase 7 does not claim that an arbitrary delayed/manual retry can resume the
  exact pipeline once request bytes or an in-memory extraction draft are gone;
- Phase 6's human retry command still records the operator request and restores
  the domain's recorded origin, but M7A does not add a durable resume command
  or pretend that the current raw-metadata model can supply one;
- production-style delayed resume, durable source retention, leases/stale
  processing recovery, and broader recovery hardening remain later reliability
  work, primarily Phase 10.

This explicit limitation is preferable to creating an unowned storage system or
silently rerunning AI with different input.

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
- `FAILED_RETRYABLE` → safe retryable-failure/review response;
- `FAILED_FINAL` → safe final-failure response;
- `PROCESSING` and any other existing/in-progress/default state → safe
  current-state response without selecting a lifecycle destination.

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
M7D may change the pin only after re-verifying a newer stable release and
recording the decision.

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
- **Phase 6:** does not reuse human credentials, does not let n8n approve,
  and does not claim that the current raw-metadata model supports arbitrary
  delayed resume.
- **Phase 7 scope:** makes no M7A production, test, package, migration,
  Compose, workflow, credential, or infrastructure change.

There are no unresolved design gaps in this candidate. Where the
current implementation does not yet provide an end-to-end entry point, this
document states the future boundary and defers its implementation to the
named M7B–M7E milestone rather than implying that it already exists.
