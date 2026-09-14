# Phase 3 Document Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` to implement this plan task-by-task.
> Steps use checkbox (`- [ ]`) syntax for tracking. Repository policy
> requires single-agent sequential execution; subagents, parallel agents, and
> spawned reviewers are forbidden unless the human explicitly authorizes them.

**Goal:** Build an infrastructure-independent deterministic document-processing
subsystem for email/plain text, CSV, XLSX, and PDF that produces canonical
content for later AI extraction.

**Architecture:** Small immutable document records plus format-specific
function modules behind one synchronous dispatcher. Text/CSV use the standard
library; XLSX uses openpyxl; PDF uses pypdf. No HTTP, persistence, AI, OCR,
or order mutation.

**Tech Stack:** Python 3.12, stdlib csv/hashlib/json/unicodedata/zipfile,
openpyxl, pypdf, pytest, Ruff, mypy.

**Spec:**
`docs/superpowers/specs/2026-09-14-phase-3-document-ingestion-design.md`

**Repository:** `Joseph-Nawar/OpsFlow_AI`

**Phase:** Phase 3 — Document Ingestion

**Current milestone:** M3A — Canonical Ingestion Contract

**Design status:** Human-approved committed Phase 3 design; this plan is
pending independent review.

**Governing sources:** `AGENTS.md`, `README.md`,
`docs/roadmap/project-roadmap.md`, `docs/architecture/system-overview.md`,
`docs/architecture/domain-model.md`, `docs/development/development-guide.md`,
`docs/audits/phase-2-audit.md`,
`docs/superpowers/plans/2026-09-14-phase-2-persistence-api.md`, and the
authoritative Phase 3 design linked above.

**Baseline main:** `a051510ed4bdb5532b878c6544bdf30309df14e7`

**Starting branch/HEAD:** `phase/3-document-ingestion` /
`3b6962c6800e1c6b3ccb899bfbad57c557e3c9ff`

**Plan status:** M3A remains `IN PROGRESS` while this plan awaits independent
review. This document authorizes no implementation by itself.

## Global Constraints

- The accepted Phase 3 design is the behavioral authority. If implementation
  evidence contradicts it, stop at the current task and report the conflict;
  do not silently revise the approved design.
- Execute this plan sequentially in one agent context. Use
  `superpowers:executing-plans`; repository policy forbids subagents, parallel
  agents, delegated implementers, and delegated reviewers unless the human
  explicitly authorizes an exception.
- At implementation start, Phase 3 is `IN PROGRESS`; the active milestone is
  `IN PROGRESS`; completed prior milestones retain `COMPLETE`; and future
  milestones retain `NOT STARTED`. M3A is not closed until this plan has
  independent review and human approval.
- Phase 3 answers only: “What does this source document deterministically
  contain?” It produces canonical content before any AI processing.
- V1 supports exactly `EMAIL_BODY`, `PDF`, `XLSX`, and `CSV` from the existing
  Phase 1 `SourceDocumentType`. `FORM` remains a Phase 1 enum value but is
  rejected by the Phase 3 dispatcher. Do not create a second document-type
  enum, and do not change `SourceDocument`.
- Phase 3 performs no LLM call, business validation, order approval/routing,
  database persistence, order mutation, external side effect, HTTP upload API,
  raw-file storage, object storage, multipart contract, n8n workflow, Gmail,
  Slack, or review UI work.
- The first public Phase 3 boundary is the synchronous internal function
  `process_document`. Do not add `/v1/documents`, a FastAPI route, or an upload
  adapter.
- All public records are immutable stdlib dataclasses with
  `frozen=True, slots=True`. Ordered metadata, pages, tables, rows, cells, and
  warnings are preserved in tuples; duplicate metadata keys remain duplicated
  and in caller order.
- SHA-256 is calculated over the exact incoming bytes before decoding or
  normalization. Never hash normalized text, and never query PostgreSQL or
  apply business duplicate policy to the hash.
- Text normalization is exactly Unicode NFC plus CRLF/CR to LF conversion. It
  preserves meaningful leading, trailing, and interior whitespace; it does not
  lowercase, globally trim, collapse whitespace, reorder content, deduplicate
  rows, or reinterpret business values. UTF-8 BOM handling occurs in decoding
  through `utf-8-sig`.
- MIME comparison strips surrounding whitespace, lowercases the base media
  type, ignores valid parameters such as `charset=utf-8`, and rejects blank or
  malformed declarations. Filename extensions never reclassify a declared
  document.
- The exact MIME map is `EMAIL_BODY → text/plain`, `CSV → text/csv`, `PDF →
  application/pdf`, and `XLSX →
  application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`.
- V1 safety defaults are fixed at:

  | Limit field | Default |
  | --- | ---: |
  | `max_input_bytes` | `10 * 1024 * 1024` |
  | `max_text_characters` | `1_000_000` |
  | `max_pdf_pages` | `50` |
  | `max_xlsx_sheets` | `20` |
  | `max_xlsx_rows_per_sheet` | `5_000` |
  | `max_xlsx_populated_cells` | `20_000` total |
  | `max_csv_rows` | `5_000` |
  | `max_table_columns` | `100` |
  | `max_xlsx_expanded_bytes` | `50 * 1024 * 1024` |

- Limits are injected through one immutable `DocumentLimits` value. Every
  exceeded limit raises `DocumentLimitError`; no parser truncates and then
  returns a partial canonical document.
- The XLSX row-span limit is per worksheet and is independent of the total
  populated-cell limit. The executor must detect a meaningful row beyond the
  configured span before materializing an unbounded sparse rectangle. A
  sparse cell at row 5,001 fails under the default even when the workbook has
  only one populated cell.
- Text/CSV use only Python standard-library parsing. No pandas, numpy solely
  for document parsing, libmagic/python-magic, OCR stack, cloud SDK, AI SDK,
  multipart/FastAPI upload dependency, or other parser dependency is allowed.
- Add `openpyxl` only in M3C and `pypdf` only in M3D. Update `uv.lock` at the
  same milestone and verify that lockfile movement is limited to the justified
  direct dependency and its required transitive closure. If any other genuine
  dependency is required, stop and report before changing dependency files.
- XLSX loading must be read-only, `data_only=False`, and `keep_links=False`.
  It must not execute formulas, macros, scripts, or external links. Macro
  package parts are rejected before workbook parsing.
- PDF processing has no OCR. A valid scanned or image-style PDF with no
  extractable text remains structurally represented with explicit warning(s)
  and no fabricated text.
- Focused document tests run without PostgreSQL, Docker, the FastAPI app,
  database/session modules, an AI provider, network access, or an API server.
  Existing Phase 0–2 behavior must remain green in the full repository gates.
- Synthetic fixtures only. Keep committed PDF/XLSX binaries small and
  ordinary repository files. Use injected small limits or generated temporary
  inputs for limit tests; never commit giant sparse workbooks or customer
  documents.

## File and interface map

Lock this structure before implementation. Create each file only in the task
that first needs it.

### Production files

| File | Responsibility | First milestone |
| --- | --- | --- |
| `src/opsflow/documents/__init__.py` | Deliberate Phase 3 public exports; never an empty future-package stub. | M3B/M3E |
| `src/opsflow/documents/models.py` | Immutable public records plus the private parser-result record. | M3B |
| `src/opsflow/documents/errors.py` | Small document-specific exception hierarchy with safe messages. | M3B |
| `src/opsflow/documents/limits.py` | Immutable limits and exact V1 defaults. | M3B |
| `src/opsflow/documents/common.py` | Shared MIME, UTF-8, normalization, SHA, and table-rendering helpers; created because all format paths need these concrete helpers. No generic parser framework. | M3B |
| `src/opsflow/documents/text.py` | UTF-8 plain-text/email-body parser. | M3B |
| `src/opsflow/documents/csv.py` | Strict explicit-dialect CSV parser and table renderer. | M3B |
| `src/opsflow/documents/xlsx.py` | XLSX ZIP/package preflight and read-only workbook parser. | M3C |
| `src/opsflow/documents/pdf.py` | Signature validation and page-by-page pypdf extraction. | M3D |
| `src/opsflow/documents/processor.py` | Supported-type/MIME/size/hash envelope, direct dispatcher, final text limit, and canonical-document construction. | M3E |

`common.py` is intentional rather than mechanical: `normalize_text`, MIME
normalization, UTF-8 decoding, raw-byte hashing, and compact JSON-row rendering
would otherwise be duplicated across four format modules and the dispatcher.
It must remain a small helper module with no abstract parser protocol, parser
registry, dependency-injection framework, or generic ingestion abstraction.

### Tests and fixtures

