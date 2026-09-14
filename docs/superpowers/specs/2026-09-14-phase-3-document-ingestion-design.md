# Phase 3 Document Ingestion & Canonical Parsing Design

## Document control

- **Repository:** `Joseph-Nawar/OpsFlow_AI`
- **Phase:** Phase 3 — Document Ingestion
- **Baseline SHA:** `a051510ed4bdb5532b878c6544bdf30309df14e7`
- **Current milestone:** M3A — Canonical Ingestion Contract
- **Design status:** Authoritative design in progress; implementation plan and production behavior are not yet authorized
- **Branch:** `phase/3-document-ingestion`
- **Design date:** 2026-09-14

### Governing sources

This design is governed by the active Phase 3 brief and the repository’s
durable architecture and workflow references:

1. [Project roadmap](../../roadmap/project-roadmap.md)
2. [System overview](../../architecture/system-overview.md)
3. [Phase 1 domain model](../../architecture/domain-model.md)
4. [Development guide](../../development/development-guide.md)
5. [Phase 2 independent audit](../../audits/phase-2-audit.md)

The Phase 1 `SourceDocumentType` and `SourceDocument` contracts remain the
authoritative domain boundary. This document defines the separate parsed
document representation used inside Phase 3.

## 1. Objective and authority boundary

Phase 3 converts supported incoming documents into a deterministic canonical
representation **before any AI processing**.

The key question for this phase is:

> What does this source document deterministically contain?

Phase 4 will later answer: “What order fields can AI extract from that
canonical content?” Phase 5 will later answer: “Is the extracted order valid
according to trusted business rules?”

### Supported V1 inputs

Phase 3 supports exactly these `SourceDocumentType` values:

- `EMAIL_BODY` — UTF-8 body/plain text;
- `PDF`;
- `XLSX`;
- `CSV`.

The existing Phase 1 `FORM` value is intentionally unsupported by the Phase 3
parser. The Phase 1 `SourceDocument` record remains unchanged.

### Phase 3 performs no downstream interpretation or side effect

Phase 3 performs no:

- LLM call or AI extraction;
- business validation or policy decision;
- order approval or routing;
- database persistence or parsed-document persistence;
- order mutation or state-machine orchestration;
- raw-file persistence or object storage;
- HTTP upload API, API route, or multipart contract;
- n8n workflow or external integration;
- network access or paid service call.

The output describes document content and parsing warnings. It does not claim
that a document is a purchase order, valid order, duplicate, approved, or
safe to execute.

## 2. Architecture choice: internal Python subsystem only

Phase 3 is an **internal Python subsystem**. Its first public boundary is a
synchronous in-process function, not an HTTP upload/parsing endpoint.

Phase 3 must not add an HTTP upload/parsing endpoint, attach uploaded raw files
to orders, introduce raw-file persistence/object storage, or change the Phase 2
`/v1/orders` contract. A storage or HTTP boundary now would prematurely force
decisions about multipart contracts, raw-file lifecycle, document attachment
mutation, and orchestration before later phases need those decisions.

The expected production structure is:

```text
src/opsflow/documents/__init__.py
src/opsflow/documents/models.py
src/opsflow/documents/errors.py
src/opsflow/documents/limits.py
src/opsflow/documents/processor.py
src/opsflow/documents/text.py
src/opsflow/documents/csv.py
src/opsflow/documents/xlsx.py
src/opsflow/documents/pdf.py
```

These are expected implementation paths for later milestones, not permission
to create them during M3A. Empty package files are not required unless the
implementation needs them.

The architecture remains deliberately small:

- small immutable typed data records;
- format-specific parsing functions;
- one public dispatcher;
- no abstract parser class;
- no parser registry or plugin system;
- no dependency-injection framework;
- no generic ingestion framework.

## 3. Public processing contract

The subsystem exposes one synchronous internal entry point conceptually
equivalent to:

```python
process_document(
    document: DocumentInput,
    limits: DocumentLimits = DEFAULT_DOCUMENT_LIMITS,
) -> CanonicalDocument
```

