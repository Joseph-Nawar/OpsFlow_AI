# Phase 5 — Deterministic Validation Design

## Document control

- **Repository:** `Joseph-Nawar/OpsFlow_AI`
- **Phase:** Phase 5 — Deterministic Validation
- **Current milestone:** M5A — Deterministic Validation Contract & Design
- **Design status:** Authoritative Phase 5 design specification; implementation is not authorized by this document alone
- **Branch:** `phase/5-deterministic-validation`
- **Design date:** 2026-09-17
- **Starting main SHA:** `84de8ed70b745bf987227953495320deccee94fe`

This document is design documentation only. It defines the implementation-ready
contract for Phase 5 and creates no production source, tests, migration,
dependency, API, UI, workflow, or implementation-plan artifact.

### Status reconciliation at the Phase 5 baseline

The Phase 4 independent audit is a passing closeout record, and the README and
roadmap narrative identify Phase 4 as complete. The roadmap's phase overview
table still contains a stale `IN PROGRESS` value for Phase 4 at the starting
SHA. The Phase 5 brief and the passing Phase 4 audit are the status authority
for this design task: Phase 4 is treated as **COMPLETE** and Phase 5 is
**NOT STARTED**. This M5A document does not change the README or roadmap; the
stale overview-table value remains an existing documentation issue outside the
requested file scope.

## Governing sources

The design is governed by:

1. [`AGENTS.md`](../../../AGENTS.md)
2. [Project roadmap](../../roadmap/project-roadmap.md)
3. [System overview](../../architecture/system-overview.md)
4. [Phase 1 domain model](../../architecture/domain-model.md)
5. [Development guide](../../development/development-guide.md)
6. [Phase 4 independent audit](../../audits/phase-4-audit.md)
7. [Phase 4 structured-extraction design](2026-09-17-phase-4-structured-ai-extraction-design.md)
8. The approved Phase 5 milestone brief and user requirements

Phase 4 supplies the `ExtractionDraft` input contract. The existing `Order`,
`OrderLine`, `SourceDocument`, `ValidationIssue`, `AuditEvent`, and state-machine
contracts remain authoritative and are not redesigned here.

## 1. Purpose and authority boundary

Phase 5 is the deterministic trust boundary between untrusted AI extraction and
trusted business workflow state.

> AI interprets. Deterministic software decides.

The input to Phase 5 is:

```text
ExtractionDraft
+ trusted business data
+ explicit ValidationPolicy
+ explicit ValidationContext
```

The output is a `ValidationResult`. Only deterministic Phase 5 logic decides:

- whether extracted values are acceptable;
- whether an order needs human review;
- whether an order is ready for approval;
- which trusted customer, product, catalogue, and inventory values may be
  promoted into trusted order state.

The LLM never decides routing, approval readiness, customer or product
identity, duplicate status, inventory sufficiency, price acceptability, or any
external side effect. Phase 5 does not call an LLM. A persisted Phase 4 draft
is treated as untrusted input until this deterministic boundary has completed.

## 2. Approved top-level flow

The architecture is:

```text
CanonicalDocument
    ↓
ExtractionDraft
[UNTRUSTED]
    ↓
durable extraction snapshot
    ↓
TrustedBusinessData + ValidationPolicy + ValidationContext
    ↓
ValidationEngine
[PURE / SYNC / NO I/O]
    ↓
ValidationResult
    ├── issues
    ├── trusted/promotable data
    ├── approval requirement
    └── route
    ↓
Phase 5 application service
    ↓
EXTRACTED
    → VALIDATED
        ├── NEEDS_REVIEW
        └── READY_FOR_APPROVAL
```

`CanonicalDocument` and `ExtractionDraft` are separated by the Phase 4
extraction boundary. The durable snapshot records the draft before business
validation. The validation engine is separated from persistence and provider
access. The application service owns the final transaction and state changes.
The diagram describes the contract and data dependencies; the application
holds the canonical snapshot serialization until the final transaction so the
snapshot, issues, promotion, state, and audits commit or roll back together.

The existing state machine remains authoritative. Phase 5 introduces no new
`OrderState` value and no alternate transition path. The only legal success
paths are:

```text
EXTRACTED → VALIDATED → NEEDS_REVIEW
EXTRACTED → VALIDATED → READY_FOR_APPROVAL
```

`READY_FOR_APPROVAL` means validation passed; it does not mean the order is
approved or synchronized.

## 3. Durable untrusted extraction snapshot

### 3.1 Boundary and ownership

`ExtractionDraft` remains provider-neutral and is persisted separately from the
trusted `Order` and `OrderLine` rows. One snapshot represents one draft for one
persisted `Order` and one persisted `SourceDocument`.

The snapshot is an immutable record. It is insert-only through the Phase 5
application/repository contract: there is no update, replacement, delete, or
provider-response persistence operation. An exact replay of an existing
order/source snapshot is resolved at the application boundary; a conflicting
draft is rejected there. Neither case creates a second snapshot.

The source identity precondition is strict before the snapshot is persisted or
used for validation:

```text
draft.source_sha256 == source_document.sha256.casefold()
draft.source_document_type == source_document.document_type
source_document.order_id == order.id
```

The draft already requires a lowercase SHA-256 digest. The persisted source
document may contain either hexadecimal case because the Phase 2 contract
allows both; the application compares case-insensitively and stores the
canonical lowercase draft value. A source identity mismatch is an
application/integrity error, not a `ValidationIssue`.

The snapshot has no authority to change the source document, source hash,
document type, or order ownership. Source documents and their original
references remain preserved throughout review and promotion.

### 3.2 Recommended relational envelope

Migration `0003_phase5_extraction_snapshots` introduces one table:

| Column | Type | Nullability and meaning |
| --- | --- | --- |
| `id` | PostgreSQL UUID | Primary key, application-assigned snapshot identity. It is not generated by `ValidationEngine`. |
| `order_id` | PostgreSQL UUID | Required foreign key to `orders.id`, `ON DELETE CASCADE`. |
| `source_document_id` | PostgreSQL UUID | Required foreign-key component identifying the source document. |
| `source_sha256` | Text | Required lowercase 64-character SHA-256 copied from the draft; independently queryable. |
| `source_document_type` | Text | Required `SourceDocumentType.value`; independently queryable. |
| `payload` | JSONB | Required deterministic serialized `ExtractionDraft`; never raw provider output. |
| `created_at` | `TIMESTAMPTZ` | Required application-supplied timezone-aware recording time. |