| Path | Coverage |
| --- | --- |
| `tests/unit/documents/test_models.py` | Public records, private parser-result shape, immutability, and structural invariants. |
| `tests/unit/documents/test_common.py` | Shared normalization, MIME, decoding, hashing, and rendering behavior. Create only because `common.py` is required. |
| `tests/unit/documents/test_text.py` | UTF-8/BOM, line endings, NFC, empty text, invalid bytes. |
| `tests/unit/documents/test_csv.py` | Explicit CSV grammar, rows/cells, quoting, multiline values, malformed data, and limits. |
| `tests/unit/documents/test_xlsx.py` | ZIP/package safety, sparse-row guard, workbook values, formulas, external-link safety, macros, limits, and corruption. |
| `tests/unit/documents/test_pdf.py` | Signature, page extraction/order, no-text warnings, encryption/corruption, limits, and repeatability. |
| `tests/unit/documents/test_processor.py` | Unified envelope, exact type/MIME map, hash/size, dispatch, final text limit, and all-format isolation. |
| `fixtures/documents/` | Small synthetic committed text, CSV, XLSX, and PDF regression files created only by their implementation milestones. |

No migration, API, persistence, Docker, CI, application, domain, or Phase 2
test file belongs to the Phase 3 implementation plan. No fixture is created in
M3A or by this plan.

### Locked public records

Implement these exact shapes unless a test demonstrates a direct type-checking
defect. Any such defect must be fixed within the approved design boundary or
reported rather than silently redesigned.

```python
from dataclasses import dataclass
from opsflow.domain.records import SourceDocumentType


@dataclass(frozen=True, slots=True)
class DocumentInput:
    document_type: SourceDocumentType
    name: str
    mime_type: str
    content: bytes
    source_reference: str | None = None
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CanonicalPage:
    number: int
    text: str


@dataclass(frozen=True, slots=True)
class CanonicalTable:
    name: str
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class DocumentWarning:
    code: str
    message: str
    location: str | None = None


@dataclass(frozen=True, slots=True)
class CanonicalDocument:
    document_type: SourceDocumentType
    name: str
    mime_type: str
    sha256: str
    size_bytes: int
    source_reference: str | None
    metadata: tuple[tuple[str, str], ...]
    text: str
    pages: tuple[CanonicalPage, ...]
    tables: tuple[CanonicalTable, ...]
    warnings: tuple[DocumentWarning, ...]
```

The parser modules return one consistent private record rather than four
different tuple conventions:

```python
@dataclass(frozen=True, slots=True)
class _ParsedDocumentContent:
    text: str
    pages: tuple[CanonicalPage, ...] = ()
    tables: tuple[CanonicalTable, ...] = ()
    warnings: tuple[DocumentWarning, ...] = ()
```

`_ParsedDocumentContent` lives in `models.py`, is imported by the four parser
modules and `processor.py`, and is not part of the public package surface.
The exact parser signatures are:

```python
def parse_text_document(content: bytes) -> _ParsedDocumentContent:
    pass


def parse_csv_document(
    content: bytes,
    limits: DocumentLimits,
) -> _ParsedDocumentContent:
    pass


def parse_xlsx_document(
    content: bytes,
    limits: DocumentLimits,
) -> _ParsedDocumentContent:
    pass


def parse_pdf_document(
    content: bytes,
    limits: DocumentLimits,
) -> _ParsedDocumentContent:
    pass
```

`parse_text_document` has no format-specific limit. The dispatcher applies the
final canonical-text limit to its result, just as it does for CSV/XLSX/PDF.
The other parsers receive `DocumentLimits` because their format-specific
limits must be enforced while records are being read.

### Locked limits, errors, and helpers

```python
@dataclass(frozen=True, slots=True)
class DocumentLimits:
    max_input_bytes: int
    max_text_characters: int
    max_pdf_pages: int
    max_xlsx_sheets: int
    max_xlsx_rows_per_sheet: int
    max_xlsx_populated_cells: int
    max_csv_rows: int
    max_table_columns: int
    max_xlsx_expanded_bytes: int


DEFAULT_DOCUMENT_LIMITS = DocumentLimits(
    max_input_bytes=10 * 1024 * 1024,
    max_text_characters=1_000_000,
    max_pdf_pages=50,
    max_xlsx_sheets=20,
    max_xlsx_rows_per_sheet=5_000,
    max_xlsx_populated_cells=20_000,
    max_csv_rows=5_000,
    max_table_columns=100,
    max_xlsx_expanded_bytes=50 * 1024 * 1024,
)
```

The exception hierarchy is:

```text
DocumentProcessingError
├── UnsupportedDocumentTypeError
├── DocumentValidationError
├── DocumentLimitError
└── DocumentParseError
```

The shared helper signatures are:

```python
def normalize_text(value: str) -> str:
    pass


def normalize_mime_type(value: str) -> str:
    pass


def decode_utf8(content: bytes) -> str:
    pass


def sha256_bytes(content: bytes) -> str:
    pass


def render_table_text(table: CanonicalTable) -> str:
    pass


def render_tables_text(tables: tuple[CanonicalTable, ...]) -> str:
    pass
```

`normalize_mime_type` returns a lowercase base media type and raises
`DocumentValidationError` for blank or malformed declarations. `decode_utf8`
uses `utf-8-sig` and translates `UnicodeDecodeError` to a safe
`DocumentParseError`. `sha256_bytes` is exactly
`hashlib.sha256(content).hexdigest()`. `render_table_text` emits the heading
line followed by one compact JSON array per row, using
`json.dumps(row, ensure_ascii=False, separators=(",", ":"))`; it emits only
the heading for an empty table. `render_tables_text` joins table renderings in
table order with one blank line and returns an empty string for no tables.

The dispatcher signature is:

```python
def process_document(
    document: DocumentInput,
    limits: DocumentLimits = DEFAULT_DOCUMENT_LIMITS,
) -> CanonicalDocument:
    pass
```

The dispatcher uses explicit `if`/`elif` dispatch over the four supported
`SourceDocumentType` values. It does not create a parser registry or generic
protocol.

`DocumentInput` validates `document_type` at construction: it must be an
actual `SourceDocumentType` member, so a value such as `"XML"` raises
`DocumentValidationError`. `SourceDocumentType.FORM` passes that input-record
validation because it is a real Phase 1 enum member, but `process_document`
rejects it with `UnsupportedDocumentTypeError` before MIME or parser dispatch.
The processor contract does not require behavior for malformed
`DocumentInput` instances fabricated by bypassing dataclass construction.

### Locked warning values

Use stable code/message/location construction so repeated parses compare equal:

| Code | Message | Location |
| --- | --- | --- |
| `EMPTY_TEXT` | `Document contains no non-whitespace text.` | `None` |
| `EMPTY_PDF_PAGE` | `PDF page contains no extractable text.` | `page:number` where number is 1-based |
| `NO_EXTRACTABLE_TEXT` | `PDF contains no extractable text on any page.` | `None` |
| `EMPTY_SHEET` | `Worksheet contains no populated cells.` | worksheet title |

These are the only warning concepts planned. `EMPTY_CSV` is not introduced;
a zero-record CSV is represented as an empty `CSV` table with `# CSV` text.

## Dependency sequencing and status protocol

M3B adds no runtime dependency and finishes with usable deterministic models,
validation, shared helpers, text, and CSV processing. `openpyxl` and `pypdf`
must not appear in `pyproject.toml` or `uv.lock` during M3B.

M3C adds only `openpyxl` with the implementation-selected compatible direct
constraint `openpyxl>=3.1,<4`, then updates `uv.lock` using the repository’s
existing `uv` workflow. Verify the diff contains only openpyxl and its required
transitive closure. M3C must not add pypdf.

M3D adds only `pypdf` with the compatible direct constraint `pypdf>=5,<7`, then
updates `uv.lock` and verifies only pypdf’s justified transitive movement.
M3D must not add any OCR, image, cloud, or AI package.

M3E adds no runtime dependency. If a package install or parser experiment
requires anything else, stop before changing the dependency files and report
the concrete requirement and why the approved two-dependency boundary is
insufficient.

Before later implementation begins, independent review and human approval of
this plan may close M3A. At the start of M3B, update only canonical status
records needed for the active milestone: Phase 3 remains `IN PROGRESS`, M3B
becomes `IN PROGRESS`, M3A is `COMPLETE` only after its separate review gate,
and M3C–M3F remain `NOT STARTED`. On each later milestone transition, the
previous milestone becomes `COMPLETE` only after implementation, self-review,
relevant tests, and exact-head GitHub CI; the next milestone becomes
`IN PROGRESS`; later milestones remain `NOT STARTED`. M3F is the only point at
which Phase 3 can become `COMPLETE`.

## M3B — Canonical Models, Validation & Text/CSV

M3B introduces no third-party runtime dependency and does not create XLSX/PDF
implementation files. Each task below is independently testable and ends with
an inspectable focused commit.

### Task 1: Define immutable document records, errors, and limits

**Files:**

- Create: `src/opsflow/documents/__init__.py`
- Create: `src/opsflow/documents/models.py`
- Create: `src/opsflow/documents/errors.py`
- Create: `src/opsflow/documents/limits.py`
- Test: `tests/unit/documents/test_models.py`