Processing is local deterministic parsing. It has no network operation, no
Phase 3 external service, and no need to introduce asynchronous complexity
merely because FastAPI exists elsewhere. Phase 4 or later application
orchestration may invoke this function as appropriate.

## 4. Input contract

`DocumentInput` is an immutable Phase 3 input record containing:

| Field | Type | Meaning |
| --- | --- | --- |
| `document_type` | `SourceDocumentType` | The caller-declared supported source kind. |
| `name` | `str` | Human-readable source name; not authoritative for type detection. |
| `mime_type` | `str` | The caller-declared media type, optionally with valid parameters. |
| `content` | `bytes` | Exact incoming payload bytes. |
| `source_reference` | `str \| None` | Safe provenance/reference value, if available. |
| `metadata` | `tuple[tuple[str, str], ...]` | Ordered immutable metadata, including duplicate keys when supplied. |

Phase 3 reuses `SourceDocumentType` from
[`src/opsflow/domain/records.py`](../../../src/opsflow/domain/records.py); it
does not invent a second document-type enum. The input record should reject
invalid record types, non-bytes content, blank required strings, and metadata
that is not an ordered tuple of string pairs through the document-specific
error contract.

Only `EMAIL_BODY`, `PDF`, `XLSX`, and `CSV` are dispatchable. `FORM` produces
`UnsupportedDocumentTypeError` before parsing or side effects.

## 5. Canonical output contract

All canonical records are immutable snapshots. Collections are ordered tuples
so repeated processing can compare results directly without exposing mutable
state.

### 5.1 `CanonicalDocument`

The canonical document contains:

| Field | Type | Meaning |
| --- | --- | --- |
| `document_type` | `SourceDocumentType` | The supported source kind that was processed. |
| `name` | `str` | Input name preserved as supplied. |
| `mime_type` | `str` | Normalized base MIME type, without parameters. |
| `sha256` | `str` | Lowercase hexadecimal SHA-256 of exact incoming bytes. |
| `size_bytes` | `int` | Exact incoming payload length in bytes. |
| `source_reference` | `str \| None` | Input source reference preserved. |
| `metadata` | `tuple[tuple[str, str], ...]` | Input metadata in its original order, including duplicates. |
| `text` | `str` | Deterministic normalized or structurally rendered text. |
| `pages` | `tuple[CanonicalPage, ...]` | Ordered page records where page structure exists. |
| `tables` | `tuple[CanonicalTable, ...]` | Ordered table records where table structure exists. |
| `warnings` | `tuple[DocumentWarning, ...]` | Ordered honest parser warnings. |

For text/email and CSV/XLSX, `pages` is empty. For PDF, `tables` is empty.
The structured `pages` and `tables` fields are authoritative for their
respective formats; rendered `text` is a deterministic convenience view.

### 5.2 `CanonicalPage`

```text
number: int
text: str
```

Page numbers are one-based and pages retain source order. A page with no
extractable text remains present with `text=""`.

### 5.3 `CanonicalTable`

```text
name: str
rows: tuple[tuple[str, ...], ...]
```

Rows preserve row order and column order. Empty cells that are structurally
present remain empty strings in their original positions. CSV produces one
table with stable name `CSV`. XLSX produces one table per worksheet in sheet
order, named with the worksheet title.

### 5.4 `DocumentWarning`

```text
code: str
message: str
location: str | None
```

`code` is a stable machine-readable string, `message` is human-readable and
safe to expose to application code, and `location` is an optional stable
parser coordinate such as `page:2` or a worksheet/row location. Warnings are
not exceptions and never authorize a downstream decision.

The currently justified stable codes are:

- `EMPTY_TEXT` — valid plain text is empty or whitespace-only;
- `EMPTY_PDF_PAGE` — a preserved PDF page has no extractable text;
- `NO_EXTRACTABLE_TEXT` — the PDF has no extractable text on any page;
- `EMPTY_SHEET` — a preserved XLSX worksheet contains no non-blank cells.