The table has these constraints and indexes:

- primary key `id`;
- `UNIQUE (order_id, source_document_id)` named
  `uq_extraction_snapshots_order_source`;
- a foreign key from `order_id` to `orders.id` with `ON DELETE CASCADE`;
- a foreign key from `(source_document_id, order_id)` to
  `(source_documents.id, source_documents.order_id)` with `ON DELETE CASCADE`;
- a lowercase SHA-256 check named `ck_extraction_snapshots_sha256`;
- a source-document-type check named
  `ck_extraction_snapshots_document_type` for exactly
  `EMAIL_BODY`, `PDF`, `XLSX`, `CSV`, or `FORM`;
- a JSON object check named `ck_extraction_snapshots_payload_object` using
  `jsonb_typeof(payload) = 'object'`;
- a non-unique lookup index on `source_sha256`, named
  `ix_extraction_snapshots_source_sha256`.

The existing `source_documents` table receives the narrow redundant unique
constraint `UNIQUE (id, order_id)`, named
`uq_source_documents_id_order_id`, solely so PostgreSQL can enforce the
composite ownership foreign key. This does not change the source-document
domain contract. The snapshot must never use a globally unique source hash:
the same hash must remain representable under another order so deterministic
validation can emit `DOCUMENT_ALREADY_PROCESSED` rather than failing during
snapshot insertion.

Deleting an order cascades through its source documents and extraction
snapshots, consistent with the existing order graph. The application exposes no
snapshot deletion operation. Direct privileged database maintenance is outside
the application contract and is not a Phase 5 workflow.

### 3.3 Deterministic JSONB payload

`payload` is the serialized typed draft, not the provider response. Its exact
top-level shape is:

```json
{
  "source": {
    "sha256": "lowercase-64-character-sha256",
    "document_type": "PDF"
  },
  "customer_name": null,
  "customer_reference": "CUST-001",
  "po_number": "PO-1001",
  "order_date": "2026-09-01",
  "requested_delivery_date": "2026-09-15",
  "currency": "USD",
  "lines": [
    {
      "sku": "SKU-001",
      "description": "Widget",
      "quantity": "2.5",
      "submitted_price": "10"
    }
  ],
  "notes": null,
  "evidence": [
    {
      "field_path": "po_number",
      "source_location": "page:1",
      "quote": "PO-1001"
    }
  ]
}
```

The serializer has these locked rules:

- all listed top-level fields are present, including explicit `null` values;
- `source.sha256` and `source.document_type` are present in the payload and
  must equal the relational envelope columns;
- line objects always contain `sku`, `description`, `quantity`, and
  `submitted_price`, with explicit `null` values;
- evidence objects always contain `field_path`, `source_location`, and
  `quote`;
- line array order is exactly `ExtractionDraft.lines` order;
- evidence array order is exactly `ExtractionDraft.evidence` order;
- `date` values use exact ISO `YYYY-MM-DD` strings;
- `Decimal` values use canonical finite strings with no exponent notation:
  fixed-point formatting, insignificant trailing fractional zeroes removed,
  and every zero, including negative zero, represented as `"0"`;
- text is preserved after Phase 4 structural validation; Phase 5 does not
  trim, case-fold, spell-correct, or semantically rewrite it;
- no UUID, timestamp inside the draft payload, prompt text, model name, raw
  provider response, provider SDK object, API key, or provider-internal field
  is serialized;
- the JSONB value is constructed from ordinary JSON-safe `dict`, `list`,
  string, boolean, integer, and `null` values only.

JSON object-key order is not a semantic part of JSONB. The arrays and scalar
representations above are the ordering and canonicalization contract used for
round-trip equality and replay comparison.

### 3.4 Replay and conflict semantics

The unique `(order_id, source_document_id)` key defines the intended
validation boundary. Before attempting insertion, the application reads any
existing snapshot for that pair:

1. no row exists: validation may proceed;
2. a row exists and its source identity and canonical payload equal the current
   draft: raise/return an application-level **snapshot replay** outcome and do
   not insert another row;
3. a row exists but source identity or payload differs: raise an application-
   level **snapshot conflict** error and do not insert another row.

The final transaction repeats this check under the locked order row. A database
unique violation is translated into the same replay/conflict distinction after
the existing row is read. It is never converted into a business validation
issue.

## 4. Pure `ValidationEngine`

### 4.1 Contract

The engine is synchronous, deterministic, side-effect-free, and database-free.
Its conceptual signature is:

```text
ExtractionDraft
+ TrustedBusinessData
+ ValidationPolicy
+ ValidationContext
→ ValidationResult
```

The engine is:

- synchronous;
- pure and deterministic for equal inputs;
- database-free and network-free;
- FastAPI-free and SQLAlchemy-free;
- provider-free;
- clock-free;
- environment-free.

It must not call `date.today()`, `datetime.now()`, `random`, UUID
generation, a network, a database, a provider, or an environment-variable
reader. UUIDs and timestamps needed for persistence or audit events are created
by the application boundary after the engine returns.

### 4.2 Stable execution order

The engine evaluates rules in this order and appends issues in this order:

1. customer identity;
2. PO identity and customer-scoped duplicate;
3. source-document duplicate;
4. order and delivery dates;
5. order currency;
6. order-line presence;
7. each line in ascending zero-based index order, evaluating the per-line
   rules in the order defined in the rule matrix;
8. high-value approval classification.

The engine does not stop after the first issue. It skips only rules whose
required predecessor value is absent or invalid, avoiding meaningless
cascaded comparisons while continuing all independent checks. This yields a
stable issue tuple for multiple simultaneous violations.

## 5. Trusted business-data contract

### 5.1 Provider-neutral records

Trusted reference data is an immutable input snapshot to the engine. The
provider never returns a route, severity, approval level, or `ValidationIssue`.
It returns records and lookup facts; the engine applies the policy.

Conceptually:

```python
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
    duplicate_customer_po: bool
    document_already_processed: bool
```

The conceptual types are implementation targets, not source files created by
M5A. Their invariants are:

- customer references and names are non-blank; customer references are
  canonical trusted identifiers;
- `customer_candidates` contains only exact lookup candidates for this draft:
  exact reference matches when `customer_reference` is present, otherwise
  normalized exact name matches;
- exact customer candidate order is canonicalized by trusted reference;
- `products_by_line` has exactly the same length and order as
  `ExtractionDraft.lines`;