**Interfaces:** The task produces the public records, `_ParsedDocumentContent`,
the four-subclass exception hierarchy, and `DocumentLimits`/
`DEFAULT_DOCUMENT_LIMITS` exactly as locked above. `DocumentInput` reuses
`opsflow.domain.records.SourceDocumentType`; `SourceDocument` is not imported
as a replacement or modified.

- [ ] **Step 1: Write the failing contract tests (RED).**

  Create tests with these names and cases:

  - `test_document_input_preserves_duplicate_metadata_order`: construct an
    `EMAIL_BODY` input with
    `(("source", "first"), ("source", "second"))`; assert the tuple is
    unchanged and `source_reference` survives.
  - `test_document_input_rejects_non_enum_document_type`: construct an input
    with `document_type="XML"` and otherwise valid fields; expect
    `DocumentValidationError`. Construct the same shape with
    `SourceDocumentType.FORM` and assert record construction succeeds.
  - `test_document_records_are_frozen_and_slot_based`: construct every public
    record and `_ParsedDocumentContent`; assert assignment raises
    `FrozenInstanceError` and `__dict__` is absent.
  - `test_canonical_page_numbers_are_one_based`: assert zero/negative page
    numbers are rejected and page 1 is accepted.
  - `test_canonical_table_preserves_ragged_rows_and_empty_cells`: construct
    rows `(("A", "B"), ("1",), ("2", "3", ""))`; assert the exact
    row-width, cell, and ordering data is preserved.
  - `test_document_warning_requires_stable_code_and_message`: reject blank
    code/message and preserve an optional location.
  - `test_document_limits_match_approved_defaults`: assert all nine default
    values, including `max_xlsx_rows_per_sheet == 5_000` and
    `max_xlsx_populated_cells == 20_000`.
  - `test_document_limits_reject_nonpositive_values`: reject zero and negative
    limits without coercing them.
  - `test_document_errors_are_document_specific_and_safe`: assert subclass
    relationships and assert an exception string for a bad input does not
    contain a supplied raw body such as `private-secret-body`.

- [ ] **Step 2: Run RED and confirm the failure source.**

  ```bash
  uv run pytest tests/unit/documents/test_models.py -q --no-cov
  ```

  Expected result: collection fails because `opsflow.documents` does not yet
  exist. Do not create parser modules or dependency stubs to bypass collection.

- [ ] **Step 3: Implement the smallest contracts.**

  Define frozen slot dataclasses with tuple-typed fields and narrow
  `__post_init__` shape checks: nonblank names/codes/messages, bytes content,
  valid `SourceDocumentType`, positive page numbers and limits, tuple pairs for
  metadata, tuple rows, and string cells. `CanonicalTable` must not compare
  row lengths; its structural contract is only a tuple of tuple rows with
  string cells, so ragged rows are valid canonical data. Keep error
  constructors safe and document-specific. Export only the
  records/errors/limits that exist at this task; do not import future parser
  dependencies.

- [ ] **Step 4: Run GREEN, regressions, and self-review.**

  ```bash
  uv run pytest tests/unit/documents/test_models.py -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Review that `SourceDocumentType` is imported from Phase 1, no Phase 2 model
  or application module is imported, all default fields are present, and no
  raw content is embedded in error messages.

- [ ] **Step 5: Commit the contract slice.**

  ```bash
  git add src/opsflow/documents tests/unit/documents/test_models.py
  git commit -m "feat: add Phase 3 document contracts"
  ```

### Task 2: Implement shared MIME, normalization, decoding, hashing, and rendering helpers

**Files:**

- Create: `src/opsflow/documents/common.py`
- Test: `tests/unit/documents/test_common.py`

**Interfaces:** The task implements the five locked helpers in `common.py`.
No helper accepts a database session, network client, FastAPI request, AI
client, or parser registry.

- [ ] **Step 1: Write the failing helper tests (RED).**

  Create tests with these names and exact inputs:

  - `test_normalize_text_converts_line_endings_without_stripping`: input
    `"  A\r\nB\rC  "`; expect `"  A\nB\nC  "`.
  - `test_normalize_text_applies_nfc_and_preserves_whitespace`: input
    `"\u0065\u0301  value  "`; expect `"é  value  "`.
  - `test_normalize_mime_type_lowercases_base_and_ignores_parameters`: input
    `"  Text/Plain; charset=utf-8  "`; expect `"text/plain"`.
  - `test_normalize_mime_type_rejects_blank_and_malformed_values`: exercise
    `""`, `" ; charset=utf-8"`, `"text"`, `"text/ plain"`,
    `"text/plain; charset"`, and `"text/plain; =utf-8"`; expect
    `DocumentValidationError`.
  - `test_decode_utf8_accepts_bom_and_rejects_invalid_bytes`: expect BOM bytes
    to decode without U+FEFF and `b"\\xff"` to raise
    `DocumentParseError` without echoing bytes.
  - `test_sha256_bytes_hashes_exact_input`: compare `sha256_bytes(b"A\\r\\n")`
    with `hashlib.sha256(b"A\\r\\n").hexdigest()` and prove it differs from
    the hash of normalized `b"A\\n"`.
  - `test_render_table_text_uses_compact_unicode_json_rows`: render a `CSV`
    table with `("A", "é", "line\nvalue")`; assert heading `# CSV`, compact
    JSON escaping, `ensure_ascii=False`, and row order.
  - `test_render_empty_table_has_only_heading_and_no_tables_is_empty`: expect
    `# CSV` for zero rows and `""` for an empty table tuple.

- [ ] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_common.py -q --no-cov
  ```

  Expected result: collection fails because `common.py` and its helpers do not
  exist.

- [ ] **Step 3: Implement the concrete helpers.**

  Use `unicodedata.normalize("NFC", value.replace("\\r\\n", "\\n").replace("\\r", "\\n"))`;
  do not call `.strip()`. Decode with `content.decode("utf-8-sig")`. Validate
  the MIME base using a small standard-library/token check for exactly one
  nonblank `type/subtype` base. Validate each parameter segment as a nonblank
  token name followed by `=` and a nonblank token or balanced quoted value,
  then ignore the validated parameter values. Hash the bytes directly with
  `hashlib.sha256`.

  Render a table as its heading followed by one
  `json.dumps(row, ensure_ascii=False, separators=(",", ":"))` line per row;
  join multiple tables in their supplied order with `"\\n\\n"`. Do not
  normalize metadata or alter table row structure in the renderer.

- [ ] **Step 4: Run GREEN, regressions, and self-review.**

  ```bash
  uv run pytest tests/unit/documents/test_common.py -q --no-cov
  uv run pytest tests/unit/documents/test_models.py tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Check that no string trimming, lowercasing of content, metadata sorting,
  dialect sniffing, or decoded-text hashing entered the helpers.

- [ ] **Step 5: Commit the helper slice.**

  ```bash
  git add src/opsflow/documents/common.py tests/unit/documents/test_common.py
  git commit -m "feat: add Phase 3 canonical helpers"
  ```

### Task 3: Parse UTF-8 plain text and email bodies

**Files:**

- Create: `src/opsflow/documents/text.py`
- Test: `tests/unit/documents/test_text.py`
- Create: `fixtures/documents/text/clean-po.txt` and
  `fixtures/documents/text/bom-nfc.txt`

**Interfaces:** Implement `parse_text_document(bytes) -> _ParsedDocumentContent`.
It parses body/plain text, not RFC-822 `.eml`, headers, or attachments.

- [ ] **Step 1: Write the failing parser tests (RED).**

  Create these cases:

  - `test_parse_text_document_decodes_utf8_and_bom`: read the synthetic clean
    and BOM/NFC fixture bytes; assert normalized text, no pages, no tables.
  - `test_parse_text_document_normalizes_crlf_and_cr`: pass
    `b"A\\r\\nB\\rC"`; expect `"A\\nB\\nC"`.
  - `test_parse_text_document_preserves_meaningful_whitespace`: pass
    `b"  PO-1  \\n  10  "`; assert leading/trailing spaces remain.
  - `test_parse_text_document_warns_for_empty_or_whitespace_only_text`: pass
    `b" \\r\\n\\t"`; expect exactly one `EMPTY_TEXT` warning with the locked
    message/location and empty pages/tables.
  - `test_parse_text_document_rejects_invalid_utf8_safely`: pass invalid UTF-8
    and assert `DocumentParseError`; assert its message does not contain the
    raw byte representation.
  - `test_text_parser_does_not_infer_email_headers_or_attachments`: pass
    text beginning `From:`, `Subject:`, and a separator; assert it remains
    ordinary normalized text with no attachment/page/table records.

- [ ] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_text.py -q --no-cov
  ```

  Expected result: collection fails because `text.py` is absent.

- [ ] **Step 3: Implement the parser minimally.**

  Call `decode_utf8`, then `normalize_text`. If `normalized.strip()` is empty,
  return the normalized text plus exactly the locked `EMPTY_TEXT` warning;
  otherwise return text with empty pages/tables/warnings. Do not strip the
  returned text, infer headers, parse `.eml`, or create attachment records.

- [ ] **Step 4: Run GREEN, regressions, and self-review.**

  ```bash
  uv run pytest tests/unit/documents/test_text.py -q --no-cov
  uv run pytest tests/unit/documents/test_common.py tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Review BOM handling occurs only in `decode_utf8`, text normalization is
  conservative, and no parser import reaches FastAPI, SQLAlchemy, or AI code.