An implementation may emit a subset when the condition does not arise. It
must not invent warnings for content it did not observe or create a large
general-purpose warning taxonomy.

## 6. Source identity and metadata

SHA-256 is calculated over the exact incoming `DocumentInput.content` bytes
before decoding, normalization, parsing, or structural rendering:

```text
sha256 = SHA-256(document.content).hexdigest()
size_bytes = len(document.content)
```

Consequences:

- identical bytes produce identical hashes;
- text normalization cannot change source identity;
- metadata ordering and duplicate metadata keys do not affect the source hash;
- Phase 3 exposes source identity only.

Phase 3 must not query PostgreSQL for duplicate hashes, decide whether a hash
is a business duplicate, or reject a document merely because an identical hash
exists. Duplicate business policy belongs to later deterministic workflow
logic.

The output preserves `source_reference` and metadata exactly as ordered input
records. No timestamp, random identifier, absolute environment path, or
network result is added.

## 7. Conservative normalization

Normalization preserves source meaning and is intentionally limited to:

- removing a leading UTF-8 BOM where text decoding supports it;
- converting CRLF and CR line endings to LF;
- applying Unicode NFC normalization;
- applying deterministic parser-generated structural rendering.

Normalization must not:

- lowercase content;
- globally trim meaningful source whitespace;
- collapse all whitespace;
- reorder rows, cells, pages, sheets, or metadata;
- deduplicate lines, rows, or metadata keys;
- “correct” source values;
- reinterpret arbitrary prose dates;
- rewrite business numbers.

Whitespace may be inspected only to determine whether text is empty for the
`EMPTY_TEXT` warning. It must not be stripped from the returned content.

## 8. MIME and content validation

Phase 3 does not use `libmagic` or `python-magic`. Validation is deterministic
and combines:

- the declared `SourceDocumentType`;
- the normalized base MIME type;
- content signature/structure and parser validity.

For comparison, normalize a declared MIME value by taking its case-insensitive
base media type and ignoring valid parameters such as `charset=utf-8`.
Filename extensions are not authoritative and are never used to silently
reclassify an input.

The supported mapping is:

| Type | Required normalized base MIME |
| --- | --- |
| `EMAIL_BODY` | `text/plain` |
| `CSV` | `text/csv` |
| `PDF` | `application/pdf` |
| `XLSX` | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

Examples:

- `PDF` plus XLSX bytes fails validation or parsing;
- `XLSX` plus an arbitrary ZIP fails validation or parsing;
- a mismatched filename does not change the declared type;
- a valid MIME parameter does not cause a false mismatch.

The dispatcher validates support and MIME before invoking the format-specific
parser. Format parsers then validate their content signature/container and
fail safely on invalid data.

## 9. Format-specific behavior

### 9.1 Plain text and email body

`EMAIL_BODY` means body/plain text content. It is not RFC-822 `.eml` parsing.

The parser decodes UTF-8, accepting and removing a leading UTF-8 BOM, then
normalizes line endings and Unicode NFC. It does not infer email headers,
attachments, or message structure. It returns `pages=()` and `tables=()`.

Valid empty or whitespace-only text returns an honest canonical result with an
`EMPTY_TEXT` warning. Invalid UTF-8 fails with `DocumentParseError` and does
not produce fabricated replacement text.

### 9.2 CSV

CSV uses Python’s standard-library `csv` module; pandas is not used. The parser
decodes UTF-8/BOM text, retains embedded newlines, and uses a deterministic
strict comma-separated dialect with standard CSV quoting and escaped quotes.
It should read with newline preservation and strict parsing so malformed
quoting fails explicitly.

It preserves row order, column order, cell text, quoting semantics after
parsing, embedded newlines inside cell values, and empty cells. It produces
one `CanonicalTable(name="CSV", ...)`; the table is authoritative.

The canonical human-readable text uses this stable representation, preserving
Unicode:

```text
# CSV
["SKU","Quantity"]
["ABC-1","10"]
```

Each row is a compact JSON string array with `ensure_ascii=false` and stable
separators. The rendering is deterministic and unambiguous for tabs, commas,
quotes, and newlines inside cell values. It is not business interpretation and
does not parse JSON as an input format.

### 9.3 XLSX

The planned runtime dependency is `openpyxl`. Workbook loading uses behavior
equivalent to:

- read-only mode;
- `data_only=False`, so formulas remain formula expressions rather than cached
  results;
- external links disabled/not followed;
- no macro or script execution.

Formulas are source data. The parser never evaluates formulas, macros, scripts,
or external workbook behavior.

The parser preserves sheet order, sheet title, row order, column order, and
structurally relevant empty cells. For each sheet, it determines the highest
worksheet row containing a non-blank value or formula before materializing the
canonical row rectangle. The meaningful worksheet row span is the bounded
worksheet-coordinate range from row 1 through that highest meaningful row;
empty cells inside the selected column range remain empty strings. An
entirely empty sheet produces an empty table and an `EMPTY_SHEET` warning.
Blank scalar cells become `""`.

The row-span guard runs before unbounded row iteration or rectangle
materialization. The parser must use the worksheet's available dimension/row
metadata or a bounded streaming observation to determine the highest
meaningful row. If the span would exceed `max_xlsx_rows_per_sheet`, it raises
`DocumentLimitError` immediately; it must not first expand or materialize an
arbitrarily large sparse rectangle and discover the limit afterward. The guard
applies independently to every worksheet and counts row positions, not merely
rows containing populated cells. A sparse cell at row 5,001 therefore exceeds
the default 5,000-row span even if the workbook contains only one populated
cell.

Canonical scalar conversion is:

- string → normalized string with source whitespace preserved;
- blank/`None` → `""`;
- boolean → stable lowercase text `true` or `false`;
- date, datetime, or time → its deterministic ISO representation;
- number → `str(value)` using locale-independent deterministic Python numeric
  text;
- formula → the formula expression as document data.

For `CanonicalDocument.text`, each sheet is rendered in sheet order with a
stable worksheet heading followed by compact JSON row arrays, for example:

```text
# Sheet: "Orders"
["SKU","Quantity"]
["ABC-1","10"]
```

Worksheet titles are represented as JSON strings in headings so unusual title
characters cannot make the rendering ambiguous. Structured tables remain the
authoritative workbook representation.

The parser does not preserve or interpret fonts, colors, charts, images,
macros, pivot semantics, or executable behavior.

#### XLSX container validation

XLSX is a ZIP-based format. Before `openpyxl` parsing, the parser:

1. validates the ZIP container;
2. inspects members without extracting uploaded content through shell tools;
3. requires basic package members including `[Content_Types].xml` and
   workbook content such as `xl/workbook.xml`;
4. rejects configured aggregate uncompressed member-size violations;
5. rejects macro-bearing package content rather than executing or preserving
   it.

Corrupt archives, arbitrary ZIP files, invalid package structure, and unreadable
workbooks fail with safe document-specific errors. External-link parts are not
followed or executed.

### 9.4 PDF

The planned runtime dependency is `pypdf`. The parser validates the PDF
signature/container before or during parsing and extracts text page by page.
It preserves:

```text
CanonicalPage(number=1, text=...)
CanonicalPage(number=2, text=...)
```

Page numbers are one-based and source order is retained. Each extracted page
text receives the conservative text normalization rules. Combined canonical
`text` joins normalized page text in page order with a deterministic blank-line
separator; `pages` remains authoritative for boundaries.

If a page has no extractable text, the page remains in `pages` and the parser
emits `EMPTY_PDF_PAGE` with a stable page location where useful. If every page
has no extractable text, it additionally emits `NO_EXTRACTABLE_TEXT` and
returns an honest empty combined text value. It never fabricates text.