- a non-`None` product has a non-blank canonical SKU, a non-blank currency in
  three-uppercase-letter form, a finite nonnegative catalogue price or
  `None`, and a finite nonnegative available quantity or `None`;
- `available_quantity=None` means inventory information is unavailable or
  unknown; `Decimal("0")` is known zero availability;
- a trusted product lookup returns at most one exact SKU record. Duplicate
  exact SKU records are a trusted-data configuration/operational error, not a
  fabricated validation issue;
- `duplicate_customer_po` is true only for a customer-scoped exact identity
  match excluding the current order;
- `document_already_processed` is true only when the same source SHA-256 has
  an earlier processed extraction snapshot under another order/source;
- no record contains an API key, provider object, raw source content, raw
  provider response, or environment-dependent value.

### 5.2 `BusinessDataProvider` protocol

The provider-neutral protocol is intentionally one narrow async retrieval
operation so a future network-backed adapter can retrieve all trusted data
before the final database write transaction:

```python
class BusinessDataProvider(Protocol):
    async def get_validation_data(
        self,
        draft: ExtractionDraft,
        *,
        current_order_id: UUID,
        source_sha256: str,
    ) -> TrustedBusinessData: ...
```

The method performs deterministic exact lookups for:

- customer reference, when present and authoritative;
- normalized exact customer name, only when customer reference is absent;
- each non-null SKU, with no description fallback;
- customer-scoped existing PO references;
- processed source hashes.

The method may be async because Phase 9 may later use a network-backed Odoo
adapter. Phase 5 does not implement Odoo, HTTP, credentials, retries, caching,
or a generic integration framework. The provider must not mutate any external
system or reserve inventory. An operational/provider exception is an
application error, not a `ValidationIssue`.

### 5.3 `SandboxBusinessDataProvider`

Phase 5 includes `SandboxBusinessDataProvider` with synthetic in-memory data.
It is deterministic, credential-free, network-free, and suitable for CI.

Its immutable configuration contains tuples of customers and products, a
customer+PO reference set, and a processed-source-hash set. It canonicalizes
lookup result order by customer reference and SKU. It uses no environment
variables or current time.

Customer-name normalization is exactly:

```text
Unicode casefold
→ split on Unicode whitespace
→ join tokens with one ASCII space
```

Surrounding and repeated whitespace therefore does not affect an exact name
match. Punctuation, accents, transliteration, and spelling are not removed or
repaired. There is no fuzzy matching, edit distance, embedding, or LLM call.

The sandbox permits duplicate normalized customer names so the engine can
produce `AMBIGUOUS_CUSTOMER`. It rejects duplicate exact customer references
and duplicate exact SKUs as invalid trusted-data configuration. It returns
known-zero inventory distinctly from missing inventory and returns deterministic
snapshots for repeated equal requests.

## 6. Deterministic identity and matching rules

### 6.1 Customer

The customer identity procedure is:

1. if `customer_reference` is present, it is authoritative and only exact
   trusted-reference lookup is used;
2. if `customer_reference` is absent and `customer_name` is present, the
   normalized exact customer-name lookup is used;
3. zero candidates produces `UNKNOWN_CUSTOMER` when an identity was supplied;
4. multiple candidates produce `AMBIGUOUS_CUSTOMER`;
5. one inactive candidate produces `INACTIVE_CUSTOMER`;
6. one active candidate supplies the canonical trusted customer reference.

If both customer reference and name are absent, the result is
`CUSTOMER_REQUIRED`, not `UNKNOWN_CUSTOMER`. A reference is never replaced by
a name match, and an inactive or ambiguous candidate is never silently
promoted.

### 6.2 Product

SKU is authoritative. A missing SKU produces `SKU_REQUIRED`; description is
not a fallback identity. A present SKU with no exact trusted product produces
`UNKNOWN_SKU`. An inactive exact product produces `INACTIVE_SKU`. Exact SKU
matching is case-sensitive and does not use description similarity.

Phase 5 has no description-mismatch rule. If a later explicit rule ever checks
description text, it must use only deterministic exact or normalized matching;
semantic, fuzzy, and AI similarity are not permitted.

The engine does not attempt AI similarity validation, embeddings, fuzzy
matching, transliteration, or semantic comparison.

## 7. `ValidationPolicy`

`ValidationPolicy` is an immutable, explicit policy value, conceptually:

```python
@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    supported_currencies: tuple[str, ...]
    price_tolerance_fraction: Decimal
    high_value_threshold: Decimal
```

Its rules are:

- `supported_currencies` is a non-empty tuple of unique three-uppercase-letter
  currency codes in stable caller-provided order;
- `price_tolerance_fraction` is a finite `Decimal` greater than or equal to
  zero;
- `high_value_threshold` is a finite `Decimal` greater than or equal to zero;
- no policy value is read from an environment variable;
- no policy value is a magic constant hidden inside the engine;
- policy construction rejects floats, non-finite decimals, malformed currency
  codes, and duplicate currency entries.

The application composition root supplies one explicit policy instance to each
validation call. Phase 5 does not decide deployment-specific currency lists or
threshold values.

## 8. `ValidationContext`

`ValidationContext` is an immutable explicit evaluation context, conceptually:

```python
@dataclass(frozen=True, slots=True)
class ValidationContext:
    evaluation_date: date
```

`evaluation_date` is the only required context value. The engine uses it for
future and past date rules. The application or test supplies it; the engine
does not read the system clock, timezone, environment, or database.

## 9. `ValidationResult`

The immutable result contract is conceptually:

```python
@dataclass(frozen=True, slots=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...]
    route: ValidationRoute
    approval_level: ApprovalLevel
    order_total: Decimal | None
    validated_order_data: ValidatedOrderData | None
```

The recommended enums are:

```text
ValidationRoute:
    NEEDS_REVIEW
    READY_FOR_APPROVAL

ApprovalLevel:
    STANDARD
    ELEVATED
```

Result invariants:

- `issues` preserves the stable engine order;
- `route` is derived only from issue severity:
  any `ERROR` means `NEEDS_REVIEW`, otherwise `READY_FOR_APPROVAL`;
- `WARNING` and `INFO` alone never force `NEEDS_REVIEW`;
- `order_total` is the exact Decimal sum of `quantity * submitted_price` in
  extraction line order when every line has a positive quantity and
  nonnegative submitted price and the order has at least one line; otherwise
  it is `None`;