- [ ] **Step 5: Commit the text slice.**

  ```bash
  git add src/opsflow/documents/text.py tests/unit/documents/test_text.py fixtures/documents/text
  git commit -m "feat: parse Phase 3 plain text"
  ```

### Task 4: Parse explicit-dialect CSV into canonical tables

**Files:**

- Create: `src/opsflow/documents/csv.py`
- Test: `tests/unit/documents/test_csv.py`
- Create: small synthetic
  `fixtures/documents/csv/quoted-multiline.csv` and
  `fixtures/documents/csv/empty-cells.csv`.

**Interfaces:** Implement `parse_csv_document(bytes, DocumentLimits) ->
_ParsedDocumentContent`. It returns one table named exactly `CSV`, with
`pages == ()`, and renders canonical text through `render_table_text`. Each
parsed record retains its actual width; ragged records are valid when each
individual row is within `limits.max_table_columns`, and no padding is added.

- [ ] **Step 1: Write the failing CSV tests (RED).**

  Create these cases and assertions:

  - `test_parse_csv_document_preserves_rows_columns_and_empty_cells`: parse
    `SKU,Quantity\nABC-1,10\n,\n`; assert rows
    `(("SKU", "Quantity"), ("ABC-1", "10"), ("", ""))`.
  - `test_parse_csv_document_preserves_ragged_record_widths`: parse
    `A,B\n1\n2,3,\n`; assert rows
    `(("A", "B"), ("1",), ("2", "3", ""))` with no padding or row
    reordering.
  - `test_parse_csv_document_handles_quoted_delimiters_and_multiline_cells`:
    parse `"SKU,blue","line 1\nline 2"\n`; assert two cells and the embedded
    newline remains inside the second cell.
  - `test_parse_csv_document_uses_utf8_bom_and_nfc`: assert BOM removal and NFC
    normalization in cell values.
  - `test_parse_csv_document_counts_every_record_and_checks_each_width`: use
    injected `DocumentLimits(max_input_bytes=100, max_text_characters=1000,
    max_pdf_pages=10, max_xlsx_sheets=10, max_xlsx_rows_per_sheet=10,
    max_xlsx_populated_cells=10, max_csv_rows=2, max_table_columns=2,
    max_xlsx_expanded_bytes=1000)` to
    reject a third record and a three-column record independently.
  - `test_parse_csv_document_keeps_zero_record_csv_as_empty_table`: pass
    `b""`; assert one `CSV` table with zero rows, `# CSV` text, and no warning.
  - `test_parse_csv_document_rejects_malformed_quoted_input`: pass an
    unclosed quoted record; expect `DocumentParseError` without raw CSV text in
    the message.
  - `test_csv_rendering_is_compact_unicode_and_repeatable`: assert exact text
    lines and equality across two parses of the same bytes.

- [ ] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_csv.py -q --no-cov
  ```

  Expected result: collection fails because `csv.py` is absent.

- [ ] **Step 3: Implement the standard-library parser.**

  Decode with `decode_utf8`, wrap the resulting string in
  `io.StringIO(decoded, newline="")`, and construct
  `csv.reader(stream, delimiter=",", quotechar='"', strict=True)`. Do not
  sniff dialects. Iterate records one at a time; increment the row count for
  every parsed record before appending, reject a count above
  `limits.max_csv_rows`, reject each row whose width exceeds
  `limits.max_table_columns`, normalize each cell with `normalize_text`, and
  preserve empty rows/cells and each record’s actual width. Ragged records are
  allowed; only the individual-row width check applies, and no padding is
  introduced. Translate `csv.Error` to `DocumentParseError` without including
  source content. Return `CanonicalTable("CSV", rows)` and
  `render_table_text` output. A zero-record input is valid.

- [ ] **Step 4: Run GREEN, M3B regression, and self-review.**

  ```bash
  uv run pytest tests/unit/documents/test_csv.py -q --no-cov
  uv run pytest tests/unit/documents -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Confirm M3B contains no `openpyxl`/`pypdf` dependency or import, the row
  limit is not a character limit, no records are silently truncated, and table
  structure is authoritative over the rendered text.

- [ ] **Step 5: Commit M3B’s deterministic text/CSV slice.**

  ```bash
  git add src/opsflow/documents/csv.py tests/unit/documents/test_csv.py fixtures/documents/csv
  git commit -m "feat: parse Phase 3 CSV documents"
  ```

## M3C — XLSX Parsing

M3C adds only openpyxl. The archive guard precedes every workbook parse and is
designed to avoid trusting attacker-controlled worksheet dimensions.

### Task 5: Add openpyxl and implement XLSX ZIP/package preflight

**Files:**

- Modify: `pyproject.toml` through `uv add "openpyxl>=3.1,<4"`
- Modify: `uv.lock` through the same dependency operation
- Modify: `src/opsflow/documents/xlsx.py`
- Test: `tests/unit/documents/test_xlsx.py`
- Create only after the dependency is locked: a small synthetic workbook
  fixture under `fixtures/documents/xlsx/` for later parser tests.

**Interfaces:** Define the private preflight boundary in `xlsx.py`:

```python
@dataclass(frozen=True, slots=True)
class _XlsxSheetBounds:
    title: str
    part_name: str
    max_meaningful_row: int
    max_meaningful_column: int


@dataclass(frozen=True, slots=True)
class _XlsxPackageInfo:
    sheets: tuple[_XlsxSheetBounds, ...]
    populated_cell_count: int


def _validate_xlsx_package(
    content: bytes,
    limits: DocumentLimits,
) -> _XlsxPackageInfo:
    pass
```

These are module-private safety records, not a generic OOXML model and not a
new public parser protocol.

- [ ] **Step 1: Add only the justified dependency and prove the lock diff.**

  Run:

  ```bash
  uv add "openpyxl>=3.1,<4"
  git diff -- pyproject.toml uv.lock
  ```

  Confirm only the direct openpyxl requirement and its required lockfile
  closure moved. If `uv` proposes another direct runtime dependency, stop and
  report it. Confirm `pypdf` is still absent.

- [ ] **Step 2: Write failing package-preflight tests (RED).**

  In `test_xlsx.py`, create in-memory ZIP bytes with `zipfile` for these exact
  cases:

  - `test_xlsx_package_requires_content_types_and_workbook_parts`: omit each
    required member in turn; expect `DocumentValidationError` before
    `openpyxl.load_workbook` is reachable.
  - `test_xlsx_package_rejects_non_zip_and_malformed_zip`: pass arbitrary bytes
    and truncated ZIP bytes; expect `DocumentParseError` or
    `DocumentValidationError` from the document hierarchy, never raw
    `BadZipFile`.
  - `test_xlsx_package_rejects_macro_member_and_macro_content_type`: provide a
    `xl/vbaProject.bin` member or a VBA macro content type in
    `[Content_Types].xml`; expect `DocumentValidationError`.
  - `test_xlsx_package_enforces_expanded_size_before_workbook_load`: provide a
    small ZIP whose member `file_size` exceeds an injected
    `max_xlsx_expanded_bytes`; monkeypatch `xlsx.load_workbook` to fail if
    called; expect `DocumentLimitError` and prove the loader was not called.
  - `test_xlsx_package_rejects_sheet_count_before_workbook_materialization`:
    provide more worksheet parts than injected `max_xlsx_sheets`; expect
    `DocumentLimitError`.
  - `test_xlsx_package_sparse_row_guard_rejects_row_beyond_small_limit`: build
    one worksheet XML containing a single value-bearing cell at row 6 and pass
    `max_xlsx_rows_per_sheet=5`; expect `DocumentLimitError` before workbook
    loading. This is the required sparse-workbook safety proof and uses a
    small injected limit rather than a giant fixture.
  - `test_xlsx_package_sparse_column_guard_rejects_column_beyond_limit`: place
    a value-bearing cell at column 3 with `max_table_columns=2`; expect
    `DocumentLimitError`.