There is no OCR in Phase 3. Encrypted, unreadable, malformed, and corrupt PDFs
fail safely as document-processing errors according to the error contract.

## 10. OCR policy

OCR is explicitly deferred. Phase 3 does not add Tesseract, OCRmyPDF, image
rendering stacks, vision APIs, AI OCR, or cloud OCR.

The Phase 3 behavior for an image/scanned PDF is:

```text
valid PDF structure
        -> no extracted text
        -> explicit warning(s)
        -> no fabricated output
```

Only a future measured requirement based on scanned fixtures may justify a
separate OCR decision. That decision is outside M3A.

## 11. Limits and failure behavior

`DocumentLimits` is one immutable typed record. Its fields are conceptually
`max_input_bytes`, `max_text_characters`, `max_pdf_pages`,
`max_xlsx_sheets`, `max_xlsx_rows_per_sheet`, `max_xlsx_populated_cells`,
`max_csv_rows`, `max_table_columns`, and `max_xlsx_expanded_bytes`. The default
`DEFAULT_DOCUMENT_LIMITS` sets `max_xlsx_rows_per_sheet = 5,000` and contains
these portfolio-sized V1 safety defaults:

| Limit | Default |
| --- | ---: |
| Input payload | 10 MiB |
| Canonical text | 1,000,000 characters |
| PDF pages | 50 |
| XLSX sheets | 20 |
| XLSX rows per sheet | 5,000 |
| XLSX populated cells | 20,000 total |
| CSV rows | 5,000 |
| Table row width | 100 columns |
| XLSX aggregate expanded ZIP content | 50 MiB |

These are demonstrable safety defaults, not universal enterprise limits.
Tests may inject much smaller limits. The processor checks input size before
format parsing and checks canonical text size after deterministic rendering.
Format-specific checks apply page, sheet, XLSX row-span, populated-cell, CSV
row, row-width, and expanded-ZIP limits before returning a canonical result.
The 5,000-row-per-sheet guard complements, rather than replaces, the separate
20-sheet, 20,000-populated-cell-total, 100-column, and 50 MiB expanded-XLSX
limits; they protect different resource dimensions.

When any configured limit is exceeded, processing fails explicitly with
`DocumentLimitError`. It never silently truncates text, pages, sheets, rows,
cells, row spans, or ZIP content. Phase 4 must never mistakenly believe it saw
the complete document.

## 12. Error contract

Use a small document-specific exception hierarchy:

```text
DocumentProcessingError
├── UnsupportedDocumentTypeError
├── DocumentValidationError
├── DocumentLimitError
└── DocumentParseError
```

The hierarchy is internal-library level and not a global HTTP error framework.
Errors expose safe diagnostic information useful to application code and tests
without including raw document bodies or sensitive content.

Use the focused subclasses for these cases:

- unsupported `FORM` or any unsupported source type →
  `UnsupportedDocumentTypeError`;
- invalid input record, MIME mismatch, or invalid container declaration →
  `DocumentValidationError`;
- payload, canonical-text, page, sheet, cell, row, width, or expanded-ZIP
  limit → `DocumentLimitError`;
- invalid UTF-8, malformed CSV, corrupt/unreadable PDF, corrupt workbook, or
  invalid XLSX archive/package → `DocumentParseError`.

Warnings are truthful result data, not exceptions. Corruption, mismatch,
unsupported type, and excessive size are failures, not warnings.

## 13. Determinism contract

For a fixed byte payload, document type, MIME, metadata, limits, and dependency
versions, repeated processing must return equal canonical results.

Stable ordering is required for:

- pages and page numbers;
- tables and worksheets;
- rows and columns;
- metadata, including duplicate keys;
- warnings.

`CanonicalDocument` must contain no current timestamp, random identifier,
environment-specific absolute path, process-specific value, or network result.
Repeated identical bytes must yield the same SHA-256 and same complete
canonical record. A parser may fail consistently; it must not produce a
partially truncated success.

## 14. Fixtures and data posture