- `approval_level` is `ELEVATED` exactly when a computable total is greater
  than or equal to `high_value_threshold`; otherwise it is `STANDARD`;
- high-value valid orders therefore remain `READY_FOR_APPROVAL` with
  `ELEVATED` approval;
- `validated_order_data` is present only when there is no `ERROR` issue and all
  trusted promotion preconditions hold; it is `None` for every blocking
  validation failure;
- no result contains provider response data, a UUID generated by the engine,
  a timestamp generated by the engine, or an external side effect.

### 9.1 Trusted/promotable order data

`ValidatedOrderData` is a separate immutable internal record. It contains only
data safe to promote into the Phase 1 domain:

```text
ValidatedOrderData
├── canonical trusted customer_reference: str
├── po_number: str
├── order_date: date
├── requested_delivery_date: date
├── supported currency: str
└── lines: tuple[ValidatedOrderLine, ...]

ValidatedOrderLine
├── trusted sku: str
├── promotable description: str | None
├── positive quantity: Decimal
├── nonnegative submitted_price: Decimal
└── trusted catalogue_price: Decimal
```

For a promotable line, the SKU, active status, product currency, catalogue
price, inventory availability, quantity, and submitted price have all passed
the applicable deterministic checks. The line description is the trusted
product description when present; otherwise the extracted description is
retained as a non-identity descriptive value. The trusted SKU ensures the
existing `OrderLine` invariant even when the extracted description is absent.

The record has no line UUID. The application allocates line UUIDs while
promoting the validated record into an immutable `Order` snapshot. The engine
never creates identity values.

### 9.2 Narrow promotion operation

Phase 5 introduces one narrow domain operation conceptually named
`Order.promote_validated_data(...)`. It returns a new immutable `Order` snapshot
with the canonical customer reference, PO, dates, currency, and newly built
trusted `OrderLine` tuple. It preserves the existing order ID, source-document
tuple, and current state; it does not perform a state transition.

The operation is legal only for an order currently in `EXTRACTED`, accepts
only a complete `ValidatedOrderData` plus application-assigned line IDs, and
re-validates the resulting Phase 1 `Order`/`OrderLine` invariants. It replaces
the complete trusted business-data graph as one domain operation rather than
allowing arbitrary field mutation. It cannot accept a `ValidationResult` with
`validated_order_data=None`, invalid quantities, missing trusted prices, or
untrusted customer/product identity.

The application calls this operation only on the valid path, then calls the
existing `transition_to` operation for `EXTRACTED → VALIDATED` and
`VALIDATED → READY_FOR_APPROVAL`. The review path never invokes the promotion
operation and never copies invalid extracted values into trusted order lines.

## 10. Stable rule matrix

All rules in this Phase 5 matrix emit `ValidationIssue` records. `ERROR` is
blocking; `WARNING` is non-blocking. The final route is always derived from
severity, not from a second hard-coded list.

`expected` and `actual` are JSON-safe deterministic values. Decimal values are
canonical strings, dates are ISO strings, enums are their `.value` strings,
currency collections are lists in policy order, and compound identities use
objects with the fixed keys `customer_reference` and `po_number`. Every
explanation follows the template shown in the matrix and contains no raw
document body, provider payload, or secret.

| Rule code | Severity | Field path | Expected / actual semantics | Deterministic explanation |
| --- | --- | --- | --- | --- |
| `CUSTOMER_REQUIRED` | ERROR | `customer` | Expected `customer_reference or customer_name`; actual `null`. | `Customer reference or customer name is required.` |
| `UNKNOWN_CUSTOMER` | ERROR | `customer_reference` when a reference was supplied, otherwise `customer_name` | Expected one exact trusted customer; actual supplied identity. | `No exact trusted customer matched the supplied identity.` |
| `AMBIGUOUS_CUSTOMER` | ERROR | `customer_reference` when a reference was supplied, otherwise `customer_name` | Expected one exact trusted customer; actual candidate count and identity. | `Multiple exact trusted customers matched the supplied identity.` |
| `INACTIVE_CUSTOMER` | ERROR | `customer_reference` when a reference was supplied, otherwise `customer_name` | Expected an active trusted customer; actual canonical reference. | `The matched customer is inactive.` |
| `PO_NUMBER_REQUIRED` | ERROR | `po_number` | Expected a non-null PO number; actual `null`. | `Purchase-order number is required.` |
| `DUPLICATE_CUSTOMER_PO` | ERROR | `po_number` | Expected no existing exact `{customer_reference, po_number}` pair; actual fixed-key identity object. | `The customer-scoped purchase-order reference already exists.` |
| `DOCUMENT_ALREADY_PROCESSED` | ERROR | `source_sha256` | Expected no earlier processed snapshot for this SHA-256; actual lowercase SHA-256. | `The source document SHA-256 was already processed under another order or source.` |
| `ORDER_DATE_REQUIRED` | ERROR | `order_date` | Expected a date; actual `null`. | `Order date is required.` |
| `DELIVERY_DATE_REQUIRED` | ERROR | `requested_delivery_date` | Expected a requested delivery date; actual `null`. | `Requested delivery date is required.` |
| `ORDER_DATE_IN_FUTURE` | ERROR | `order_date` | Expected `order_date <= evaluation_date`; actual ISO order date and evaluation date. | `Order date is later than the evaluation date.` |
| `DELIVERY_DATE_IN_PAST` | ERROR | `requested_delivery_date` | Expected `requested_delivery_date >= evaluation_date`; actual ISO delivery date and evaluation date. | `Requested delivery date is earlier than the evaluation date.` |
| `DELIVERY_BEFORE_ORDER_DATE` | ERROR | `requested_delivery_date` | Expected `requested_delivery_date >= order_date`; actual fixed-key order and delivery dates. | `Requested delivery date is earlier than the order date.` |
| `CURRENCY_REQUIRED` | ERROR | `currency` | Expected a non-null currency; actual `null`. | `Currency is required.` |
| `UNSUPPORTED_CURRENCY` | ERROR | `currency` | Expected one of the policy currency list; actual supplied currency. A malformed/non-uppercase code is also unsupported. | `Currency is not supported by the explicit validation policy.` |
| `ORDER_LINES_REQUIRED` | ERROR | `lines` | Expected at least one line; actual empty list. | `At least one order line is required.` |
| `SKU_REQUIRED` | ERROR | `lines[i].sku` | Expected a non-null SKU; actual `null`. | `SKU is required for line i.` |
| `UNKNOWN_SKU` | ERROR | `lines[i].sku` | Expected one exact trusted product; actual supplied SKU. | `SKU is not present in trusted product data for line i.` |
| `INACTIVE_SKU` | ERROR | `lines[i].sku` | Expected an active trusted product; actual supplied SKU. | `SKU refers to an inactive trusted product on line i.` |
| `QUANTITY_REQUIRED` | ERROR | `lines[i].quantity` | Expected a non-null quantity; actual `null`. | `Quantity is required for line i.` |
| `QUANTITY_NOT_POSITIVE` | ERROR | `lines[i].quantity` | Expected a quantity greater than zero; actual canonical Decimal quantity. | `Quantity must be greater than zero for line i.` |
| `INVENTORY_UNAVAILABLE` | ERROR | `lines[i].quantity` | Expected known trusted available quantity; actual `null` inventory information. | `Trusted inventory availability is unavailable for line i.` |
| `INSUFFICIENT_INVENTORY` | ERROR | `lines[i].quantity` | Expected requested quantity `<=` trusted available quantity; actual fixed-key requested and available quantities. | `Requested quantity exceeds trusted available inventory for line i.` |
| `SUBMITTED_PRICE_REQUIRED` | ERROR | `lines[i].submitted_price` | Expected a non-null submitted price; actual `null`. | `Submitted price is required for line i.` |
| `SUBMITTED_PRICE_NEGATIVE` | ERROR | `lines[i].submitted_price` | Expected a price greater than or equal to zero; actual canonical Decimal price. | `Submitted price must not be negative for line i.` |
| `CATALOGUE_PRICE_UNAVAILABLE` | ERROR | `lines[i].submitted_price` | Expected a trusted catalogue price; actual `null`. | `Trusted catalogue price is unavailable for line i.` |
| `PRODUCT_CURRENCY_MISMATCH` | ERROR | `lines[i].sku` | Expected trusted product currency equal to the usable order currency; actual fixed-key product/order currencies. | `Product currency does not match order currency for line i.` |
| `PRICE_OUTSIDE_TOLERANCE` | ERROR | `lines[i].submitted_price` | Expected absolute difference no greater than the Decimal tolerance allowance; actual submitted, catalogue, difference, and allowance. | `Submitted price is outside the configured catalogue-price tolerance for line i.` |
| `HIGH_VALUE_APPROVAL_REQUIRED` | WARNING | `order_total` | Expected total below the inclusive high-value threshold for standard approval; actual canonical total and threshold. | `Order total meets the high-value threshold and requires elevated approval.` |

