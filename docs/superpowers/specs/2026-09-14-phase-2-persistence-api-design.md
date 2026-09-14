# Phase 2 — Persistence & Core API Design

## Status and authority

- Repository: `Joseph-Nawar/OpsFlow_AI`
- Phase: **Phase 2 — Persistence & Core API**
- Current milestone: **M2C — Repository & Durable Reads — COMPLETE**
- Design status: independently accepted authoritative Phase 2 design; M2A–M2C are complete, and M2D–M2F are not started
- Baseline: `4e3613b935edabead28d7cc44ea53619f059eeff`
- Phase 1 contract: [Phase 1 Domain Model & State Machine Contract](../../architecture/domain-model.md)

This document is the approved architecture and implementation boundary for
Phase 2. Its companion [implementation plan](../plans/2026-09-14-phase-2-persistence-api.md)
records the execution sequence for the first durable vertical slice:

~~~text
HTTP → application orchestration → Phase 1 domain → PostgreSQL persistence
~~~

The Phase 1 domain remains the business authority. Persistence and HTTP adapt
around that domain. This document authorizes the later M2B–M2E implementation
milestones; it does not claim that their implementation or any Phase 2 runtime
behavior is complete. M2A is **COMPLETE** because the design was independently
accepted and the companion implementation plan was completed and self-reviewed.
M2B is **COMPLETE** because its schema, migration, constraints, and explicit
domain/persistence mapping passed local static/unit verification and exact-head
PostgreSQL CI; M2C is complete and M2D–M2F remain not started.

## 1. Governing sources and repository baseline

Phase 2 must be implemented against these sources of truth, in this order:

1. The active Phase 2 brief and this approved design.
2. [The project roadmap](../../roadmap/project-roadmap.md).
3. [The system overview](../../architecture/system-overview.md).
4. [The Phase 1 domain contract](../../architecture/domain-model.md).
5. [The development guide](../../development/development-guide.md).
6. Existing code, tests, and committed configuration for behavior already implemented.

The implementation uses the existing Python 3.12, FastAPI, Pydantic v2,
SQLAlchemy 2.x, asyncpg, Alembic, pytest, Ruff, mypy, HTTPX, and uv setup. No
new runtime dependency is expected. `pytest-asyncio` or another async test
runtime is not added merely for style.

The verified starting repository state for this design is:

- default branch: `main`;
- local `main` and `origin/main`:
  `4e3613b935edabead28d7cc44ea53619f059eeff`;
- Phase 1 is merged and independently audited;
- Alembic head is `0001_baseline`;
- the application has the existing async engine, `/health`, and `/ready` only;
- the existing tests are standard pytest tests, with `asyncio.run` and HTTPX
  patterns for asynchronous application checks;
- no Phase 2 branch existed before M2A branch creation;
- no Phase 2 production source, migration, API, persistence, or test behavior
  exists at the baseline.

This phase is documentation-first. The current M2A change set may modify only
the Phase 2 design and canonical status documentation. It must not introduce
ORM models, migrations, repositories, routes, API schemas, application
services, idempotency logic, or tests.

## 2. Phase 2 purpose and responsibility boundary

### 2.1 Purpose

Phase 2 introduces the first durable business slice. It safely persists orders
and exposes the first meaningful order API while keeping the existing Phase 1
domain independent from infrastructure.

POST /v1/orders is intake only. It creates a durable
OrderState.RECEIVED snapshot and its initial audit event. It does not start
document processing, AI extraction, validation, approval, synchronization, or
any other later workflow.

### 2.2 Phase 2 owns

- PostgreSQL persistence for Phase 1 domain information;
- SQLAlchemy ORM persistence models;
- Alembic schema evolution;
- explicit domain-to-persistence and persistence-to-domain mapping;
- the first core order application use cases;
- the first /v1/orders HTTP API;
- order-creation idempotency;
- atomic initial audit persistence;
- durable create, read, list, and audit behavior;
- request-scoped SQLAlchemy sessions;
- transaction rollback guarantees;
- real PostgreSQL integration tests.

### 2.3 Phase 2 does not own

- document upload, parsing, PDF/XLSX/CSV extraction, or OCR;
- LLM calls, AI extraction, or prompt handling;
- deterministic business validation rules;
- supported-currency business policy or price tolerance;
- customer, product, inventory, or catalogue lookup;
- review UI;
- approval/rejection endpoints or general state-transition endpoints;
- n8n, Gmail, Slack, ERP, or CRM integrations;
- authentication;
- background workers, Redis, queues, or event buses;
- generalized retry infrastructure;
- request IDs, tracing taxonomy, or mature Phase 12 error infrastructure.

Phase 2 may persist already-known source-document metadata and already-created
validation-issue records, but it does not create business validation rules or
persist raw document bodies and attachments.

## 3. Architectural approach

### 3.1 Thin dependency flow

The approved dependency flow is:

~~~text
API → application → domain + persistence
~~~

The API owns transport concerns and HTTP translation. The application layer
owns orchestration and transaction behavior. The Phase 1 domain owns the
business aggregate and structural/lifecycle invariants. Persistence owns
SQLAlchemy models, database access, and explicit mapping.