- [ ] **Step 3: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_xlsx.py -q --no-cov
  ```

  Expected result: collection/import failure until `xlsx.py` and the package
  preflight boundary exist. The tests must not import the FastAPI app or a
  database session.

- [ ] **Step 4: Implement bounded package inspection before openpyxl.**

  Open the input with `zipfile.ZipFile(io.BytesIO(content))`; translate
  `BadZipFile`, invalid member reads, and XML failures to safe document
  errors. Inspect every `ZipInfo` before calling openpyxl: reject duplicate
  member names if present, reject macro-bearing member names/content types,
  sum `ZipInfo.file_size` and fail above
  `limits.max_xlsx_expanded_bytes`, require `[Content_Types].xml` and
  `xl/workbook.xml`, and require worksheet relationship targets under
  `xl/worksheets/`.

  Use a small `xml.etree.ElementTree.iterparse` pass over workbook metadata and
  worksheet XML streams solely for package structure and row/cell coordinates;
  do not expose or build a generic XML parser. Resolve workbook sheet order to
  worksheet part names through `xl/workbook.xml` and its relationship part.
  For each worksheet stream, clear elements as they are consumed so the pass
  never materializes a complete XML tree. A value-bearing cell is one with a
  formula (`f`), value (`v`), or inline string (`is`) child; style-only cells
  are not meaningful. Read its row/column coordinates (falling back to the
  sequential row position only when the row attribute is absent), track the
  highest meaningful row/column and count meaningful cells.

  As soon as a meaningful row exceeds
  `limits.max_xlsx_rows_per_sheet`, raise `DocumentLimitError`; do the same for
  a meaningful column above `limits.max_table_columns` and for aggregate
  populated cells above `limits.max_xlsx_populated_cells`. This is a bounded
  structural guard, not an iteration to Excel’s maximum row. It must run
  before `load_workbook` and must not trust `ws.max_row` or a claimed
  the worksheet `dimension` element as the safety authority.

  If a supported openpyxl version cannot coexist with this bounded guard or
  the relationship/coordinate pass cannot reliably detect the required
  sparse-row case, stop and report rather than weakening the row-span rule.

- [ ] **Step 5: Run GREEN, dependency, and regression checks.**

  ```bash
  uv run pytest tests/unit/documents/test_xlsx.py -q --no-cov
  uv run pytest tests/unit/documents/test_models.py tests/unit/documents/test_common.py tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Inspect `pyproject.toml`/`uv.lock` again for only openpyxl movement and
  confirm the preflight opens no network resource and never calls an external
  command.

- [ ] **Step 6: Commit the XLSX package-safety slice.**

  ```bash
  git add pyproject.toml uv.lock src/opsflow/documents/xlsx.py tests/unit/documents/test_xlsx.py
  git commit -m "build: add Phase 3 XLSX preflight"
  ```

### Task 6: Parse bounded XLSX worksheets into deterministic tables

**Files:**

- Modify: `src/opsflow/documents/xlsx.py`
- Modify: `tests/unit/documents/test_xlsx.py`
- Create: small synthetic committed fixtures under
  `fixtures/documents/xlsx/`, including `clean-multisheet.xlsx` and
  `formulas.xlsx`.

**Interfaces:** Complete `parse_xlsx_document(bytes, DocumentLimits) ->
_ParsedDocumentContent` using Task 5’s `_XlsxPackageInfo`. The parser loads
with `load_workbook(BytesIO(content), read_only=True, data_only=False,
keep_links=False)` and closes the workbook in `finally`.

- [ ] **Step 1: Write failing workbook behavior tests (RED).**

  Use committed small fixtures plus `tmp_path`/in-memory ZIP data for edge
  cases. Create these tests:

  - `test_parse_xlsx_document_preserves_sheet_order_and_names`: assert table
    names and order match workbook order, pages are empty, and rows/columns
    remain ordered.
  - `test_parse_xlsx_document_preserves_structural_empty_cells_and_rows`:
    create values in A1 and C2; assert rows are
    `(("A1", "", ""), ("", "", "C2"))`, including the empty middle cell.
  - `test_parse_xlsx_document_preserves_formula_expression`: assert a formula
    cell is represented as its source expression such as `=SUM(A1:A2)`, not a
    calculated cached value.
  - `test_parse_xlsx_document_converts_scalars_deterministically`: cover
    string/NFC, `None -> ""`, `False -> "false"`, integer, float, date,
    datetime, and time; assert locale-independent exact strings and
    `.isoformat()` date/time values.
  - `test_parse_xlsx_document_warns_only_for_truly_empty_sheet`: assert an
    empty worksheet has an empty table and one locked `EMPTY_SHEET` warning;
    an all-empty structural row is not treated as populated.
  - `test_parse_xlsx_document_enforces_sheet_row_cell_and_column_limits`:
    inject separate small limits and assert sheet, row-span, populated-cell,
    and column violations raise `DocumentLimitError` without truncation.
  - `test_parse_xlsx_document_preserves_per_sheet_row_span_without_sparse_workload`:
    use a meaningful cell at row 5 under an injected limit of 5 and assert
    exactly five-row canonical span; use a cell at row 6 and assert the
    preflight fails before worksheet iteration.
  - `test_parse_xlsx_document_rejects_unexpected_scalar_type`: monkeypatch a
    fake cell value to an unsupported object and expect `DocumentParseError`,
    not arbitrary `str(value)` conversion.
  - `test_parse_xlsx_document_does_not_follow_external_links`: use an XLSX
    package with an external-link relationship and monkeypatch any network
    attempt to fail; assert parsing completes locally and the loader call uses
    `keep_links=False`.
  - `test_parse_xlsx_document_rejects_corrupt_workbook_and_non_xlsx_zip`: pass
    corrupt workbook XML and a valid ZIP lacking XLSX package structure; assert
    safe document-specific errors.
  - `test_parse_xlsx_document_repeated_parses_compare_equal`: parse the same
    fixture twice with equal limits and assert exact `_ParsedDocumentContent`
    equality.

- [ ] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_xlsx.py -q --no-cov
  ```

  Expected result: behavior tests fail because worksheet materialization,
  scalar conversion, rendering, and warning construction are incomplete.

- [ ] **Step 3: Implement read-only bounded worksheet parsing.**

  After `_validate_xlsx_package` succeeds, enforce the package sheet count,
  load with the exact safe keyword arguments, and pair workbook worksheets with
  the preflight sheet order. For each `_XlsxSheetBounds`, iterate only
  `min_row=1..max_meaningful_row` and
  `min_col=1..max_meaningful_column`; both values are preflight-bounded by the
  configured row/column limits. The XLSX parser deliberately emits a
  rectangular bounded coordinate range for each sheet; this is XLSX parser
  behavior and is not a `CanonicalTable` invariant. Do not iterate an
  unbounded `ws.iter_rows()`.
  Emit every row in the coordinate span, including all-empty rows between the
  first and last meaningful row. Count non-`None` source values across sheets
  and fail before returning when the aggregate populated-cell limit is
  exceeded. Do not silently truncate.

  Convert only known openpyxl values in this order: `None -> ""`; `bool ->
  "true"/"false"`; `datetime`, `date`, and `time` -> `.isoformat()` with
  `datetime` checked before `date`; `str` -> `normalize_text`; `int`/`float`
  -> stable Python `str(value)` without locale formatting; formula strings
  remain strings because `data_only=False`; every other type raises
  `DocumentParseError`. Build a `CanonicalTable` per sheet, render all tables
  with stable sheet headings, and issue `EMPTY_SHEET` only when the sheet has
  no value-bearing cells.

- [ ] **Step 4: Create and verify small synthetic fixtures.**

  Generate the committed XLSX files once with a controlled local script kept
  outside the repository, using the already-approved openpyxl dependency;
  remove that one-time script after generation. The committed set is limited
  to a clean single/multi-sheet workbook and a formula/date workbook. Corrupt,
  macro, external-link, sparse, and limit cases remain generated in memory or
  under `tmp_path`; no giant or downloaded binary is committed. Inspect archive
  members and byte sizes before staging fixtures.

- [ ] **Step 5: Run GREEN, regressions, and self-review.**

  ```bash
  uv run pytest tests/unit/documents/test_xlsx.py -q --no-cov
  uv run pytest tests/unit/documents/test_models.py tests/unit/documents/test_common.py tests/unit/documents/test_text.py tests/unit/documents/test_csv.py -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run ruff format --check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Review that formulas are not evaluated, macros are rejected, external links
  are not followed, row-span and populated-cell limits remain independent, no
  private openpyxl internals are used, and all output ordering is explicit.

- [ ] **Step 6: Commit M3C.**

  ```bash
  git add src/opsflow/documents/xlsx.py tests/unit/documents/test_xlsx.py fixtures/documents/xlsx
  git commit -m "feat: parse Phase 3 XLSX documents"
  ```

## M3D — PDF Parsing

M3D adds only pypdf and keeps PDF extraction local, page-ordered, conservative,
and free of OCR.

### Task 7: Add pypdf, synthetic PDF fixtures, and core page extraction

**Files:**

- Modify: `pyproject.toml` through `uv add "pypdf>=5,<7"`
- Modify: `uv.lock` through the same dependency operation
- Create: `src/opsflow/documents/pdf.py`
- Test: `tests/unit/documents/test_pdf.py`
- Create: small committed fixtures under `fixtures/documents/pdf/`:
  `single-page-text.pdf` and `multi-page-text.pdf`.

**Interfaces:** Implement `parse_pdf_document(bytes, DocumentLimits) ->
_ParsedDocumentContent` with `CanonicalPage` records numbered from 1.