The literal `i` in the matrix is replaced by the zero-based line index. Rule
codes remain exactly stable; field paths remain stable and use the same index.

### 10.1 Dependency and cascade rules

The matrix is evaluated completely but dependent checks use these gates:

- customer-scoped duplicate lookup is used only when PO is present and exactly
  one customer candidate exists; an unknown or ambiguous customer does not
  produce a misleading duplicate issue;
- date comparison rules run only when their referenced dates are present;
- line product rules run only after a line has a non-null SKU and a trusted
  product record; a missing product produces `UNKNOWN_SKU` and no inventory,
  catalogue, currency, or tolerance comparison;
- inventory comparison runs only when quantity is present and positive;
- catalogue-price availability is reported for a known product regardless of
  submitted-price presence; tolerance comparison requires a nonnegative
  submitted price and a catalogue price;
- product-currency mismatch requires a present, supported, structurally valid
  order currency; a missing/unsupported order currency is already blocking and
  prevents a misleading cross-currency comparison;
- price tolerance comparison is skipped when product and order currencies do
  not match;
- high-value classification runs after the line checks and adds a warning only
  when a complete nonnegative submitted total is computable.

## 11. Price validation semantics

All price arithmetic uses `Decimal`; float arithmetic and currency-scale
rounding are forbidden.

For a line with a nonnegative submitted price and a trusted catalogue price:

```text
absolute_difference = abs(submitted_price - catalogue_price)
allowed_difference = abs(catalogue_price) * price_tolerance_fraction
```

The line passes when:

```text
absolute_difference <= allowed_difference
```

When `catalogue_price == 0`, the submitted price must equal exactly zero.
There is no currency-scale quantization, rounding mode, or minor-unit policy
in Phase 5. A negative submitted price is reported by
`SUBMITTED_PRICE_NEGATIVE` and is never compared for tolerance.

## 12. Inventory semantics

Trusted product data distinguishes:

- a known available quantity represented by a finite nonnegative `Decimal`,
  including exact zero;
- unavailable or unknown inventory represented by `None`.

For a known product and a positive requested quantity:

- `available_quantity is None` produces `INVENTORY_UNAVAILABLE`;
- `requested_quantity > available_quantity` produces
  `INSUFFICIENT_INVENTORY`;
- `requested_quantity <= available_quantity` passes the inventory check.

Phase 5 performs no stock reservation, decrement, or other inventory
mutation. Inventory is read-only trusted reference data.

## 13. Date semantics

All date-sensitive decisions use `ValidationContext.evaluation_date`:

```text
order_date is None
    → ORDER_DATE_REQUIRED

requested_delivery_date is None
    → DELIVERY_DATE_REQUIRED

order_date > evaluation_date
    → ORDER_DATE_IN_FUTURE

requested_delivery_date < evaluation_date
    → DELIVERY_DATE_IN_PAST

requested_delivery_date < order_date
    → DELIVERY_BEFORE_ORDER_DATE
```

Missing dates do not produce comparison issues. No timezone logic is required;
Phase 4 drafts use `date`, not `datetime`.

## 14. Duplicate semantics

### 14.1 Customer-scoped PO identity

Duplicate PO identity is exactly:

```text
canonical_customer_reference + po_number
```

It is not `po_number` globally. The duplicate lookup compares the exact
canonical trusted customer reference and exact PO string, excludes the current
order, and treats any existing persisted order reference as a duplicate. No
case-folding or fuzzy normalization is applied to PO numbers.

The current order cannot be a duplicate of itself. The provider or repository
must obtain the canonical customer reference before performing this lookup.

### 14.2 Source SHA-256 identity

Document duplicate identity is the lowercase source SHA-256.

Two cases are distinct:

1. **same order/source already has a snapshot:** application-level replay or
   conflict; do not create a second immutable snapshot and do not manufacture a
   validation issue;
2. **same SHA-256 is processed under another order/source:** the engine receives
   `document_already_processed=True` and emits
   `DOCUMENT_ALREADY_PROCESSED`.