Phase 3 justifies the repository fixture area:

```text
fixtures/documents/
```

Fixtures are synthetic only. Likely small committed fixtures are:

- plain text: clean PO-like body and, if useful, UTF-8/BOM text;
- CSV: clean table and quoted/multiline table;
- PDF: single-page text, multi-page text, valid blank/image-style no-text,
  and a malformed/corrupt example where a committed fixture is useful;
- XLSX: clean workbook, multi-sheet workbook, formula-containing workbook,
  and a malformed/corrupt workbook where useful.

All binary fixtures remain ordinary small repository-committable files. Do not
use customer/private documents or download random public documents into the
repository. Do not commit giant files to test limits; use injected small
limits or generated temporary test data.

M3A does not create fixtures. Later implementation milestones create only the
fixtures required by their tests.

## 15. Dependency contract

M3A adds no dependencies and changes neither `pyproject.toml` nor `uv.lock`.

Later Phase 3 implementation is expected to justify only these runtime
dependencies:

- `pypdf` for PDF parsing;
- `openpyxl` for XLSX parsing.

Text and CSV use the Python standard library. Phase 3 must not add pandas,
numpy solely for document parsing, `python-magic`/libmagic, OCR packages,
cloud SDKs, AI SDKs, or multipart/FastAPI upload dependencies. If a genuine
implementation need appears, it must be stopped and explicitly justified
before expanding the stack.

## 16. Persistence and API boundary

Phase 3 introduces:

- no database migration;
- no new business table;
- no parsed-document persistence;
- no new API route;
- no modification to the Phase 2 `/v1/orders` contract;
- no raw-file upload or raw document storage strategy;
- no object-storage abstraction;
- no state-machine transition orchestration.

The existing Phase 1 `SourceDocument` remains unchanged. Phase 3 canonical
records may later be mapped or orchestrated by later phases, but the processor
itself remains infrastructure-independent.

## 17. Security posture

Automated Phase 3 processing must:

- never execute formulas, macros, scripts, or document instructions;
- never follow external workbook links;
- never use shell tools on uploaded content;
- never perform network access or call AI;
- reject excessive input payloads and ZIP expansion;
- fail safely on corruption, invalid encoding, and unreadable containers;
- avoid logging raw document bodies or cell contents in exceptions.

Prompt injection inside a document is just text at this boundary. It has zero
authority and cannot affect parsing policy, routing, approval, or execution.

## 18. Testing design

Unit tests are infrastructure-independent and belong under
`tests/unit/documents/` in later implementation milestones. Fixture-backed
parser tests may remain ordinary backend tests and do not require PostgreSQL.

### Common contract tests

Cover deterministic SHA-256, identical bytes producing identical hashes,
`size_bytes`, MIME normalization, MIME mismatch, unsupported `FORM`, payload
and canonical-text limits, repeat-parse equality, preserved metadata order,
preserved duplicate metadata keys, and the absence of timestamp, randomness,
environment paths, AI, database, or network requirements.

### Text tests

Cover UTF-8, BOM, CRLF/CR normalization, NFC normalization, invalid UTF-8,
meaningful whitespace preservation, and the empty-text warning.

### CSV tests

Cover a basic table, quoted delimiters, multiline cells, row and column order,
empty cells, malformed CSV, row and width limits, and deterministic compact
JSON-row rendering.

### XLSX tests

Cover a single sheet, multiple sheets, sheet ordering, row/column ordering,
structurally relevant empty cells, sparse worksheets whose meaningful row span
exceeds an injected small limit, formula preservation as source text,
deterministic dates/datetimes/times and numbers, corrupt workbooks, wrong
ZIP/non-XLSX ZIP, macro-bearing content, sheet/row-span/cell/row-width limits,
expanded-ZIP limits, and the absence of formula evaluation, external-link
following, execution, or network access. The sparse-row case must fail safely
before an arbitrarily large rectangle is materialized; use an injected small
limit rather than a giant committed fixture where practical.