- [ ] **Step 1: Add only pypdf and inspect dependency movement.**

  Run:

  ```bash
  uv add "pypdf>=5,<7"
  git diff -- pyproject.toml uv.lock
  ```

  Confirm openpyxl remains the only earlier document dependency and the diff
  contains only pypdf plus its justified lockfile closure. Stop for any other
  direct dependency proposal.

- [ ] **Step 2: Write failing core PDF tests (RED).**

  Create these tests:

  - `test_parse_pdf_document_validates_pdf_signature`: pass bytes beginning
    with `%PDF-` and a valid fixture; assert parsing proceeds; pass XLSX/text
    bytes and assert `DocumentValidationError` or `DocumentParseError` without
    invoking extraction.
  - `test_parse_pdf_document_extracts_single_page_text`: assert exactly one
    `CanonicalPage(number=1, text="expected page text")`, normalized text, no
    tables, and no OCR.
  - `test_parse_pdf_document_preserves_multi_page_order`: assert page numbers
    `[1, 2]` and page text remains in source page order.
  - `test_parse_pdf_document_enforces_page_limit_before_extraction`: inject
    `max_pdf_pages=1` for the two-page fixture and monkeypatch page extraction
    to fail if reached; expect `DocumentLimitError` first.
  - `test_parse_pdf_document_repeated_parses_are_equal`: compare two parses of
    each committed text fixture.

- [ ] **Step 3: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_pdf.py -q --no-cov
  ```

  Expected result: collection fails because `pdf.py` is absent.

- [ ] **Step 4: Implement signature validation and page extraction.**

  Require `content.startswith(b"%PDF-")`; do not strip arbitrary leading
  bytes or perform signature recovery. Construct `pypdf.PdfReader` from
  `io.BytesIO(content)` with strict parsing. If the reader is encrypted, do
  not guess or supply passwords; fail safely when it cannot be read without
  credentials. Read `len(reader.pages)` before extracting any page and reject
  above `limits.max_pdf_pages`.

  For each page in reader order, call `page.extract_text()`, map `None` to
  `""`, normalize the resulting text with `normalize_text`, and emit
    `CanonicalPage(number=index + 1, text=normalized_page_text)`. Keep all
    page records. Do not
  render page layout, execute document instructions, call OCR, or call a
  network service.

- [ ] **Step 5: Create/inspect small text-PDF fixtures and run GREEN.**

  Generate the two committed synthetic PDFs once with a controlled local
  script kept outside the repository that writes ordinary text content streams
  and valid PDF xref/object structure; remove that one-time script after
  generation and do not use a new fixture-generation dependency. Keep each file
  small, inspectable, and free of customer data. Use in-memory pypdf writers
  for encrypted/corrupt edge PDFs instead of committing additional binaries.

  ```bash
  uv run pytest tests/unit/documents/test_pdf.py -q --no-cov
  uv run pytest tests/unit/documents/test_xlsx.py tests/unit/documents/test_csv.py tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Inspect the dependency diff and confirm no OCR/image/cloud/AI dependency
  entered the lockfile.

- [ ] **Step 6: Commit the core PDF slice.**

  ```bash
  git add pyproject.toml uv.lock src/opsflow/documents/pdf.py tests/unit/documents/test_pdf.py fixtures/documents/pdf
  git commit -m "build: add Phase 3 PDF parser"
  ```

### Task 8: Complete PDF warnings, failure behavior, and deterministic combined text

**Files:**

- Modify: `src/opsflow/documents/pdf.py`
- Modify: `tests/unit/documents/test_pdf.py`
- Create: small synthetic `fixtures/documents/pdf/no-text.pdf`.

**Interfaces:** Complete the locked `EMPTY_PDF_PAGE` and
`NO_EXTRACTABLE_TEXT` warning behavior and deterministic combined text. No
OCR or visual reconstruction is introduced.

- [ ] **Step 1: Write failing warning/failure tests (RED).**

  Create these tests:

  - `test_parse_pdf_document_warns_for_each_empty_page`: build a valid PDF
    containing a text page and a blank page; assert the blank page remains in
    `pages` and exactly one `EMPTY_PDF_PAGE` warning points to `page:2`.
  - `test_parse_pdf_document_reports_no_extractable_text_without_fabrication`:
    parse a valid blank/image-style PDF; assert every page text is `""`,
    `NO_EXTRACTABLE_TEXT` exists, no nonempty text is invented, and page
    structure remains present.
  - `test_parse_pdf_document_joins_only_extractable_pages_deterministically`:
    assert combined text is `"page one\\n\\npage three"` for text/empty/text
    pages and `""` when every page is empty.
  - `test_parse_pdf_document_normalizes_extracted_line_endings_and_nfc`: use a
    fixture/page result containing CRLF/CR and decomposed characters; assert
    shared normalization.
  - `test_parse_pdf_document_rejects_corrupt_and_encrypted_inputs_safely`:
    pass truncated bytes with a PDF signature and an encrypted in-memory PDF;
    expect `DocumentParseError` without password guessing or raw bytes in the
    message.
  - `test_pdf_parser_has_no_ocr_or_network_dependency`: inspect imports and
    monkeypatch network-related calls to fail; assert the parser remains local.

- [ ] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_pdf.py -q --no-cov
  ```

  Expected result: warning, combined-text, and corrupt/encrypted cases fail
  until the behavior is completed.

- [ ] **Step 3: Implement the warning and combined-text rules.**

  For each normalized page whose `.strip()` is empty, append exactly one
  `DocumentWarning("EMPTY_PDF_PAGE", "PDF page contains no extractable text.",
  f"page:{number}")`. If every page
  is empty/whitespace-only, append one `NO_EXTRACTABLE_TEXT` warning. Build
  combined text with `"\\n\\n".join(page.text for page in pages if page.text.strip())`,
  which keeps all page records authoritative while returning an empty string
  for a fully non-extractable PDF. Translate pypdf reader/page exceptions to
  `DocumentParseError` with safe diagnostics. Never call `decrypt` with a
  guessed password.

- [ ] **Step 4: Run GREEN, regressions, and self-review.**

  ```bash
  uv run pytest tests/unit/documents/test_pdf.py -q --no-cov
  uv run pytest tests/unit/documents/test_text.py tests/unit/documents/test_csv.py tests/unit/documents/test_xlsx.py tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run ruff format --check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Verify no exact visual-layout guarantee was added, no OCR package exists,
  page order is source order, and all warning construction is deterministic.

- [ ] **Step 5: Commit M3D.**

  ```bash
  git add src/opsflow/documents/pdf.py tests/unit/documents/test_pdf.py fixtures/documents/pdf
  git commit -m "feat: harden Phase 3 PDF parsing"
  ```

## M3E — Unified Processor & Robustness

M3E introduces the public dispatcher, completes the canonical envelope, and
proves all four formats operate without infrastructure. It adds no runtime
dependency.

### Task 9: Implement the synchronous processor envelope and dispatcher

**Files:**

- Create: `src/opsflow/documents/processor.py`
- Modify: `src/opsflow/documents/__init__.py`
- Test: `tests/unit/documents/test_processor.py`

**Interfaces:** Implement the locked `process_document` function. The module
owns supported-type validation, normalized MIME compatibility, input-byte
limit, exact-byte SHA-256, direct parser dispatch, final canonical-text limit,
and `CanonicalDocument` construction.

- [ ] **Step 1: Write failing dispatcher tests (RED).**

  Create these tests:

  - `test_process_document_builds_common_envelope_for_plain_text`: provide an
    `EMAIL_BODY` input with mixed-case `Text/Plain; charset=utf-8`, source
    reference, duplicate metadata, and CRLF bytes; assert normalized MIME,
    exact raw SHA-256, byte size, preserved metadata/reference, normalized
    text, and no pages/tables.
  - `test_process_document_dispatches_every_supported_format`: pass one
    input for text, CSV, XLSX, and PDF fixtures; assert the correct canonical
    content shape for each.
  - `test_process_document_rejects_form_before_parser_dispatch`: construct a
    valid `DocumentInput` with `SourceDocumentType.FORM`, monkeypatch every
    format parser to fail if called, and expect
    `UnsupportedDocumentTypeError` before MIME or parser dispatch.
  - `test_process_document_enforces_exact_mime_map_without_reclassification`:
    exercise PDF bytes declared as XLSX, XLSX bytes declared as PDF, and a
    wrong filename extension; assert mismatches fail and extensions do not
    change the declared type.
  - `test_process_document_enforces_input_and_canonical_text_limits`: inject
    small `max_input_bytes` and `max_text_characters`; assert
    `DocumentLimitError` before truncation and no partial canonical result.
  - `test_process_document_repeated_same_input_compares_equal`: parse every
    supported fixture twice with identical limits and assert exact
    `CanonicalDocument` equality.

- [ ] **Step 2: Run RED.**

  ```bash
  uv run pytest tests/unit/documents/test_processor.py -q --no-cov
  ```

  Expected result: collection fails because `processor.py` and the public
  dispatcher do not exist.