Phase 5 does not implement Phase 10's general idempotency or concurrency
framework. It uses the snapshot uniqueness constraint and the final order-row
lock needed for this validation transaction only.

## 15. Promotion and routing behavior

### 15.1 `NEEDS_REVIEW`

When the result contains any `ERROR`:

- persist the immutable extraction snapshot;
- replace the current `validation_issues` rows with the result issue tuple,
  preserving issue order;
- do not copy invalid extracted customer, PO, date, currency, or line values
  into trusted `Order`/`OrderLine` fields;
- preserve the original source document and order ID;
- transition `EXTRACTED → VALIDATED → NEEDS_REVIEW` using the existing domain
  operations.

Phase 6 will later display and correct the extraction snapshot. Phase 5 does
not edit it.

### 15.2 `READY_FOR_APPROVAL`

When there are no `ERROR` issues:

- persist the immutable extraction snapshot;
- replace `validation_issues` with any `INFO`/`WARNING` tuple, including the
  high-value warning when applicable;
- promote the canonical trusted customer reference, trusted product/SKU data,
  positive quantities, submitted prices, supported currency, and trusted
  catalogue prices;
- create trusted `OrderLine` records that satisfy the existing positive-
  quantity and nonnegative-price invariants;
- preserve the original source document and order ID;
- transition `EXTRACTED → VALIDATED → READY_FOR_APPROVAL`;
- preserve `ApprovalLevel.ELEVATED` in the application result/context when the
  high-value warning applies. No new order state represents elevation.

The application never treats `HIGH_VALUE_APPROVAL_REQUIRED` as a validation
failure. Approval itself remains a later explicit domain action.

## 16. Application orchestration

The Phase 5 application service owns orchestration and side effects. It accepts
an already-produced `ExtractionDraft`; it does not invoke Phase 4 or any LLM.
Its internal contract includes the order ID, source-document ID, draft,
explicit policy, explicit validation context, a `BusinessDataProvider`, and an
application-supplied timezone-aware `recorded_at` value for persistence/audit
timestamps.

The service sequence is:

1. read the order and source document;
2. verify the source document belongs to the order and the draft source hash
   and type exactly match the persisted source identity;
3. verify the order is eligible for validation in `EXTRACTED`;
4. check the existing snapshot uniqueness boundary and classify replay versus
   conflict without inserting a second row;
5. obtain `TrustedBusinessData` from the provider before the final write
   transaction; no provider call holds the final mutation transaction open;
6. call the synchronous `ValidationEngine` with the draft, trusted data, policy,
   and context;
7. open the final database write transaction;
8. re-read and lock the order row with `SELECT ... FOR UPDATE` or the
   SQLAlchemy equivalent, verify it is still `EXTRACTED`, and re-verify source
   ownership and snapshot replay/conflict conditions;
9. insert the immutable snapshot;
10. replace the current validation issues in the deterministic result order;
11. on the ready path only, call the narrow domain promotion operation, persist
    the trusted order columns and replace the ordered `order_lines` graph;
12. apply the legal `EXTRACTED → VALIDATED` and final route transition;
13. persist the deterministic audit events;
14. commit once, returning the validation outcome only after the commit
    succeeds.

The final transaction atomically includes the snapshot, current issues,
promoted trusted data when allowed, state transitions, and audit events. Any
database, integrity, state, mapping, or audit failure rolls back the complete
set. Provider failure occurs before this final transaction and is reported as
an application/infrastructure failure, not as a fake business issue.

The service must not blindly overwrite an order that changed state between its
initial read and final write. The row lock and state re-check reject that race.
Phase 10 owns broader idempotency and concurrency hardening.

## 17. Persistence design

### 17.1 Existing persistence extensions

The existing `OrderModel`, `OrderLineModel`, `SourceDocumentModel`,
`ValidationIssueModel`, and `AuditEventModel` remain the current relational
records. Phase 5 extends the existing persistence module with one
`ExtractionSnapshotModel`, its mapper, and focused repository functions. It
does not introduce a generic repository base, Unit of Work abstraction,
service locator, or validation-run subsystem.

Expected functions are narrow and transaction-owned by the caller:

- insert/read one extraction snapshot;
- find an existing snapshot by `(order_id, source_document_id)`;
- find an existing customer-scoped `(customer_reference, po_number)` pair,
  excluding a supplied current order ID;
- find a processed extraction snapshot by source SHA-256, excluding the current
  order/source identity;
- replace current validation issues for one order in supplied tuple order;
- lock/read an order for final validation mutation;
- replace the trusted order business graph from a validated immutable `Order`
  snapshot and preserve ordered child positions;
- persist the state and audit records without committing independently.

No repository function commits on behalf of the application service. The
existing order graph remains the source of truth for trusted business state;
the snapshot is a separate untrusted provenance record.

### 17.2 Snapshot mapping

The mapper performs a checked round trip:

- `ExtractionDraft` → canonical JSON-safe payload;
- payload → `ExtractionDraft`, with strict field presence, Decimal/date
  conversion, source identity, line order, evidence order, and explicit-null
  checks;
- relational envelope → a typed persisted-snapshot record containing the
  snapshot ID, order ID, source-document ID, source identity, draft, and
  `created_at`.

The mapper rejects payloads with missing keys, extra keys, wrong scalar types,
non-canonical date/Decimal values, reordered or malformed arrays, mismatched
source identity, provider/raw-response fields, or mutable domain collections.
It does not reconstruct `OrderLine` from an extraction snapshot; doing so would
wrongly apply Phase 1 invariants to untrusted data.

### 17.3 Validation issue replacement

`ValidationIssueModel` remains the current issue table, keyed by
`(order_id, position)`. The replacement operation deletes the existing rows,
flushes, inserts the new tuple at positions `0..n-1`, and remains inside the
caller-owned final transaction. It does not preserve prior validation runs as
history. The immutable extraction snapshot and audit events provide the Phase 5
provenance needed by the current requirements.

## 18. Atomicity and locking

The final write transaction is the single atomic boundary for:

- extraction snapshot insertion;
- validation-issue replacement;
- trusted order and order-line promotion when allowed;
- `EXTRACTED → VALIDATED → route` transitions;
- `EXTRACTION_SNAPSHOT_RECORDED`, `ORDER_VALIDATED`, and route audit events.