### PDF tests

Cover single-page and multi-page text, page ordering, conservative text
normalization, blank/no-text page preservation and warning, full
no-extractable-text warning, malformed/corrupt PDFs, page limits, and
deterministic repeated extraction.

### Unified processor tests

For every supported format, prove the complete path:

```text
DocumentInput -> validation -> format parser -> CanonicalDocument
```

The focused suite must run without PostgreSQL, Docker, a FastAPI app or API
server, an AI provider, or internet access. It must prove that no LLM provider
is needed and that no parser path performs an external side effect.

## 19. Full-repository regression

Phase 3 implementation must keep all existing Phase 0–2 behavior green. The
full GitHub Backend suite continues to run PostgreSQL because earlier phases
need it. Focused Phase 3 tests remain runnable without PostgreSQL, Docker, an
API server, an AI provider, or internet access.

M3A is documentation-only and therefore does not invent application tests or
claim unimplemented parsing behavior is passing. It verifies documentation,
links, scope, and repository state instead.

## 20. Explicit non-goals

Phase 3 does not include:

- a `/v1/documents` API;
- multipart upload;
- raw-file persistence or object storage;
- database migrations or parsed-content persistence;
- order mutation or state processing;
- duplicate business policy;
- OCR;
- `.eml` parsing;
- DOC/DOCX;
- image formats;
- legacy XLS;
- a generic XML parser;
- macros or executable workbook behavior;
- AI extraction, Gemini, OpenAI, or any other LLM provider;
- prompt design;
- deterministic business validation;
- n8n, Gmail, Slack, or external integrations;
- a review UI;
- authentication work;
- any Phase 4+ functionality.

`FORM` remains a Phase 1 domain value but is not a Phase 3 parser input.

## 21. Phase 3 milestone contract

| Milestone | Approved scope | Status at M3A establishment |
| --- | --- | --- |
| **M3A — Canonical Ingestion Contract** | Design spec; later implementation plan; branch/status establishment; no production behavior. | **IN PROGRESS** |
| **M3B — Canonical Models, Validation & Text/CSV** | Models, errors, limits, hash/MIME validation, text parser, CSV parser. | **NOT STARTED** |
| **M3C — XLSX Parsing** | `openpyxl`, archive validation, structured workbook parsing, fixtures, and tests. | **NOT STARTED** |
| **M3D — PDF Parsing** | `pypdf`, page parsing, no-text warnings, fixtures, and tests. | **NOT STARTED** |
| **M3E — Unified Processor & Robustness** | Dispatcher, all-format fixtures, corruption, mismatch, limits, deterministic regression, and Phase 3 hardening. | **NOT STARTED** |
| **M3F — Independent Phase 3 Audit & Closeout** | Fresh-context/read-only first audit; justified remediation; durable audit; PR; GitHub merge commit; exact-main post-merge CI; branch cleanup. | **NOT STARTED** |

M3A completes only after this design is committed, independently reviewed,
approved by the human, and followed by a separately committed implementation
plan. This document does not authorize M3B and does not contain that plan.

## 22. Phase 3 Definition of Done

Phase 3 is complete when synthetic examples of an email/plain-text body, CSV,
XLSX, and text-based PDF can be passed to the internal processor and produce
the same truthful canonical result deterministically every time.

Returned canonical data includes:

- raw-byte SHA-256 and exact byte size;
- conservative normalized content;
- page structure for PDFs and table structure for CSV/XLSX;
- source metadata and reference;
- honest warnings where content is empty or not extractable.

Unsupported, mismatched, corrupt, invalid, and excessive documents fail safely.
Scanned/no-text PDFs are explicitly reported without fabricated text.

The focused Phase 3 path requires no LLM, paid service, PostgreSQL, HTTP
upload route, or external network call.

M3A itself is complete only at the separate design-review, human-approval, and
implementation-plan gate described above. Until then, Phase 3 remains
`IN PROGRESS` and M3A remains `IN PROGRESS`.