- [ ] **Step 3: Implement one explicit dispatcher.**

  `DocumentInput` has already validated the enum shape. Check
  `document.document_type is SourceDocumentType.FORM` first and raise
  `UnsupportedDocumentTypeError` before MIME or parser dispatch. For the four
  supported enum members, call `normalize_mime_type`, compare against the exact
  map, and check `len(document.content)` against `limits.max_input_bytes` before
  parsing. Compute `sha256_bytes(document.content)` before any normalization.
  Dispatch with explicit branches to the four parser signatures. Reject MIME
  mismatches with the focused exception hierarchy. After parsing, reject
  `len(parsed.text) > limits.max_text_characters`; never slice the text. Do not
  add a processor branch for malformed `DocumentInput` instances that could
  exist only by bypassing construction.

  Construct `CanonicalDocument` from the original type/name/content-derived
  fields, normalized MIME, raw hash, byte size, original reference/metadata,
  and parser result tuples. Do not add current time, random IDs, absolute
  paths, environment values, persistence calls, network calls, or AI calls.
  Export the dispatcher and existing Phase 3 public records from
  `documents/__init__.py` without importing the FastAPI app.

- [ ] **Step 4: Run GREEN, regressions, and self-review.**

  ```bash
  uv run pytest tests/unit/documents/test_processor.py -q --no-cov
  uv run pytest tests/unit/documents -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check src/opsflow/documents tests/unit/documents
  uv run ruff format --check src/opsflow/documents tests/unit/documents
  uv run mypy src/opsflow/documents
  git diff --check
  ```

  Use import inspection or an isolated subprocess to prove focused document
  tests do not import `opsflow.api`, `opsflow.database`, SQLAlchemy sessions,
  or the FastAPI app. Review that `SourceDocument` remains unchanged and the
  dispatcher exposes identity only rather than duplicate-business policy.

- [ ] **Step 5: Commit the processor slice.**

  ```bash
  git add src/opsflow/documents/processor.py src/opsflow/documents/__init__.py tests/unit/documents/test_processor.py
  git commit -m "feat: add Phase 3 document dispatcher"
  ```

### Task 10: Prove all-format robustness, isolation, and implementation-facing documentation

**Files:**

- Modify: `tests/unit/documents/test_processor.py`
- Modify: individual document modules only when a focused regression test
  demonstrates an implementation defect.
- Modify: `docs/development/development-guide.md` to record the focused
  command and infrastructure-independent document-test boundary once the
  behavior is implemented.

**Interfaces:** No new public interface or dependency. This task turns the
approved robustness requirements into a repeatable all-format evidence sweep.

- [ ] **Step 1: Write failing robustness/isolation tests (RED).**

  Add these exact cases:

  - `test_supported_formats_have_canonical_output_without_infrastructure`:
    invoke `process_document` for all four committed synthetic formats in a
    test process with database/network/AI modules unavailable; assert success.
  - `test_corruption_mismatch_and_excess_fail_with_document_errors`: combine
    corrupt text/CSV/XLSX/PDF bytes, mismatched MIME/type pairs, and injected
    input/text/page/sheet/row-span/cell/width/expanded-size limits; assert the
    focused exception classes and no truncation.
  - `test_duplicate_hashes_are_exposed_but_not_rejected`: process identical
    bytes under two names/references; assert equal SHA-256 and successful
    independent canonical results.
  - `test_canonical_output_contains_no_runtime_identity`: assert serialized
    record fields contain no timestamp, random identifier, absolute
    environment path, network result, or raw-body error payload.
  - `test_document_package_has_no_http_storage_or_ai_boundary`: inspect the
    document module import graph and assert no FastAPI, database, SQLAlchemy,
    HTTP client, AI SDK, n8n, object-storage, or order-application import.
  - `test_full_canonical_text_rendering_is_repeatable_for_all_tables_and_pages`:
    compare text/page/table/warning tuples over repeated runs for all fixtures.

- [ ] **Step 2: Run RED and isolate each failure.**

  ```bash
  uv run pytest tests/unit/documents -q --no-cov
  ```

  Expected result: any uncovered edge behavior fails with a concrete assertion
  or import-boundary violation. If the suite is already green, record that no
  production fix is justified and proceed to the evidence/documentation step;
  do not create an empty implementation commit.

- [ ] **Step 3: Apply only evidence-backed minimal fixes.**

  For each failing case, keep the assertion, make the smallest change within
  the approved design, rerun the single failing test, and preserve the exact
  parser interfaces. Never solve a failure by broadening limits, truncating
  data, adding a dependency, importing application infrastructure, or changing
  the design spec. Any requirement that cannot be met without such a change is
  a stop-and-report condition.

- [ ] **Step 4: Update the development guide and run GREEN.**

  Add a concise repository command note:

  ```bash
  uv run pytest tests/unit/documents -q --no-cov
  ```

  State that this focused suite requires no PostgreSQL, Docker, API server,
  AI provider, or internet access, while the full GitHub Backend suite still
  exercises the PostgreSQL-backed Phase 0–2 repository. Do not add a new API,
  upload contract, persistence instruction, or future-phase behavior.

  ```bash
  uv run pytest tests/unit/documents -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src/opsflow
  git diff --check
  ```

- [ ] **Step 5: Review scope and commit only a nonempty hardening slice.**

  Inspect every changed implementation line, warning, error, import, and
  limit. Confirm all four formats, `FORM` rejection, OCR deferral, no
  persistence/API boundary, and exact dependency set. If documentation and
  tests are the only changes, commit them; if no changes were required after
  the processor commit, leave the tree unchanged and record that fact.

  ```bash
  git add src/opsflow/documents tests/unit/documents docs/development/development-guide.md
  git commit -m "test: harden Phase 3 document processing"
  ```

### Task 11: Run the complete Phase 0–3 regression ladder and exact milestone evidence

**Files:**

- Modify only files whose defect is demonstrated by Task 10 or this task’s
  checks.
- Test: all existing repository tests plus
  `tests/unit/documents/`.

**Interfaces:** No new interface. This task produces no architecture change;
it produces the evidence required to close M3E and is allowed to commit only
minimal evidence-backed corrections.

- [ ] **Step 1: Run the focused-to-full regression ladder.**

  Run in this order and retain command output/results:

  ```bash
  uv run pytest tests/unit/documents -q --no-cov
  uv run pytest tests/unit/domain -q --no-cov
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src/opsflow
  make frontend-check
  make check
  ```

  The focused suite and domain suite must work without PostgreSQL. `make
  check` may use the established PostgreSQL/Docker environment and remains the
  full repository gate. If PostgreSQL is unavailable, record that environmental
  limitation, run every non-database gate, and require exact-head GitHub CI for
  the authoritative result.

- [ ] **Step 2: Perform the M3E self-review before any correction.**

  Inspect the complete diff and dependency lock movement. Search imports for
  FastAPI/database/network/AI access, review all limit checks for explicit
  failure rather than truncation, verify row-span preflight precedes openpyxl
  iteration, verify formula/macro/external-link safety, and confirm no Phase 4
  extraction or Phase 5 validation language entered executable code.

- [ ] **Step 3: Correct only demonstrated defects using RED → GREEN.**

  For each failure, retain or create the smallest exact regression assertion,
  run the failing focused command, make the minimal fix, rerun the focused
  command, then rerun the affected regression command. Stop and report if a
  fix would require changing the approved design, adding a third runtime
  dependency, adding infrastructure, or weakening a safety limit.

- [ ] **Step 4: Re-run all gates and record exact-head CI prerequisites.**

  Re-run the full ladder after any correction, run `git diff --check`, inspect
  changed files with `git status --short`, and push the exact tested HEAD to
  `origin/phase/3-document-ingestion`. Wait for exact-head GitHub CI and
  require Backend `SUCCESS`, Frontend `SUCCESS`, and Secret scan `SUCCESS`
  before declaring M3E evidence complete.

- [ ] **Step 5: Commit only a verified hardening correction.**

  If this task contains an evidence-backed correction, stage only the exact
  paths named by the failing assertion after reviewing `git status --short`,
  then commit with a message naming the defect:

  ```bash
  git commit -m "fix: correct Phase 3 document limit handling"
  ```

  If no correction is needed, do not manufacture a commit. Record the exact
  tested SHA and CI run in the later M3F audit.

## M3F — Independent Phase 3 Audit & Closeout

M3F begins only after M3E has implementation evidence and a clean exact-head
CI result. It is an independent audit/closeout milestone, not permission to
add features.

### Task 12: Fresh-context audit, justified remediation, durable closeout, and integration

**Files:**

- Create only after the read-only audit and any remediation:
  `docs/audits/phase-3-audit.md`
- Modify implementation/tests only for classified, evidence-backed findings.
- Modify `README.md` and `docs/roadmap/project-roadmap.md` only for final
  Phase 3/M3A–M3F status closeout after all required evidence exists.