The service locks the order before any mutation and confirms the order is still
`EXTRACTED`. A state mismatch, source ownership mismatch, snapshot replay, or
unique conflict aborts the transaction. A valid provider result computed before
the lock cannot overwrite a later state change.

There is no distributed lock, queue, retry framework, event-sourcing log, or
general idempotency coordinator in Phase 5. The database uniqueness boundary
and one order-row lock are the minimum controls needed for this milestone.

## 19. Audit events

The application records these event types, with actor `system`:

| Event type | When | Exact safe description |
| --- | --- | --- |
| `EXTRACTION_SNAPSHOT_RECORDED` | Snapshot inserted in the final transaction. | `Immutable extraction snapshot recorded for the order source document.` |
| `ORDER_VALIDATED` | `EXTRACTED → VALIDATED` succeeds. | `Deterministic validation completed.` |
| `ORDER_NEEDS_REVIEW` | Final route is `NEEDS_REVIEW`. | `Deterministic validation found one or more blocking issues; human review is required.` |
| `ORDER_READY_FOR_APPROVAL` | Final route is `READY_FOR_APPROVAL`. | `Deterministic validation passed; order is ready for approval.` |

For an elevated result, the final description is instead:

```text
Deterministic validation passed; elevated approval is required.
```

The application supplies the event timestamp. To preserve insertion order
when all events share one operation, it derives successive event timestamps as
`recorded_at`, `recorded_at + 1 microsecond`, and `recorded_at + 2
microseconds`; it never calls the system clock from the engine. Event IDs are
application-generated. Audit descriptions contain no raw document text,
provider content, API key, or customer-sensitive payload.

## 20. API, UI, and orchestration boundaries

Phase 5 introduces no new public HTTP endpoint unless an already-existing
consumer proves one strictly necessary during implementation. The default
design has no new API surface.

Phase 5 includes none of the following:

- UI or review actions;
- Phase 6 human edits, approval, rejection, or correction actions;
- n8n workflow changes;
- email, Slack, Gmail, Odoo, HubSpot, or ERP/CRM writes;
- stock reservation;
- external approval action;
- public validation endpoint;
- provider-dependent routing.

The application service is an internal Python boundary. If a later existing
consumer requires exposure, that separate design must preserve the same
deterministic service contract and must not move rules into HTTP, n8n, or an
LLM prompt.

## 21. Error handling

Phase 5 separates normal business outcomes from operational failures.

### 21.1 Validation outcomes

Expected business conditions are represented only by immutable
`ValidationIssue` records and the derived `ValidationResult` route. Unknown
customers, invalid quantities, unsupported currencies, insufficient inventory,
duplicate identity, and price violations are not raised as infrastructure
exceptions.

### 21.2 Application and infrastructure errors

The application error surface includes safe categories for:

- missing order;
- missing source document;
- source-document ownership mismatch;
- source SHA-256 or document-type mismatch;
- order not in `EXTRACTED`;
- snapshot replay or snapshot conflict;
- invalid trusted-data provider contract;
- trusted-data provider operational failure;
- database constraint, transaction, or persistence failure.

These are not converted into fake `ValidationIssue` records. Provider
exceptions are translated to safe messages without raw exception text,
credentials, source content, or provider payloads. HTTP status mapping is not
part of this milestone.

## 22. Determinism contract

Equal values for:

```text
ExtractionDraft
+ TrustedBusinessData
+ ValidationPolicy
+ ValidationContext
```

produce equal `ValidationResult` values. Equality includes:

- issue count, issue order, rule codes, severities, field paths,
  expected/actual representations, and explanations;
- route;
- approval level;
- order total;
- validated/promotable data;
- trusted line order and evidence-independent values.

The engine does not use UUIDs, timestamps, current date/time, random values,
environment variables, network responses, database ordering, or provider
objects. Repository reads establish deterministic order explicitly: source and
line positions, issue positions, and audit timestamps/IDs are never left to
unspecified database order.

## 23. Tests required by the design

M5A creates no tests. The later implementation milestones must add the
following focused coverage without weakening existing assertions or invoking
live external systems.

### 23.1 Pure engine tests

The unit suite under `tests/unit/validation/` must cover:

- missing, unknown, ambiguous, and inactive customer;
- authoritative customer-reference lookup and normalized exact-name fallback;
- missing and duplicate PO;
- duplicate source SHA-256;
- missing, future, past, and out-of-order dates;
- missing and unsupported currency;
- no lines;
- missing, unknown, and inactive SKU;
- missing, zero, negative, and non-positive quantity behavior;
- missing inventory and insufficient inventory, including known zero stock;
- missing and negative submitted price;
- missing catalogue price;
- product/order currency mismatch;
- price tolerance strictly inside, exactly on, and outside the boundary;
- zero catalogue price with zero and nonzero submitted price;
- high-value totals just below and exactly at the inclusive threshold;
- standard versus elevated approval level;
- multiple simultaneous violations;
- deterministic issue ordering and stable field paths;
- repeated equal input producing an equal `ValidationResult`;
- no I/O imports or boundaries: no FastAPI, SQLAlchemy, asyncpg, Alembic,
  network client, provider SDK, clock, environment read, random call, or UUID
  generation from the engine.

The unit tests must also assert that blocking results have
`validated_order_data is None`, while a warning-only high-value result remains
`READY_FOR_APPROVAL` with `ELEVATED` approval.

### 23.2 Sandbox adapter tests

The sandbox suite must cover:

- exact customer-reference lookup;
- normalized exact customer-name lookup;
- ambiguous duplicate names;
- inactive customer records;
- exact SKU lookup and unknown SKU;
- rejected duplicate exact customer references and duplicate exact SKUs;
- deterministic snapshot values and ordering for repeated equal requests;
- known-zero versus missing inventory;
- duplicate customer+PO lookup;
- processed source-hash lookup;
- no network access, credentials, environment dependence, or external writes.

### 23.3 Persistence tests

PostgreSQL-backed persistence tests must cover:

- migration `0003_phase5_extraction_snapshots` from the Phase 2 head;
- extraction snapshot round trip;
- Decimal canonical strings, ISO dates, explicit nulls, source identity, and
  ordered lines/evidence;
- unique `(order_id, source_document_id)` behavior;
- composite source-document ownership foreign key;
- source snapshot cascade behavior consistent with the order graph;
- immutable snapshot application semantics and no update/delete repository
  operation;