Persistence may map to and from domain records. The domain must remain
infrastructure-independent and must know nothing about FastAPI, Pydantic,
SQLAlchemy, PostgreSQL, Alembic, HTTP, or idempotency storage.

### 3.2 Deliberately excluded abstractions

Phase 2 will not introduce abstract repository interfaces merely for
abstraction, generic repository base classes, a Unit of Work framework, CQRS,
a mediator, command bus, service container, DDD framework, state-machine
framework, event bus, dependency-injection library, microservices, or
generalized retry/locking infrastructure.

The implementation must use the smallest explicit architecture that supports
the four endpoints, durable aggregate reconstruction, idempotent creation,
and real PostgreSQL verification.

### 3.3 Target package shape

The responsibility map is:

~~~text
src/opsflow/
├── domain/                 # Phase 1; unchanged unless a real contract defect is found
├── persistence/
│   ├── models.py           # SQLAlchemy tables and metadata
│   ├── mappers.py          # Explicit domain/persistence conversion
│   └── repositories.py     # Concrete persistence operations only
├── application/
│   ├── errors.py           # Small HTTP-independent application errors
│   └── orders.py           # Thin order use-case orchestration
├── api/
│   ├── schemas.py          # Pydantic v2 transport contracts
│   └── orders.py           # Four business routes and HTTP translation
├── database.py             # Existing engine plus session factory support
└── main.py                 # Existing app/lifespan plus router/session wiring
~~~

This is a responsibility map, not a requirement to create every file. If a
smaller file arrangement cleanly satisfies the responsibilities, fewer files
are preferred. No empty future-phase package is permitted.

## 4. Phase 1 domain boundary

The Phase 1 domain is the authority and should remain unchanged. It contains
the immutable, frozen, slotted Order, OrderLine, SourceDocument,
ValidationIssue, and AuditEvent records, the OrderState enum, and the explicit
lifecycle operations.

### 4.1 Order creation contract

The application creates new orders through Order.received(...). This always
produces:

- state=OrderState.RECEIVED;
- failure_origin=None;
- an empty tuple for omitted lines;
- an empty tuple for omitted source documents.

The domain permits a valid pre-extraction RECEIVED order with absent optional
customer reference, PO number, dates, currency, and lines. Phase 2 must not
add business requirements that Phase 1 intentionally leaves for extraction or
later validation.

### 4.2 Exact domain fields persisted for orders

The orders row must represent these exact Phase 1 business/lifecycle fields:

- id;
- customer_reference;
- po_number;
- order_date;
- requested_delivery_date;
- currency;
- lines through order_lines;
- source_documents through source_documents;
- state;
- failure_origin.

The database also stores created_at as persistence/API metadata. created_at
must not be added to the Order domain dataclass.

The implementation must not add updated_at, deleted_at, soft deletion,
optimistic versioning, tenant_id, owner_id, external references, or other
speculative order fields.

### 4.3 State persistence and invariant

Lifecycle values are stored as strings with explicit database checks. No
PostgreSQL custom ENUM type is approved; string checks preserve migration
simplicity and provide database defense-in-depth.