**Interfaces:** Produces the durable Phase 3 audit, final status evidence, a
  pull request to `main`, a GitHub merge commit preserving the reviewed commit
  history, exact-main post-merge CI evidence, and safe branch cleanup. It does
  not produce new parser behavior or future-phase modules.

- [ ] **Step 1: Start from a fresh context and audit read-only first.**

  Verify branch/base/HEAD identity, complete commit list, changed-file scope,
  approved design and plan, all public interfaces, Phase 1 enum reuse,
  unchanged `SourceDocument`, all four parser paths, exact MIME map, raw-byte
  hash, normalization, warnings, every limit including sparse XLSX row span,
  macro rejection, `keep_links=False`, encrypted/corrupt failure, fixture
  sizes/provenance, dependency diff, focused tests, full gates, and exact-head
  CI. Confirm no HTTP route, storage boundary, migration, order mutation, AI,
  OCR, network call, or Phase 4/5 behavior exists.

- [ ] **Step 2: Maintain a severity finding ledger.**

  Record every finding as `CRITICAL`, `HIGH`, `MEDIUM`, or `LOW` with file,
  exact evidence, affected contract, and disposition. CRITICAL/HIGH findings
  block closeout. MEDIUM findings require remediation or an explicit rationale
  accepted by the human. LOW findings cannot expand Phase 3 scope.

- [ ] **Step 3: Remediate only findings that require action.**

  For each required correction, create the narrow regression assertion first,
  observe RED, implement the minimal fix, observe GREEN, rerun affected
  documents/domain/full gates, and re-audit the exact remediation SHA. Do not
  change the approved design in the audit branch. If a design contradiction is
  found, stop and report it instead of editing the spec silently.

- [ ] **Step 4: Write the durable audit and verify M3F evidence.**

  Write `docs/audits/phase-3-audit.md` with repository, branch, baseline,
  audited exact SHA, findings ledger/verdict, acceptance evidence, commands and
  results, dependency/security/cost notes, fixture provenance, known
  limitations, and the exact Backend/Frontend/Secret scan CI results. Confirm
  all CRITICAL/HIGH findings are zero and every MEDIUM finding is resolved or
  explicitly accepted.

- [ ] **Step 5: Close statuses only after the audit verdict.**

  Update README and roadmap to Phase 3 `COMPLETE` and M3A–M3F `COMPLETE` only
  after the plan review, implementation, tests, self-review, audit, and exact-
  head CI evidence are complete. Keep Phases 4–12 `NOT STARTED`. M3A is not
  closed by writing or committing this plan.

- [ ] **Step 6: Verify, open, merge, and clean up safely.**

  Run the complete regression ladder and `git diff --check`; inspect the PR
  base/head and changed files; create a PR from
  `phase/3-document-ingestion` to `main`; require exact-head CI success; merge
  with a GitHub merge commit, not squash or rebase; fetch remote state; verify
  exact-main CI on the merge commit; confirm the working tree is clean; and
  delete the feature branch only after post-merge verification.

## Regression ladder and implementation evidence

Every implementation milestone uses the smallest relevant command first, then
the broader repository gates:

1. Focused parser command: `uv run pytest tests/unit/documents -q --no-cov`.
2. Domain isolation: `uv run pytest tests/unit/domain -q --no-cov`.
3. Static/format gates: `uv run ruff check .`, `uv run ruff format --check .`,
   and `uv run mypy src/opsflow`.
4. Frontend gate: `make frontend-check` or the repository’s equivalent CI
   frontend lint/build command.
5. Full local gate: `make check` when PostgreSQL/Docker is available.
6. Milestone closeout gate: exact-head GitHub CI with Backend, Frontend, and
   Secret scan all `SUCCESS`.

Do not import FastAPI, the database/session layer, persistence repositories,
or the application order use cases from document tests. No test may call a
live AI provider, network service, shell parser, object store, or external
workbook link.

## Phase 3 Definition of Done

The implementation described by this plan is complete only when the internal
processor accepts small synthetic email/plain-text, CSV, XLSX, and text-based
PDF inputs and produces the same truthful canonical result on repeated runs.
Each result contains the exact raw-byte SHA-256, normalized content, relevant
page/table structure, source metadata/reference, normalized MIME, size, and
honest warnings. Unsupported, mismatched, corrupt, encrypted/unreadable, and
limit-exceeding inputs fail with safe document-specific errors; scanned/no-text
PDFs retain page structure and report warnings without fabricated text.

Focused Phase 3 tests must pass without PostgreSQL, Docker, an API server, an
AI provider, or network access. The full repository regression and exact-head
GitHub CI must pass with Backend, Frontend, and Secret scan all `SUCCESS`. No
LLM, paid service, database migration, HTTP upload route, raw-file storage, or
external network call is permitted by the completed implementation.

## Approved non-goals preserved by this plan

This plan does not authorize `/v1/documents`, multipart upload, raw-file
persistence, object storage, database migration, parsed-content persistence,
order mutation/state processing, duplicate business policy, OCR, `.eml`,
DOC/DOCX, image formats, legacy XLS, a generic XML parser, macros, AI
extraction, Gemini/OpenAI, prompt design, deterministic business validation,
n8n, Gmail, Slack, review UI, authentication work, or any Phase 4+ feature.

The limited `ElementTree.iterparse` use in `xlsx.py` is only a streaming
worksheet/package coordinate safety preflight. It does not create a reusable
generic XML parser or broaden supported input formats.

## Plan self-review checklist

Before committing this plan, perform the following checks against the approved
design and the actual repository files:

| Requirement | Plan coverage |
| --- | --- |
| Phase 3 objective and internal-only boundary | Global Constraints; Tasks 9–11 |
| Existing `SourceDocumentType` reuse and unchanged `SourceDocument` | Global Constraints; Task 1; Task 9 |
| `DocumentInput`, canonical records, parser-result record | Locked public records; Task 1 |
| Error hierarchy and safe diagnostics | Locked errors; Task 1; Tasks 3–11 |
| MIME normalization and exact four-type mapping | Locked helpers; Task 2; Task 9 |
| Exact-byte SHA-256 and metadata order | Global Constraints; Task 2; Task 9 |
| Conservative normalization and BOM handling | Locked helpers; Task 2; Task 3; Task 4; Tasks 6 and 8 |
| Text/email-body behavior and no `.eml` | Task 3 |
| CSV explicit parser, quoting, multiline, ragged rows, zero-row contract | Task 4 |
| XLSX dependency and ZIP/package preflight | Task 5 |
| XLSX expanded-size, sheet, column, populated-cell limits | Tasks 5–6 |
| XLSX sparse per-sheet row-span limit before materialization | Global Constraints; Task 5 tests/algorithm; Task 6 tests/algorithm |
| XLSX formula/scalar determinism and structural empties | Task 6 |
| Macro rejection and external-link safety | Tasks 5–6 |
| PDF dependency, signature, page ordering/count | Task 7 |
| PDF warnings, corruption/encryption, no fabricated OCR | Task 8 |
| Final canonical text-size limit and dispatcher | Task 9 |
| Determinism/no timestamp/random/environment/network | Tasks 2, 6, 8–10 |
| Synthetic committed fixtures and generated limit inputs | Tasks 3–8 |
| Minimal dependency sequencing | Dependency sequencing; Tasks 4–7; Task 10 |
| Infrastructure-independent focused tests | Global Constraints; Tasks 9–11 |
| Security posture and Phase 4/5 boundary | Global Constraints; Tasks 5–11 |
| Explicit non-goals | Approved non-goals section; Tasks 9–12 |
| M3B–M3F milestone contract/status transitions | Status protocol; milestone sections; Task 12 |
| Independent audit, remediation, merge commit, exact-main CI, cleanup | Task 12 |
| Measurable Phase 3 Definition of Done | Tasks 3–11 and Task 12 evidence |

Run these plan-quality checks before committing:

- Scan the plan for unresolved placeholders and prohibited generic wording; the
  scan must find none.
- Verify every helper, record, exception, limit field, parser signature,
  renderer, and dispatcher name is defined before its first task reference.
- Verify every parser returns `_ParsedDocumentContent`, every warning uses
  `DocumentWarning`, every `DocumentLimits` field matches the locked spelling,
  and `CanonicalDocument` construction occurs only in the dispatcher.
- Verify every production-behavior task has RED, expected failure, minimal
  GREEN implementation, targeted command, regression command, self-review,
  and commit instructions.
- Verify no task creates an HTTP/storage/persistence boundary, changes Phase 1
  or Phase 2 behavior, adds a third-party dependency outside openpyxl/pypdf,
  creates giant fixtures, or begins M3B while this plan is being written.
- Verify all Markdown links resolve to repository files or documented external
  references, then run `git diff --check`.

## Execution note

The Phase 3 design is human-approved. This implementation plan still requires
independent review. After plan review passes, M3A can be closed; implementation
begins with M3B. Execution must use the single-agent sequential workflow and
`superpowers:executing-plans`. This plan-writing task does not begin M3B and
does not mark M3A complete.