- customer-scoped duplicate PO lookup excluding the current order;
- processed source-SHA lookup excluding the current order/source;
- current validation-issue replacement and stable positions;
- order-graph replacement with trusted catalogue prices and Phase 1-valid
  `OrderLine` rows;
- database rejection of invalid snapshot source identity/type/hash/payload
  envelope values where expressed by relational constraints.

### 23.4 Application integration tests

The application integration suite must cover:

- required `EXTRACTED` precondition;
- valid `EXTRACTED → VALIDATED → READY_FOR_APPROVAL`;
- invalid `EXTRACTED → VALIDATED → NEEDS_REVIEW`;
- invalid extracted values never reaching trusted `order_lines`;
- trusted customer/product values and catalogue prices being promoted only on
  the ready path;
- source snapshot, current issues, audits, order graph, and state being
  persisted atomically;
- rollback of the entire operation when any final write fails;
- state-race or incorrect-state rejection after the preflight read;
- same order/source replay and conflict without a second snapshot;
- duplicate SHA under another order producing `DOCUMENT_ALREADY_PROCESSED`;
- high-value valid order remaining `READY_FOR_APPROVAL` with `ELEVATED`;
- no LLM or provider-SDK invocation: the service receives a draft and uses only
  the intended trusted-business-data contract; the sandbox itself makes no
  network request;
- no network requirement and no live Gemini, Odoo, CRM, email, Slack, or n8n
  interaction.

### 23.5 Regression, CI, and cost tests

All Phase 0–4 tests must continue passing. CI must provide:

- PostgreSQL-backed migration and integration coverage;
- no live Gemini call or external API call;
- no ERP order, CRM mutation, email, Slack message, or stock mutation;
- a mandatory test path costing `$0`;
- the existing Ruff, format, mypy, build, frontend, and secret-scan gates.

## 24. Expected package shape

The implementation may introduce only the small package shape required by this
contract:

```text
src/opsflow/validation/
    __init__.py
    models.py
    policy.py
    business_data.py
    sandbox.py
    engine.py

src/opsflow/application/
    validation.py

existing persistence:
    models.py
    mappers.py
    repositories.py

alembic/versions/
    0003_phase5_extraction_snapshots.py

tests/unit/validation/
tests/unit/application/
tests/unit/persistence/
tests/integration/
```

This is a design expectation, not permission to create empty modules during
M5A. The implementation must not add a class-per-rule plugin architecture, DSL,
rules-framework dependency, event sourcing, generic Unit of Work, service
locator, service registry, plugin framework, caching layer, or generic
integration framework.

## 25. Phase 5 milestone structure

The Phase 5 milestones are locked as follows. Only M5A is in the current
design scope; the remaining entries record boundaries, not implementation
plans.

| Milestone | Boundary |
| --- | --- |
| **M5A — Deterministic Validation Contract & Design** | This authoritative design, explicit trust/promotion boundary, persistence contract, test contract, self-review, documentation-safe verification, and design-review gate. No production implementation. |
| **M5B — Trusted Business Data, Policy & Rule Engine** | Implement the provider-neutral trusted-data records, sandbox provider, explicit policy/context, pure engine, and focused unit behavior defined by this contract. |
| **M5C — Extraction Snapshot Persistence** | Implement migration `0003`, snapshot JSONB mapping, immutable snapshot repository operations, source ownership, and persistence tests defined by this contract. |
| **M5D — Validation Application Service & Atomic Routing** | Implement preflight/provider orchestration, final locking, atomic snapshot/issues/promotion/state/audit writes, and application integration behavior defined by this contract. |
| **M5E — Rule Matrix, Integration & Adversarial Hardening** | Complete matrix-wide, cross-boundary, rollback, replay/conflict, race, deterministic-order, security, and regression verification without adding future-phase scope. |
| **M5F — Independent Phase 5 Audit & Closeout** | Fresh independent audit, justified remediation if required, exact-head CI evidence, durable audit record, and truthful Phase 5 status closeout. |

No M5B–M5F implementation plan is created by M5A.

## 26. Explicit non-goals

Phase 5 does not include:

- fuzzy, semantic, embedding, or AI matching;
- a second LLM call or validation LLM;
- confidence scoring or calibrated confidence claims;
- raw Gemini/OpenAI response persistence;
- prompt text, API keys, provider SDK objects, or provider internals in
  persistence;
- validation-run-history event sourcing or a validation-attempt subsystem;
- Odoo, HubSpot, Gmail, Slack, n8n, or any external integration;
- external writes, ERP/CRM writes, email, Slack notifications, or stock
  reservation;
- UI or Phase 6 human edits, review actions, approval actions, rejection
  actions, or correction persistence;
- a new public validation endpoint by default;
- a new workflow/orchestration tool;
- Phase 7 n8n behavior;
- Phase 9 integration behavior;
- Phase 10 general reliability, distributed idempotency, or concurrency
  framework;
- Phase 11 evaluation framework;
- speculative plugin architecture, class-per-rule design, DSL, or generic
  rules engine;
- weakening any Phase 1 `Order` or `OrderLine` invariant;
- new `OrderState` values or alternate state transitions;
- any production implementation, migration, dependency, test, or plan in
  M5A.

## 27. M5A acceptance and design-review gate

M5A is complete only when this document is committed on the designated branch
and independently reviewable. Acceptance requires:

- the AI/deterministic authority boundary and approved flow are explicit;
- `ExtractionDraft` is durably snapshotted separately from trusted order data;
- source SHA-256, document type, and ownership checks are exact;
- snapshot payload serialization is deterministic, typed, ordered, and free of
  raw provider material;
- replay/conflict and duplicate-source semantics are distinct;
- the engine contract is pure, synchronous, deterministic, and clock/I/O-free;
- trusted customer, product, inventory, catalogue, duplicate, and processed
  hash data have a narrow provider-neutral contract;
- matching, policy, context, result, promotion, price, inventory, date,
  duplicate, severity, and routing semantics are explicit;
- the stable rule matrix covers every required rule code and deterministic
  explanation/field-path behavior;
- invalid values cannot be promoted into trusted order lines;
- high-value valid orders remain ready with elevated approval;
- the application transaction, lock, rollback, and audit boundaries are
  explicit;
- no API/UI/n8n/external integration/future-phase behavior is accidentally
  included;
- the required unit, persistence, integration, regression, and CI tests are
  specified without creating them in M5A;
- the document contains no unresolved design markers;
- only the requested design file is changed.

Before M5B begins, this design must receive independent review and user
approval. M5A ends at that design/review gate.