The exact allowed state strings are `RECEIVED`, `PROCESSING`, `EXTRACTED`,
`VALIDATED`, `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, `APPROVED`, `SYNCING`,
`COMPLETED`, `REJECTED`, `FAILED_RETRYABLE`, and `FAILED_FINAL`. The exact
allowed failure-origin strings are `PROCESSING`, `EXTRACTED`, and `SYNCING`.

The database must preserve the Phase 1 state/origin construction invariant:

- FAILED_RETRYABLE and FAILED_FINAL require failure_origin to be one of
  PROCESSING, EXTRACTED, or SYNCING;
- every other state requires failure_origin IS NULL.

The database must not encode the complete lifecycle transition graph. Legality
of transition_to, retry, and reopen remains domain behavior. Phase 2 does not
expose lifecycle mutation endpoints.

### 4.4 Ordered snapshots

The domain exposes tuple snapshots. SQL result order is not implicit, so every
ordered child collection has an explicit zero-based position and a unique
constraint on (order_id, position):

- order_lines;
- source_documents;
- validation_issues.

Reconstruction must query each collection with ORDER BY position ASC and
construct tuples in that order.

### 4.5 Money and quantity

OrderLine.quantity, submitted_price, and trusted_catalogue_price remain Python
Decimal values. PostgreSQL uses NUMERIC; no binary floating-point conversion
is allowed. No arbitrary precision or scale is imposed without a concrete
technical requirement.

Database checks enforce the same applicable lower bounds as Phase 1:

- quantity is greater than zero;
- submitted price, when present, is greater than or equal to zero;
- trusted catalogue price, when present, is greater than or equal to zero.

The mapper must construct Decimal values before constructing domain records.

### 4.6 Source-document metadata

Phase 1 metadata is an immutable ordered tuple of (str, str) pairs and may
contain duplicate keys. It must not be stored as a JSON object, because object
keys lose both ordering and duplicates.

The persistence representation is JSONB containing an ordered array of pairs:

~~~json
[["message_source", "email"], ["mailbox", "orders"]]
~~~

The HTTP representation is an ordered array of objects:

~~~json
[
  {"key": "message_source", "value": "email"},
  {"key": "mailbox", "value": "orders"}
]
~~~

The API mapper converts the object form to the domain tuple; the persistence
mapper converts the tuple to the JSONB pair-array and back. The conversion is
lossless, including ordering and duplicate keys. The database check must at
least require the outer JSONB value to be an array; mapping validation enforces
that every entry is exactly a two-string pair.

Phase 2 stores metadata and references only. It does not store raw document
body, attachment bytes, or an upload blob.

### 4.7 Validation issues

Phase 2 persists ValidationIssue records but does not generate Phase 5
business rules. Persist:

- rule_code;
- severity;
- field;
- expected;
- actual;
- explanation;
- ordered position.

expected and actual may use JSONB as a persistence representation. This does
not change the Phase 1 type contract of object | None. The mapper must accept
JSON-compatible values and reject unsupported values explicitly rather than
silently changing their meaning; Phase 2 creates no validation issues from an
HTTP request.

The existing Order aggregate has no validation-issues collection. Therefore
validation issues remain separate mapped Phase 1 records associated with an
order in persistence/application read results. They are not added to the
aggregate, not put into a domain Order field, and not used to make a business
decision in Phase 2.

### 4.8 Audit events

AuditEvent remains a separate Phase 1 record. Every successful intake creates
exactly one initial event in the same database transaction:

~~~text
event_type: ORDER_RECEIVED
actor: system
description: Order received through API intake.
occurred_at: timezone-aware UTC timestamp
~~~

The client cannot supply or override this event. Audit retrieval orders by
occurred_at ASC, id ASC.

Phase 2 does not publish events, use an event bus, or implement event sourcing.

## 5. Relational persistence design

PostgreSQL is the authoritative application store. The aggregate is not stored
as one JSON document. The schema contains exactly these six Phase 2 tables:

1. orders
2. order_lines
3. source_documents
4. validation_issues
5. audit_events
6. order_creation_idempotency

No generic processing-attempt table is included. The roadmap permits such a
record later, but Phase 2 has no real processing-attempt behavior.

### 5.1 orders

| Column | Type | Rules |
| --- | --- | --- |
| id | UUID | Primary key; server generated. |
| customer_reference | TEXT nullable | Phase 1 value; no Phase 2 lookup. |
| po_number | TEXT nullable | Phase 1 value; no duplicate-PO policy. |
| order_date | DATE nullable | Phase 1 value. |
| requested_delivery_date | DATE nullable | Phase 1 value; no commercial-date policy. |
| currency | TEXT nullable | NULL or exactly three uppercase ASCII letters. |
| state | TEXT | Not null; check against all twelve OrderState values. |
| failure_origin | TEXT nullable | Conditional check described below. |
| created_at | TIMESTAMPTZ | Not null; persistence metadata. |

The failure_origin check must express:

~~~text
(state in {FAILED_RETRYABLE, FAILED_FINAL}
 and failure_origin in {PROCESSING, EXTRACTED, SYNCING})
or
(state not in {FAILED_RETRYABLE, FAILED_FINAL}
 and failure_origin is null)
~~~

The database also checks that a present failure_origin is one of the defined
state strings. The mapper always reconstructs state and failure_origin as
OrderState members before domain construction.

### 5.2 order_lines

| Column | Type | Rules |
| --- | --- | --- |
| id | UUID | Primary key; server generated for intake. |
| order_id | UUID | Non-null foreign key to orders.id, ON DELETE CASCADE. |
| position | INTEGER | Non-null, zero or greater; unique within an order. |
| sku | TEXT nullable | Phase 1 value. |
| description | TEXT nullable | Phase 1 value. |
| quantity | NUMERIC | Non-null; check quantity > 0. |
| submitted_price | NUMERIC nullable | Check submitted_price >= 0 when present. |
| trusted_catalogue_price | NUMERIC nullable | Check trusted_catalogue_price >= 0 when present. |

Use UNIQUE(order_id, position) and index order_id for aggregate child access.
The database need not repeat the Phase 1 “SKU or useful description” rule as a
complex SQL expression; the domain mapper enforces it, while the database
enforces numeric safety and referential integrity.

### 5.3 source_documents

| Column | Type | Rules |
| --- | --- | --- |
| id | UUID | Primary key; server generated for intake. |
| order_id | UUID | Non-null foreign key to orders.id, ON DELETE CASCADE. |
| position | INTEGER | Non-null, zero or greater; unique within an order. |
| document_type | TEXT | Non-null; check against the five Phase 1 values. |
| name | TEXT | Non-null; domain requires non-blank. |
| mime_type | TEXT | Non-null; domain requires non-blank. |
| sha256 | TEXT | Non-null; check for 64 ASCII hexadecimal characters. |
| message_id | TEXT nullable | Phase 1 metadata/reference. |
| storage_reference | TEXT nullable | Reference only; no raw content. |
| metadata | JSONB | Non-null ordered pair-array; outer value must be a JSON array. |

Use `UNIQUE(order_id, position)` and index `order_id`. There is no duplicate
document policy in Phase 2, so `sha256` is not globally unique.

The exact allowed document-type strings are `EMAIL_BODY`, `PDF`, `XLSX`,
`CSV`, and `FORM`.

### 5.4 validation_issues

| Column | Type | Rules |
| --- | --- | --- |
| order_id | UUID | Non-null foreign key to orders.id, ON DELETE CASCADE. |
| position | INTEGER | Non-null, zero or greater; part of the primary key. |
| rule_code | TEXT | Non-null; domain requires non-blank. |
| severity | TEXT | Non-null; check INFO, WARNING, or ERROR. |
| field | TEXT nullable | Domain requires non-blank when present. |
| expected | JSONB nullable | JSON persistence value. |
| actual | JSONB nullable | JSON persistence value. |
| explanation | TEXT | Non-null; domain requires non-blank. |

Use composite primary key (order_id, position). This supplies stable ordered
identity for the Phase 2 child collection without inventing a Phase 1 issue ID.
Indexing beyond the order foreign-key access path is not justified yet.

The exact allowed severity strings are `INFO`, `WARNING`, and `ERROR`.

### 5.5 audit_events

| Column | Type | Rules |
| --- | --- | --- |
| id | UUID | Primary key; server generated. |
| order_id | UUID | Non-null foreign key to orders.id, ON DELETE CASCADE. |
| event_type | TEXT | Non-null; domain requires non-blank. |
| actor | TEXT | Non-null; domain requires non-blank. |
| occurred_at | TIMESTAMPTZ | Non-null timezone-aware timestamp stored in UTC. |
| description | TEXT | Non-null; domain requires non-blank. |

Index (order_id, occurred_at, id) to support deterministic audit retrieval.
The schema does not attempt to enforce that every possible event row is a
valid lifecycle event; Phase 2 enforces the exact initial event in application
orchestration.

### 5.6 order_creation_idempotency

| Column | Type | Rules |
| --- | --- | --- |
| idempotency_key | TEXT | Primary key; non-blank and maximum 128 characters. |
| request_fingerprint | CHAR(64) | Non-null lowercase SHA-256 hex digest. |
| order_id | UUID | Non-null foreign key to orders.id, ON DELETE RESTRICT. |
| created_at | TIMESTAMPTZ | Non-null UTC persistence metadata. |

The primary key on idempotency_key is the concurrency authority. Add a unique
constraint on order_id so one created order cannot acquire multiple creation
records. Add no expiry, TTL, cleanup worker, Redis lock, distributed lock, or
retry subsystem.

All six tables are created by one Alembic revision,
0002_phase2_persistence or the exact equivalent of the repository’s revision
naming convention. The revision must provide the foreign keys, unique
constraints, checks, primary keys, and only the minimal indexes justified
above. Downgrade must remove all Phase 2 tables and return to the
0001_baseline schema.

## 6. HTTP API contract

Phase 2 exposes exactly these business endpoints:

~~~text
POST /v1/orders
GET  /v1/orders
GET  /v1/orders/{order_id}
GET  /v1/orders/{order_id}/audit
~~~

Existing /health and /ready remain available and retain their current purpose
and behavior. No approval, rejection, transition, processing, validation,
upload, or integration endpoint is added.

### 6.1 POST request shape

The request accepts already-known values only:

~~~json
{
  "customer_reference": "CUST-001",
  "po_number": "PO-001",
  "order_date": "2026-09-14",
  "requested_delivery_date": "2026-10-01",
  "currency": "USD",
  "lines": [
    {
      "sku": "SKU-001",
      "description": "Blue widget",
      "quantity": "2.00",
      "submitted_price": "10.00",
      "trusted_catalogue_price": null
    }
  ],
  "source_documents": [
    {
      "document_type": "FORM",
      "name": "web-form",
      "mime_type": "application/json",
      "sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "message_id": null,
      "storage_reference": "synthetic://form/001",
      "metadata": [
        {"key": "message_source", "value": "form"},
        {"key": "mailbox", "value": "orders"}
      ]
    }
  ]
}
~~~

Every request field is optional except for fields required by the nested
record shape; lines and source_documents default to empty arrays. Exact
transport field definitions follow the Phase 1 types:

- order fields: customer_reference, po_number, order_date,
  requested_delivery_date, and currency;
- line fields: sku, description, quantity, submitted_price, and
  trusted_catalogue_price;
- source-document fields: document_type, name, mime_type, sha256, message_id,
  storage_reference, and ordered metadata pairs.

Pydantic v2 request models use extra="forbid" at every nested level. They must
reject unknown fields and malformed transport shapes. They must not duplicate
later business policy. Domain construction remains responsible for structural
validity such as positive quantity, non-negative prices, currency shape,
non-blank required record text, and valid source hashes.

The client must not supply:

- order IDs, line IDs, source-document IDs, or any persistence IDs;
- lifecycle state or failure origin;
- validation issues or audit events;
- persistence timestamps, including created_at and occurred_at.

The server generates all IDs and timestamps. The application constructs an
Order.received(...) domain snapshot, so the state is always RECEIVED.

### 6.2 Idempotency header

POST /v1/orders requires the Idempotency-Key header. It is opaque,
case-sensitive, non-blank after no semantic normalization, and at most 128
characters. A missing, blank, or overlong header is a malformed request and
returns 422. The key is not lowercased, trimmed for identity, or otherwise
rewritten.

### 6.3 POST responses

New successful creation returns 201 Created and the detailed order response.
The response represents the durable RECEIVED order and includes created_at.

An idempotent replay with the same key and the same semantic request returns
the original order result, including the same order ID and creation timestamp,
and returns 201 Created. The replay performs no second order, child row, audit
row, or idempotency-row write.

The first successful creation always has exactly one initial audit event with
the fixed values in section 4.8. The initial audit event is not embedded in the
order-detail response; it is retrieved through the separate audit endpoint.

### 6.4 GET detail response

GET /v1/orders/{order_id} returns 200 with a dedicated detail schema. It
contains:

- the Phase 1 order fields;
- created_at persistence/API metadata;
- ordered lines;
- ordered source documents with lossless metadata mapping;
- persisted validation issues ordered by position.

SQLAlchemy ORM objects are never serialized directly. Audit history remains a
separate response and endpoint. A syntactically invalid UUID path is a 422
transport error; a valid UUID with no order is a 404.

### 6.5 GET list response

GET /v1/orders accepts only:

- limit, default 50, maximum 100;
- offset, default 0, minimum 0.

No filters, fuzzy search, dynamic sorting, or cursor pagination are included.
Ordering is deterministic:

~~~sql
created_at DESC, id DESC
~~~

The response shape is:

~~~json
{
  "items": [
    {
      "id": "...",
      "customer_reference": "CUST-001",
      "po_number": "PO-001",
      "order_date": "2026-09-14",
      "requested_delivery_date": "2026-10-01",
      "currency": "USD",
      "state": "RECEIVED",
      "created_at": "2026-09-14T10:00:00Z"
    }
  ],
  "limit": 50,
  "offset": 0,
  "total": 137
}
~~~

List items are summaries only. They do not include lines, source documents,
validation issues, or audit events. Total is the count of all persisted orders
without speculative filters.

### 6.6 GET audit response

GET /v1/orders/{order_id}/audit returns 200 with a dedicated ordered
collection of audit-event response objects. Each object includes the Phase 1
audit fields (id, order_id, event_type, actor, occurred_at, and description).
Audit rows are ordered by occurred_at ASC, id ASC. A missing order returns 404;
the endpoint must not expose an orphan audit row.

### 6.7 HTTP error mapping

Phase 2 uses a small structured error shape where an application error needs a
stable code:

~~~json
{
  "detail": {
    "code": "IDEMPOTENCY_CONFLICT",
    "message": "Idempotency key was already used for a different request."
  }
}
~~~

Expected outcomes are:

- 422 for malformed request shape, missing/invalid idempotency header, or
  domain structural validation failure where appropriate;
- 404 for a missing order;
- 409 for same key with a different semantic request;
- 500 for unexpected internal failures.

OrderNotFoundError and IdempotencyConflictError are HTTP-independent
application exceptions. Application code never raises HTTPException; the
FastAPI API layer translates these exceptions. No general exception hierarchy
or mature error taxonomy is introduced.

Unexpected failures must not expose SQL, credentials, stack traces, or internal
connection details.

## 7. Idempotent creation design

### 7.1 Fingerprint input

The request fingerprint is SHA-256 over a deterministic canonical serialization
of the validated semantic request model. It is not computed from raw HTTP
bytes. Therefore JSON whitespace and object key order do not affect identity.

Canonical serialization uses UTF-8 JSON with no insignificant whitespace,
stable object-key ordering, and explicit representations for dates, enums,
decimals, and ordered collections. The canonical semantic object has these
fields in meaning, regardless of input JSON key order:

~~~text
customer_reference
po_number
order_date
requested_delivery_date
currency
lines[]
source_documents[]
~~~

Each line includes its validated semantic fields in the request order. Each
source document includes its validated semantic fields, and metadata remains
an ordered array of key/value pairs in the request order. List ordering is
semantic because it becomes the domain snapshot position. Generated order,
line, document, audit IDs, timestamps, state, failure origin, and database
metadata are not fingerprinted.

### 7.2 Decimal normalization

Before JSON serialization, every Decimal is represented as a canonical base-10
string:

- finite Decimal values only;
- trailing insignificant zeroes removed;
- exponent notation expanded to a plain decimal representation;
- any zero, including 0.0, 0.00, and -0.00, represented as "0";
- 5.0 and 5.00 therefore fingerprint identically;
- no binary float conversion.

Dates use ISO-8601 calendar strings. Enum values use their Phase 1 string
values. Optional nulls are represented as JSON null; omitted collection fields
are materialized as empty arrays by the validated request model.

The canonical serializer is a small pure function with unit tests. It does not
normalize arbitrary strings or reorder semantic arrays beyond the explicit
rules above.

### 7.3 Database-authoritative concurrency protocol

The unique database constraint on
order_creation_idempotency.idempotency_key is the concurrency authority. A
SELECT followed by an INSERT is not a correct uniqueness protocol and must not
be used as the only protection.

The create application operation uses this transaction sequence:

1. Validate the transport request and compute its canonical fingerprint.
2. Build server-generated IDs and UTC timestamps and construct the RECEIVED
   Phase 1 domain order.
3. Start one database transaction.
4. Insert the order, ordered children, and exactly one fixed initial audit row.
5. Insert the idempotency row containing the opaque key, fingerprint, order ID,
   and creation timestamp.
6. Commit the transaction only if every required insert succeeds.
7. Return the newly persisted detail result.

The idempotency insert may block on PostgreSQL’s unique constraint while a
concurrent transaction with the same key decides its outcome. If it loses the
unique-key race, the losing transaction is rolled back in full. The application
then starts a fresh read transaction, loads the committed idempotency row, and:

- returns the referenced original order for an equal fingerprint;
- raises IdempotencyConflictError for a different fingerprint.

This protocol means concurrent identical requests produce exactly one durable
order, exactly one initial audit event, and exactly one idempotency row. A
concurrent same-key/different-payload loser returns 409 and leaves no
provisional order, child row, audit row, or orphan idempotency row. If the
original transaction fails before commit, its complete rollback allows a
competing request to become the durable winner.

There is no TTL, expiry worker, cleanup worker, Redis lock, distributed lock,
or generalized retry framework.

## 8. Domain/persistence mapping

ORM objects never become the business model and are never exposed outside
persistence responsibilities.

### 8.1 Write path

~~~text
Pydantic request
  → validated transport values
  → server-generated Phase 1 records and Order.received(...)
  → explicit persistence mapper
  → SQLAlchemy ORM rows
~~~

The mapper must:

- assign server IDs only at the application/persistence boundary;
- preserve child positions from tuple/list order;
- convert Decimal to NUMERIC without float conversion;
- store source metadata as an ordered JSONB pair-array;
- store state and failure origin as explicit string values;
- store timezone-aware UTC timestamps;
- reject malformed domain snapshots before required rows are committed.

### 8.2 Read path

~~~text
SQLAlchemy ORM rows
  → explicit persistence mapper
  → Phase 1 Order and separate ValidationIssue/AuditEvent records
  → dedicated API response schemas
~~~

Aggregate reconstruction loads the order row and its child rows with explicit
ordering, converts values to Phase 1 types, and constructs a validated domain
Order. Validation issues and audit events are separately mapped Phase 1
records associated with the order because neither is a field on the Phase 1
Order aggregate. API serialization is performed only by Pydantic response
schemas.

Direct ORM mutation must not become a lifecycle bypass. Any future state
mutation must construct a new domain snapshot through the Phase 1 operation
and persist the resulting values; Phase 2 has no state-mutation endpoint.

## 9. Application operations

The application layer contains only the orchestration needed now:

- create_order: validate the already-shaped request, fingerprint it, create a
  RECEIVED domain snapshot, atomically persist the order/children/initial
  audit/idempotency row, and resolve replay/conflict behavior;
- get_order: load one order detail or raise OrderNotFoundError;
- list_orders: retrieve deterministic summaries plus limit/offset total;
- get_order_audit: verify the order exists, then retrieve deterministic audit
  history.

The application layer owns transaction boundaries for creation. It does not
raise HTTP exceptions, call AI or external systems, apply Phase 5 rules, or
provide a generalized service framework.

The concrete repository module exposes only explicit operations needed by these
use cases. It does not define an abstract repository protocol, generic CRUD
base, or hidden session/transaction framework.

## 10. Session and lifecycle design

The existing async engine and application lifespan behavior remain
conceptually intact:

~~~text
AsyncEngine → async_sessionmaker → request-scoped AsyncSession
~~~

database.py adds one application-level async_sessionmaker[AsyncSession] created
from the existing engine. A small FastAPI dependency creates one session per
request and closes it after the request. It must not create a new engine per
request, construct ad hoc sessions inside routes, or use a DI library.

The create operation owns its transaction with an explicit AsyncSession.begin()
boundary. The dependency does not commit business writes. Read operations use
the request session and close it through the dependency lifecycle. Engine
disposal remains in the existing app lifespan.

Alembic migration application remains an explicit deployment/development
operation (make migrate and CI migration setup), not an unbounded startup side
effect. A fresh PostgreSQL database must be able to migrate cleanly from
0001_baseline to the Phase 2 head through that workflow.

## 11. Alembic and metadata strategy

M2B introduces one migration revision after 0001_baseline:

~~~text
0001_baseline → 0002_phase2_persistence
~~~

The revision creates all six tables, foreign keys, primary/unique constraints,
state/origin and numeric defense-in-depth checks, and justified minimal
indexes. Its downgrade drops Phase 2 tables in foreign-key-safe order and
returns to 0001_baseline. A fresh upgrade after downgrade must succeed again.

Once ORM metadata exists, alembic/env.py changes target_metadata from None to
the persistence metadata source. The metadata import must be explicit and must
not import the FastAPI application or create a database engine as a side
effect. Autogeneration is a drift aid, not a replacement for reviewed
migration files.

No additional migration, table, enum type, trigger, stored procedure, or
over-indexing is introduced for this phase.

## 12. Testing design and verification boundaries

Testing follows the repository’s red-green-refactor practice where practical:
write a focused failing test, verify the expected failure, implement the
smallest behavior, verify green, and refactor only when justified. Tests use
synthetic data only and must never call live AI providers or create external
business-system side effects.

### 12.1 Pure/unit coverage

Unit tests cover behavior that does not require PostgreSQL:

- Pydantic request shape and nested extra="forbid" rejection;
- missing/blank/overlong idempotency-key transport behavior where pure;
- canonical request serialization;
- SHA-256 fingerprint generation;
- Decimal normalization, including 5.0 versus 5.00;
- domain-to-persistence and persistence-to-domain mapper behavior;
- ordered metadata pair mapping with duplicate keys;
- error translation helpers, if any.

The Phase 1 domain suite remains unchanged and must run with PostgreSQL and
Docker unavailable:

~~~bash
uv run pytest tests/unit/domain -q --no-cov
~~~

Phase 2 must not add infrastructure imports to the domain package.

### 12.2 Real PostgreSQL integration coverage

Mocks cannot prove SQL constraints, transaction atomicity, or concurrency. The
integration suite uses real PostgreSQL and covers:

- upgrade empty database through 0001_baseline → 0002_phase2_persistence;
- downgrade 0002_phase2_persistence → 0001_baseline;
- upgrade again successfully;
- expected tables, foreign keys, primary keys, unique constraints, checks,
  and minimal indexes;
- minimal RECEIVED order creation;
- populated RECEIVED order creation;
- exact line, source-document, and validation-issue ordering after round trip;
- ordered duplicate-key source metadata round trip;
- existing order detail retrieval;
- missing order behavior;
- deterministic list ordering;
- limit/offset pagination and total count;
- exactly one initial ORDER_RECEIVED audit event;
- deterministic audit ordering;
- same key plus same payload replay;
- same key plus different payload conflict;
- concurrent identical requests;
- concurrent conflicting requests;
- foreign-key enforcement;
- rollback with no partial order, child, audit, or idempotency rows;
- direct-insert rejection by structural database constraints;
- application startup, /health, and /ready behavior.

### 12.3 API integration coverage

HTTPX/asyncio.run patterns remain acceptable; pytest-asyncio or another
runtime/dev dependency is not added merely for style. API tests cover:

- POST /v1/orders with minimal and populated requests;
- 201 creation and 201 same-request replay;
- generated IDs/state/timestamps not accepted from clients;
- unknown-field rejection and 422 structural/domain failures;
- required idempotency header and 409 conflicting reuse;
- GET /v1/orders summaries, ordering, pagination, and total;
- GET /v1/orders/{id} detail and 404;
- GET /v1/orders/{id}/audit ordering and 404;
- no duplicate order or audit event on replay.

### 12.4 Repository quality gates

At the implementation milestones, the applicable repository checks remain:

~~~bash
make check
~~~

This covers Ruff, format check, mypy, backend tests/build, frontend lint/build,
and the existing configured coverage floor. Documentation-only M2A does not
invent implementation tests or claim Phase 2 behavior is passing. Its checks
are the documentation and repository checks in section 15.

## 13. Detailed implementation plan for M2B–M2F

This is the approved execution outline for the later milestones. It is not a
claim that those milestones are complete, and no item below is implemented by
the M2A design commit.

### M2A — Persistence & API Contract — COMPLETE

Delivered the authoritative design, implementation boundaries, companion
implementation plan, status update, self-review, and documentation-only
verification. This milestone added no production behavior, tests, dependencies,
migrations, or API routes.

### M2B — Relational Schema & Domain Mapping — COMPLETE

Planned files and responsibilities:

- src/opsflow/persistence/models.py: SQLAlchemy metadata and six explicit table
  models, including the checks, foreign keys, child positions, and minimal
  indexes in section 5;
- src/opsflow/persistence/mappers.py: explicit conversion between ORM rows,
  Phase 1 records, Decimal/NUMERIC values, and ordered metadata pair arrays;
- alembic/env.py: import the persistence metadata as target_metadata;
- alembic/versions/0002_phase2_persistence.py: one reviewed upgrade/downgrade
  revision after 0001_baseline;
- tests/unit/persistence/: mapper and pure persistence representation tests;
- tests/integration/: migration, schema, direct-constraint, and round-trip
  persistence tests.

The milestone is complete after real PostgreSQL proved upgrade, downgrade,
re-upgrade, constraints, and ordered mapping in exact-head CI. It introduced no
repository use cases or HTTP routes.

### M2C — Repository & Durable Reads — COMPLETE

Planned files and responsibilities:

- src/opsflow/persistence/repositories.py: concrete order create-row,
  detail-read, list/count, and audit-read operations; no abstract repository
  interfaces or generic CRUD base;
- src/opsflow/application/orders.py: thin read orchestration for get_order,
  list_orders, and get_order_audit;
- src/opsflow/application/errors.py: OrderNotFoundError only as needed;
- tests/integration/: existing-order, missing-order, detail reconstruction,
  list ordering, pagination, count, and audit-ordering behavior.

The milestone is complete only after ORM objects stay inside persistence and all
reads reconstruct validated Phase 1 records before response serialization.

### M2D — Idempotent Order Creation — NOT STARTED

Planned files and responsibilities:

- src/opsflow/application/orders.py: create_order transaction boundary;
- src/opsflow/application/errors.py: IdempotencyConflictError;
- the smallest explicit pure canonicalization/fingerprint location selected
  during implementation, with no generic serialization framework;
- tests/unit/: canonical serialization and Decimal normalization tests;
- tests/integration/: atomic initial audit, same-key replay, conflict,
  rollback, and concurrent identical/conflicting request tests.

The milestone is complete only after PostgreSQL uniqueness, rollback, and
concurrency behavior prove the protocol in section 7. It does not add any
other retry or distributed-lock infrastructure.

### M2E — Core /v1/orders API & Hardening — NOT STARTED

Planned files and responsibilities:

- src/opsflow/api/schemas.py: Pydantic v2 request/detail/summary/audit/list
  schemas with nested extra="forbid" and dedicated response contracts;
- src/opsflow/api/orders.py: exactly the four routes and application-error
  translation;
- src/opsflow/database.py: async sessionmaker support;
- src/opsflow/main.py: router inclusion, one request-session dependency, and
  preserved lifespan/health/readiness behavior;
- tests/integration/ and API tests: status codes, contracts, 404/409/422,
  pagination, replay, and duplicate prevention.

The milestone is complete only after all four endpoints and the full backend,
frontend, package-build, secret-scan, and regression checks pass. No
authentication, request tracing, transition API, or review workflow is added.

### M2F — Independent Phase 2 Audit & Closeout — NOT STARTED

Use a fresh context to perform an adversarial review of architecture, schema,
transactions, idempotency, API contracts, tests, security, cost, and Phase 3+
scope leakage. Remediate findings before closeout, record the durable audit,
open the PR, integrate by merge commit to main, verify post-merge CI on the
exact final SHA, and clean up the Phase 2 branch. M2F is not part of the M2A
implementation commit.

## 14. Phase 2 exit criteria

Phase 2 can be marked complete only when all of these are evidenced on the
final Phase 2 SHA:

1. A fresh PostgreSQL database migrates cleanly to current head.
2. POST /v1/orders creates a durable RECEIVED order.
3. Minimal and populated orders persist correctly.
4. The initial ORDER_RECEIVED audit event is atomic with creation.
5. Same idempotency key plus same request creates exactly one order.
6. Same key plus different request produces 409.
7. Genuine concurrent duplicate requests cannot create duplicates.
8. Transaction failure leaves no partial durable state.
9. Existing order detail is retrievable.
10. Missing order returns 404.
11. Order listing is paginated and deterministically ordered.
12. Audit history is retrievable and deterministic.
13. Phase 1 domain/persistence boundaries remain intact.
14. No Phase 3+ functionality leaks into Phase 2.
15. Domain tests run without PostgreSQL.
16. PostgreSQL integration tests prove schema and transaction behavior.
17. Ruff passes.
18. Ruff format check passes.
19. mypy passes.
20. Backend tests pass.
21. Frontend regression checks pass.
22. Package build passes.
23. Gitleaks passes.
24. CI passes on the exact final Phase 2 SHA.
25. Independent Phase 2 audit passes before integration.

These are future Phase 2 exit criteria. They are not M2A claims and are not
reported as passing by this design-only milestone.

## 15. M2A documentation-only verification record

The completed M2A documentation review checked this document and its companion
plan with fresh eyes for:

- no unresolved placeholders;
- no contradiction with the Phase 1 domain contract;
- no conflict with the roadmap or system overview;
- no accidental Phase 3+ scope;
- no speculative abstraction;
- no duplicated business policy in the API contract;
- internally consistent idempotency, persistence, mapping, migration,
  concurrency, and response semantics;
- representation of every approved Phase 2 decision.

Run these checks for the documentation-only change:

~~~bash
git diff --check
make check
~~~

Also inspect the complete diff, validate every local Markdown link, confirm that
only the design and required status documentation changed, confirm no
source/test/dependency/migration files changed, and check the diff for
credentials, API keys, private business data, and real customer documents.

The repository’s existing make check was run as requested even though M2A adds
no application behavior. Its observed result is reported separately from the
not-yet-implemented Phase 2 exit criteria.
