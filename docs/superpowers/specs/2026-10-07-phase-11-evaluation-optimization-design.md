# Phase 11 M11A — Evaluation Contract & Benchmark Design

## Status and authority

This document is the authoritative M11A design for Phase 11 — Evaluation &
Optimization. M11A design is `APPROVED` at
`bde63c54a66486aea8c1e7292887d004bf9e91f4`; the implementation plan is
`APPROVED` at `1e8c152aa072b075f059020ca232889ad2bcfa91`; M11A overall is
`COMPLETE`. M11A completed the design and implementation-planning gate only;
M11B — Synthetic Ground-Truth Corpus & Scoring Foundation is `COMPLETE` at
independently reviewed technical baseline
`c5b33dd2c0d71263552ea9085fc6e3f5985ad17d`. M11B completed only the versioned
36-case synthetic corpus, trusted synthetic catalog, corpus integrity/ground-truth
contracts, canonical extraction scorer, validation scorer, and result contracts;
it did not implement the full evaluation runner, application-level reliability
execution, release-gate execution, evaluation database lifecycle, latency
benchmark execution, live Gemini evaluation, token/cost calculation, reference
result generation, optimization, or the Phase 11 audit. M11C — Correctness,
Routing & Reliability Evaluation is `COMPLETE` at independently reviewed
technical baseline `ce456f2928ed9773f26ec65dfa5776d29dd4e915`; M11C delivered
Tasks 5–7 on active corpus `3.0.0`. M11D — Performance, Token & Cost Evaluation is `IN PROGRESS`; M11E–M11F remain `NOT STARTED`. Phase 11
remains `IN PROGRESS` and Phase 12 remains `NOT STARTED`. This document defines
the evaluation contract and implementation boundary; it does not implement
the evaluator.

The design is grounded in the repository at starting SHA
`712aa04312cf1e2ebba85f60f2319765057bc211`, the exact `main` and
`origin/main` used to create branch `phase/11-evaluation-optimization`.

### Current M11C corrective amendment

M11B was originally approved with corpus `1.0.0`. M11C Task 5 exposed an
authority contradiction in the `retry-email-001` and `retry-csv-001` recovery
expectations: retry and deterministic validation stop at `READY_FOR_APPROVAL`
until an explicit human approval action. The approved executable correction was
corpus `2.0.0` at amendment SHA
`1bdd3763bd00e73a28a8eacb148f803d03ea7bfe`; only those two expected final
states changed, and no source bytes or SHA-256 values changed. The subsequent
duplicate replay-contract amendment is recorded below.

The current status is intentionally separate from historical Phase 10 audit
records. The Phase 10 audit remains an immutable record of its own closeout and
is not rewritten to reflect the start of Phase 11.

### Current duplicate replay-contract amendment

Corpus `2.0.0` is the approved active corpus through amendment SHA
`1bdd3763bd00e73a28a8eacb148f803d03ea7bfe`. M11C real-path duplicate execution
showed that Phase 2 creation replay and Phase 7 intake execution expose
distinct production dispositions: `REPLAYED_EXISTING` and `STANDING_DOWN`.
Corpus `2.0.0` encoded those layers in one ambiguous field. Corpus `3.0.0`
splits the expectations without changing production behavior, source documents,
or source SHA-256 values. The corpus `3.0.0` amendment is approved at
`7184efb9589445d16e354decd486f28bc90ac09b`; all further Phase 11 evaluation
execution uses corpus `3.0.0`. At that amendment, M11C remained `IN PROGRESS`;
M11D–M11F remained `NOT STARTED`; Phase 11 remained `IN PROGRESS`; Phase 12
remained `NOT STARTED`. M11C was subsequently completed at approved technical
baseline `ce456f2928ed9773f26ec65dfa5776d29dd4e915`; see the implementation
plan for the closeout evidence.

Normative words such as **MUST**, **MUST NOT**, **SHOULD**, and **MAY** state
the implementation contract for M11B–M11F.

## 1. Purpose, scope, and decisions

Phase 11 exists to produce quantitative evidence rather than screenshots,
anecdotes, or production-accuracy claims unsupported by measurement. M11A
ratifies one evaluation system for the existing OpsFlow flow:

```text
synthetic source -> canonical parser -> extraction -> deterministic validation
-> persisted route/state -> optional human approval -> provider-free execution
-> durable notification/sync evidence -> structured result -> Markdown report
```

The harness evaluates:

- canonical parsing of the four supported benchmark source forms;
- structured business-field extraction against versioned human-authored ground
  truth when the provider is real;
- extraction-schema and evidence-grounding behavior when the provider is fake;
- deterministic validation issues, route, approval level, and state;
- invalid pass-through, malformed/security handling, and AI authority;
- duplicate/replay blocking, intake ownership, retry recovery, and durable
  order-sync receipts;
- execution eligibility and logical external-object uniqueness using test
  doubles;
- local deterministic latency, provider-free end-to-end intake latency, and
  opt-in live Gemini latency;
- provider call counts, authoritative token usage, and dated estimated model
  cost when those values exist.

The harness MUST NOT evaluate live Odoo, HubSpot, Gmail, Slack, or n8n
performance. Existing provider-specific sandbox and workflow-contract tests
remain their own integration evidence; M11 is concerned with a single
quantitative evaluation contract and its provider-free safety boundary.

The first implementation MUST use the smallest clean modules that satisfy the
contract. It MUST NOT introduce a benchmark framework, evaluation SaaS,
dashboard, queue, model router, or production observability replacement.

## 2. Repository reconnaissance and evidence-gap findings

### 2.1 Starting-state verification

Before branch creation, the repository satisfied every M11A precondition:

| Check | Evidence |
| --- | --- |
| Local branch | `main` |
| Local `main` | `712aa04312cf1e2ebba85f60f2319765057bc211` |
| `origin/main` | `712aa04312cf1e2ebba85f60f2319765057bc211` |
| `HEAD` before branch creation | `712aa04312cf1e2ebba85f60f2319765057bc211` |
| Worktree | clean |
| M10A–M10F and Phase 10 | `COMPLETE` in current roadmap/development status |
| Phase 11 | `NOT STARTED` before this milestone |
| Phase 12 | `NOT STARTED` |

The branch created from that exact commit is
`phase/11-evaluation-optimization`.

### 2.2 Existing seams that evaluation MUST consume

| Evidence | Existing source | Evaluation use |
| --- | --- | --- |
| Canonical input | `process_document(DocumentInput)` and `CanonicalDocument` in `src/opsflow/documents/` | Parse outcome, canonical text/table/page output, SHA-256, warnings, and parse timing |
| Extraction output | `OrderExtractor.extract()` returning `ExtractionDraft`; persisted `ExtractionSnapshotModel.payload` serialized by `extraction_draft_to_payload()` | Business-field prediction, source identity, ordered lines, and schema/evidence outcome |
| Provider boundary | `LLMProvider`, `StructuredGenerationRequest`, `StructuredGenerationResult` | Provider substitution; live mode uses `GeminiProvider` |
| Fake provider | `FakeProvider` and its request list | Provider-free scripted extraction and operational call evidence; it is not real model accuracy |
| Gemini usage | `GeminiProvider` reads `usage.total_input_tokens`, `total_output_tokens`, and `total_tokens` from the installed SDK and emits `provider_call_completed` | Live token fields and provider diagnostics, only when values are authoritative |
| Deterministic route | `ValidationResult.route` and `approval_level` from `opsflow.validation.engine.validate()` | Route and approval scoring |
| Validation issues | `ValidationResult.issues`, `ValidationIssueModel`, and the ordered persisted issue rows | Issue-code/severity comparison and durable-result inspection |
| Order state | `Order.state`, `OrderModel.state`, and `OrchestrationIntakeResult.state` | Pre-approval and final-state scoring |
| Intake disposition | `OrchestrationIntakeResult.idempotent_replay` and `execution`, plus Phase 2 creation disposition and Phase 7 claim kind | Replay, stand-down, claim, and duplicate evidence |
| Review/approval | `review_commands.py`, review authorization, state transition, audit events, and notification-intent creation | Explicit approval boundary and execution-eligibility probe |
| Notifications | `NotificationDelivery`, `NotificationDeliveryModel`, `claim_next_notification()`, and `record_notification_outcome()` | Durable notification status, attempts, failure code, and isolation from order state |
| Order sync | `OrderSyncStepExecutor`, `OrderSyncStepResult`, `OrderSyncModel`, and `OrderSync` receipt fields | Step outcomes, retry/recovery, receipt durability, and stable-identity replay |
| Observability | M10D `Observability`, `StructuredEventLogger`, `MetricsRegistry`, and `duration_ms()` | Cross-check of provider/intake/notification/sync diagnostics; not a second result store |
| Existing source fixtures | `fixtures/documents/{text,csv,xlsx,pdf}` and `fixtures/phase7/synthetic-order.txt` | Parser examples and fixture conventions only |
| Existing test doubles | `FakeProvider` and local fakes in Phase 7–10 tests | Protocol and behavior references only; they MUST NOT be copied as ground truth or assumed to be reusable production behavior |
| Commands/CI | `Makefile`, `pyproject.toml`, `.github/workflows/ci.yml`, `uv.lock`, and standard `pytest`/Ruff/mypy conventions | Future command names and CI boundary |

### 2.3 Measurements that need an M11 seam

M10D already records bounded process-local diagnostics, but those metrics reset
on process restart and are not scoped to a corpus case or evaluation run. M11
therefore adds evaluation-side collection without changing production
observability:

1. A run-scoped provider wrapper records one extraction attempt, monotonic
   duration, outcome, and the `StructuredGenerationResult` token fields.
   Counts and latency come from this wrapper. It does not infer tokens.
2. Provider-free business-data, notification, and order-sync doubles record
   calls, outcomes, stable logical identities, and receipts in memory. Existing
   test helpers are not treated as production adapters.
3. The runner measures direct parser, pure deterministic-validation, and
   provider-free end-to-end timings around existing functions. It does not
   mutate process metrics just to obtain benchmark numbers.
4. The runner serializes the actual `ValidationResult`, `OrderModel`, issue
   rows, notification rows, sync rows, receipts, audit state, and orchestration
   disposition into bounded result summaries. Raw document text, raw provider
   response bodies, credentials, and provider diagnostics are excluded.
5. A dated pricing snapshot is a new evaluation artifact in M11D. It is not
   production configuration and contains no secret.

No production seam is required merely to score extraction, routing, order
state, validation issues, notification outcome, sync outcome, receipts, or
replay disposition. The evaluation runner MUST adapt the existing contracts
instead of adding a second production state machine or observability system.

## 3. First-class evaluation architecture

OpsFlow will have one first-class harness with six conceptual responsibilities.
M11B–M11D MAY use functions, dataclasses, and small modules rather than a
large class hierarchy.

### 3.1 Evaluation corpus

Loads a versioned manifest, source bytes, trusted-data fixture, and expected
outcomes. It validates that every referenced file has the declared SHA-256,
that every case has a stable ID and valid tags, and that the ground truth is
independent of the provider under test.

### 3.2 Evaluation runner

Runs one case through the selected seams, applies only manifest-directed human
approval/retry/replay actions, collects bounded actual evidence, and returns a
case result. Provider-free mode is the default. Live mode changes only the
extraction provider and its evidence label.

### 3.3 Scorers

Pure deterministic functions calculate the defined extraction scorer rules,
parsing, route, issue, safety, duplicate, retry, eligibility, latency, token,
and cost metrics from case ground truth plus actual summaries. Scorers MUST
not call a provider, database, clock, filesystem, or external service. The
extraction scorer may be unit-tested with scripted expected/predicted fixtures,
but its business-field comparison is published as extraction quality only when
the actual summaries came from `live_gemini`; provider-free results expose
contract evidence instead.

### 3.4 Measurement collectors

Run-scoped wrappers and timers capture provider attempts, authoritative usage
fields, direct elapsed durations, adapter calls, durable outcomes, and logical
external objects. A collector MUST represent unavailable data as `null` plus a
missing-value count, never as zero.

### 3.5 Result model

Produces one JSON result artifact containing run identity, corpus identity,
environment, case observations, aggregate metrics, release gates, pricing
identity, and limitations. This JSON is the sole source of truth for reporting.

### 3.6 Report renderer

Reads one structured result artifact and renders the human-readable quantitative
Markdown report. It MUST NOT recalculate metrics from the corpus, database,
logs, or provider output.

## 4. Evaluation modes and side-effect boundary

### 4.1 Mandatory provider-free mode

Provider-free evaluation:

- requires no Gemini credential and makes no Gemini network call;
- requires no Gmail, Slack, Odoo, HubSpot, or n8n service;
- uses synthetic source files, scripted providers, deterministic trusted-data
  fixtures, provider-free notification/sync doubles, and isolated local
  PostgreSQL;
- exercises real Python parsing, validation, routing, persistence, review,
  claim/recovery, notification, and order-sync application contracts where a
  case requires them;
- costs `$0` in mandatory development services;
- is reproducible from a clean clone with the committed corpus and standard
  repository dependencies;
- reports fake provider calls as operational fake calls only; they MUST NOT be
  labeled Gemini calls, Gemini accuracy, Gemini latency, Gemini token usage, or
  Gemini cost.
- executes the complete 36-case corpus and all represented release-gate cases;
- MUST NOT publish scripted-provider business-field comparison as an
  extraction-quality score. In provider-free results, live/model extraction
  exact match, field TP/FP/FN, field precision, field recall, field F1, and
  per-field extraction quality are `NOT_APPLICABLE`/`null`;
- records the limitation/reason exactly as a no-real-model-evaluated
  limitation, such as `No real model was evaluated; scripted provider output
  is not an extraction-quality score.`

It is the release-gate mode. It measures corpus/schema validity, parsing,
deterministic validation/routing, invalid pass-through, duplicate prevention,
retry/recovery, approval and execution eligibility, durable replay behavior,
local timing, and deterministic call counts.

Provider-free mode MAY report deterministic extraction-contract evidence,
including provider-schema acceptance, parser success, evidence grounding,
source identity, extraction persistence round-trip, scripted-provider call
count, and scorer self-test evidence. These are contract/operational results;
none may be labeled `accuracy`, `precision`, `recall`, `F1`, or model quality.
M11B MAY unit-test the scorer with deterministic expected/predicted fixtures,
but those tests are scorer evidence and never benchmark quality evidence.

### 4.2 Explicit live Gemini mode

Live mode is `live_gemini` and is never selected by default. It:

- requires an explicit command and `OPSFLOW_EVALUATION_LIVE_GEMINI=1`;
- requires nonblank `OPSFLOW_GEMINI_API_KEY`, nonblank
  `OPSFLOW_GEMINI_MODEL`, and a valid positive
  `OPSFLOW_GEMINI_TIMEOUT_SECONDS`;
- validates all four requirements before the first corpus case; an absent,
  blank, malformed, non-finite, or non-positive value is a preflight error;
- uses the existing `GeminiConfig`/runtime validation semantics and does not
  introduce a separate evaluation default or fake fallback;
- uses the real `GeminiProvider` and the same versioned 36-case corpus, source
  ground truth, prompts, schema, and deterministic downstream flow as
  provider-free mode;
- never silently falls back to `FakeProvider`; a fallback is an error and the
  result MUST be marked unsuccessful rather than labeled live;
- records real extraction quality only for extraction cases that actually
  reached the real Gemini provider; the result identifies that denominator and
  the corpus cases that did not reach it;
- records real provider latency, call count, and authoritative SDK usage
  fields when present;
- uses fake trusted business data and fake downstream adapters, so it does not
  benchmark live Odoo, HubSpot, Gmail, Slack, or n8n;
- includes a dated pricing snapshot only for transparent estimated cost.

Provider-free and live runs share the corpus version and source ground truth,
but they do not share a quality denominator by implication. A deterministic
provider fault injection that cannot meaningfully coexist with a real Gemini
call remains provider-free scenario evidence; it MUST be labeled as such and
MUST NOT be presented as a fault produced by Gemini in a live report.

A real live Gemini reference run is strongly expected before Phase 11 can
close because real extraction F1 and estimated model cost per initial order are
commercially meaningful evidence. If it is unavailable, the Phase 11 reference report
MUST state that real LLM extraction and cost evidence are unavailable. A
fake-provider result MUST NOT substitute for those claims.

## 5. Corpus and ground-truth contract

### 5.1 Versioning and size

M11B MUST create a manifest-backed corpus at version `1.0.0` with exactly 36
high-signal cases. The target is deliberately small enough for human review
and broad enough to cover the current contracts; near-duplicate padding is not
allowed.

The primary category distribution is:

| Primary category | Cases |
| --- | ---: |
| `normal` | 10 |
| `edge` | 8 |
| `security` | 4 |
| `deterministic_violation` | 7 |
| `duplicate` | 4 |
| `retry_recovery` | 3 |
| **Total** | **36** |

The format distribution is nine cases each for:

- `EMAIL_BODY` with a `.txt` source and `text/plain` MIME type; this is the
  repository's supported text/TXT representation;
- `CSV` with `text/csv`;
- `XLSX` with
  `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`;
- `PDF` with `application/pdf`.

The manifest MUST use exactly the existing source document enum values. It
MUST NOT introduce a `TXT`, DOCX, image, OCR, or other unsupported format.
Each case has one primary category and MAY have additional tags only when a
tag changes reporting or explains a contract boundary, such as
`missing_optional_field`, `line_order`, `prompt_injection`,
`duplicate_source_sha`, `duplicate_customer_po`, `lost_receipt`, or
`stale_claim_recovery`.

`corpus_version` is a semantic version string in the manifest and in every
result. Any change to source bytes, expected extraction, trusted fixture,
expected route/issue/state, case membership, or case tags increments the
corpus version. A patch version is for non-semantic manifest metadata changes;
a minor version adds cases or non-breaking tags/fields; a major version changes
the case contract or removes/changes an existing case. Every changed source
file gets a new declared SHA-256. Results retain the exact corpus version and
Git SHA from which they were produced.

### 5.2 One evaluation case

One case is one stable synthetic source identity plus its human-authored
expected business and deterministic outcomes. A duplicate or retry scenario
may contain a manifest-directed sequence of attempts, but it remains one case
with one `case_id` and one scenario group.

The minimum JSON manifest shape is:

```json
{
  "schema_version": "opsflow-evaluation-corpus/v1",
  "corpus_version": "1.0.0",
  "cases": [
    {
      "case_id": "normal-email-001",
      "primary_category": "normal",
      "tags": ["normal"],
      "source": {
        "path": "documents/normal-email-001.txt",
        "document_type": "EMAIL_BODY",
        "mime_type": "text/plain",
        "sha256": "0000000000000000000000000000000000000000000000000000000000000000"
      },
      "expected_extraction": {
        "customer_name": "Example Buyer",
        "customer_reference": "CUST-001",
        "po_number": "PO-1001",
        "order_date": "2026-10-01",
        "requested_delivery_date": "2026-10-15",
        "currency": "USD",
        "notes": null,
        "lines": [
          {
            "sku": "SKU-001",
            "description": "Widget",
            "quantity": "2",
            "submitted_price": "10.00"
          }
        ]
      },
      "trusted_business_data": {
        "fixture_path": "trusted-data/normal-email-001.json",
        "facts": {
          "duplicate_customer_po": false,
          "document_already_processed": false
        }
      },
      "expected_validation": {
        "route": "READY_FOR_APPROVAL",
        "approval_level": "STANDARD",
        "issue_codes": [],
        "issue_severities": {},
        "pre_approval_state": "READY_FOR_APPROVAL",
        "external_execution_eligible": false
      }
    }
  ]
}
```

The example uses an all-zero digest for shape illustration only; M11B MUST
commit the real SHA-256 for every source file. The following rules complete the
contract:

- `case_id` is unique within a corpus version, stable lowercase ASCII with
  `-` separators, and never generated from a model response.
- `source.path` is relative to the corpus version directory. The runner MUST
  reject path traversal and a digest mismatch.
- `expected_extraction` contains the canonical business projection described
  in Section 6. It excludes evidence/provenance because evidence text is not a
  business-field exact-match requirement. It is required for extraction cases
  and omitted only for parser-only or failure cases where no extraction is
  expected.
- `trusted_business_data` is required when deterministic validation runs. The
  referenced JSON fixture is a small synthetic catalog/lookup dataset, not a
  precomputed answer for the expected extraction. It contains the synthetic
  customer records and product records needed for exact customer-reference
  lookup, normalized-exact customer-name lookup when reference is absent,
  exact SKU lookup, product active state, currency, catalogue price, and
  available quantity. It does not contain an ordered product answer keyed to
  expected lines.
- The evaluation provider MUST implement the existing
  `BusinessDataProvider.get_validation_data(BusinessDataLookupRequest)`
  contract. It MUST build `TrustedBusinessData` from the actual lookup request
  derived from the predicted draft, never from `expected_extraction`.
- For that request-driven lookup, an incorrect predicted customer reference
  returns no customer candidate unless that incorrect reference genuinely exists
  in the fixture. An incorrect predicted customer name returns no candidates or
  the candidates allowed by the existing normalized-name rule. An incorrect or
  unknown predicted SKU returns `None` at that predicted line position, and a
  missing predicted SKU also returns `None`. `products_by_line` always has the
  same length and order as the actual predicted line list, and every non-`None`
  returned product SKU equals the requested predicted SKU. Customer candidates
  use the existing canonical provider ordering.
- The fixture provider MUST validate the same request/result pairing and line
  cardinality invariants as the application contract. Expected extraction
  values MUST NOT select, repair, or rescue trusted lookup results.
- The `facts` object supplies existing `ValidationFacts` booleans. Duplicate
  customer+PO and document/source facts remain manifest-directed OpsFlow-local
  facts where appropriate; they are not reference-data lookup results.
- `expected_validation.route` is the existing `ValidationRoute` value,
  `approval_level` is the existing `ApprovalLevel` value when the case reaches
  validation, and `issue_codes`/`issue_severities` use existing deterministic
  rule codes and severity values. The issue code comparison is a canonical
  multiset comparison, so storage ordering does not create a false failure.
- `pre_approval_state` is the expected durable `OrderState` immediately after
  intake, extraction, and deterministic validation, before any human command.
- `external_execution_eligible` is the expected value at the explicit
  execution probe. A case with `false` MUST NOT call an external adapter. A
  case with `true` includes a manifest-directed authorized approval step and
  is evaluated with provider-free external doubles.
- `approval` is present only when the case exercises approval. It identifies
  the deterministic human role/action and expected `APPROVED` state; the
  runner supplies the actor from a test configuration, not from the document
  or provider output.
- `replay` is present for duplicate cases and contains a stable
  `duplicate_group_id`, the seed case/identity, the number of replay attempts,
  and the expected `REPLAYED_EXISTING` or `STANDING_DOWN` disposition.
- `recovery` is present for retry cases and contains the injected stage,
  bounded failure code, expected resume origin, expected durable outcome,
  expected final state, and whether prior receipts must remain unchanged.
- Irrelevant optional objects are omitted; they are not populated with empty
  placeholders merely to make every row look identical.

Ground truth MUST be readable in review, committed as data, and edited by a
human. No model, evaluator prediction, generated report, or live provider may
generate or update expected values.

### 5.3 Corpus validity gates

Before scoring, the runner MUST fail corpus validation if any of the following
occurs: duplicate case ID, unsupported type/MIME pair, missing source file,
digest mismatch, missing primary category, missing required extraction field
for an extraction case, malformed canonical decimal/date, invalid route, state,
issue, or approval enum, missing trusted fixture for a validation case,
duplicate replay-group identity, or recovery data that cannot identify one
bounded failure and expected outcome.

## 6. Canonical extraction and metric contract

### 6.1 Canonical business projection

Predicted and expected `ExtractionDraft` values are serialized into the same
business projection used by the existing persistence mapper:

```text
customer_name
customer_reference
po_number
order_date
requested_delivery_date
currency
notes
lines[i].sku
lines[i].description
lines[i].quantity
lines[i].submitted_price
```

`source.sha256`, `source.document_type`, and `evidence` are not part of the
business projection. Source identity is checked separately, and evidence is
checked by its own deterministic validity result.

Canonicalization MUST happen before every extraction comparison:

- `None` remains `null`; blank optional strings are invalid upstream and are
  not converted into a value;
- strings are Unicode NFC-normalized; identifiers (`customer_reference`,
  `po_number`, `currency`, `sku`) remain case-sensitive and are not case-folded,
  trimmed, or fuzzy-matched;
- dates use exact ISO `YYYY-MM-DD` values;
- finite `Decimal` values compare by numeric `Decimal` equality, so `10`,
  `10.0`, and `10.00` are one value; binary floating point is never used;
- line items remain in their existing ordered tuple/list position. Lines are
  never matched by SKU, description, or nearest value;
- `notes` and descriptions use the same NFC-normalized exact string comparison;
- evidence location and quote are excluded from business exact match but the
  existing `validate_evidence()` rules determine evidence validity.

No fuzzy, edit-distance, case-insensitive, tolerance, or semantic matching is
allowed in M11B. Such a change requires a later contract revision supported by
baseline evidence; it is not an implementation convenience.

### 6.2 Complete extraction exact match

The canonical scorer rules below are testable with deterministic fixtures, but
the report may populate extraction-quality values only in `live_gemini` mode.
For a live run, `E_live` is the set of extraction cases for which the real
Gemini provider boundary received at least one call. The result MUST report
`E_live`'s case count and case IDs (or a bounded equivalent), including cases
where the call failed or produced no prediction. Cases that never reached the
real provider are outside the live extraction-quality denominator and are
identified as unavailable evidence. A provider-free run has no extraction-
quality denominator.

For `live_gemini`, complete extraction exact match over `E_live` is:

```text
100 * count(case in E_live where canonical predicted business projection
                   == canonical expected business projection) / count(E_live)
```

The live denominator includes every reached case with `expected_extraction`,
including a case whose expected value is `null` or whose expected line list is
empty. A provider failure, schema failure, or missing prediction is not an
exact match. Evidence/provenance text MUST NOT make a business-field exact
match fail. A business-field mismatch MUST fail it even if the evidence quote
is valid. The report includes numerator, denominator, and percentage; it does
not publish an unqualified metric named only `accuracy`.

In `provider_free`, `complete_exact_match` is `null` with status
`NOT_APPLICABLE`, not a scripted-provider percentage. Its limitation/reason
MUST identify that no real model was evaluated.

### 6.3 Field-value micro precision, recall, and F1

The scorer converts each canonical projection into a set of field/value facts.
The fact key is the exact field path, including the zero-based line position:

```text
customer_reference = "CUST-001"
lines[0].sku = "SKU-001"
lines[0].quantity = Decimal("2")
```

For every expected/predicted field path:

- an equal expected and predicted non-null value is one true positive;
- an expected non-null value with no equal prediction is one false negative;
- a predicted non-null value with no equal expected value is one false
  positive;
- a wrong value at the same field path contributes one false negative for the
  expected fact and one false positive for the predicted fact;
- an expected non-null field absent because a line or field was omitted is one
  false negative;
- a predicted non-null field where expected is `null` is one false positive;
- both expected and predicted `null` contribute no positive fact and no error;
  complete exact match still requires the null agreement;
- an extra predicted line contributes one false positive for each non-null
  field it contains; missing expected line fields contribute false negatives;
- duplicate predicted facts are counted once after canonicalization and the
  duplicate is recorded as a malformed prediction rather than inflating TP.

Across all facts in the selected set:

```text
micro_precision = TP / (TP + FP), or null when TP + FP = 0
micro_recall    = TP / (TP + FN), or null when TP + FN = 0
micro_f1        = 2 * precision * recall / (precision + recall),
                  or null when precision + recall = 0
```

The scorer reports integer TP/FP/FN and decimal percentages for `live_gemini`.
The mandatory field set includes:

- `customer_reference`;
- `po_number`;
- `order_date`;
- `requested_delivery_date`;
- `currency`;
- `lines[].sku`;
- `lines[].quantity`;
- `lines[].submitted_price`.

The report also includes `customer_name`, `lines[].description`, and `notes`
when represented. `lines[].field` is a reporting label; scoring uses the exact
positioned paths. There is no macro average across fields or cases unless a
future contract defines a new denominator and names it explicitly.

Only `live_gemini` may populate complete extraction exact match, field TP/FP/FN,
micro precision, micro recall, micro F1, or per-field extraction quality in an
evaluation result. In `provider_free`, all of those quality fields are
`null`, with `status: "NOT_APPLICABLE"`; deterministic scorer self-tests are
reported separately from the evaluation-quality result.

### 6.4 Additional extraction contract metrics

The provider-free run reports, without calling them model accuracy:

- canonical parser pass/fail by source type;
- strict provider-schema acceptance/rejection;
- evidence-grounding pass rate for scripted extraction payloads;
- source-identity match rate between document SHA/type and `ExtractionDraft`;
- extraction persistence round-trip validity.

Only live Gemini results may be labeled `live Gemini extraction exact match`,
`live Gemini field precision/recall/F1`, per-field extraction quality, or `live
Gemini latency`. A fake payload is never `Gemini accuracy`, even when its
scripted prediction exactly equals the expected extraction.

## 7. Deterministic routing, safety, and reliability metrics

### 7.1 Correct deterministic routing

For the route-case set `R`, a case is correctly routed only when:

1. actual `ValidationResult.route` equals expected `route`;
2. actual `ApprovalLevel` equals expected `approval_level` when specified;
3. the durable `pre_approval_state` equals expected `pre_approval_state`; and
4. the canonical issue-code/severity multiset equals the expected issue set.

```text
routing_accuracy = correct route cases / all route cases
```

The report includes the full-set result and a separate
`deterministic_violation` subset. A route is not considered correct merely
because the final HTTP response has a familiar status code.

### 7.2 Invalid pass-through

An invalid deterministic case is any case whose manifest route or issue truth
requires `NEEDS_REVIEW`, a deterministic failure, or
`external_execution_eligible=false`. Invalid pass-through counts one failure
if the actual flow reaches `APPROVED`, `SYNCING`, or `COMPLETED`, invokes an
external execution adapter, or reports execution eligibility when the manifest
says false.

```text
invalid_pass_through_rate = invalid cases that passed incorrectly / invalid cases
```

The release gate requires the numerator to be zero. Review/approval
notifications for an invalid case are not themselves an invalid pass-through;
the manifest and durable notification row must show the correct review route.

### 7.3 Duplicate blocking and replay

Each replay attempt in a `duplicate_group_id` is one denominator item; the seed
creation is not scored as a duplicate. A duplicate attempt passes only when all
of the following hold:

- no additional authoritative `orders` row or new source/order graph exists;
- the result reports the expected replay or stand-down disposition and keeps
  the original `order_id`;
- no extraction/provider work occurs after a live active-owner stand-down;
- no notification intent or order-sync intent is created solely by the
  duplicate attempt;
- provider-free external logical-object counts remain unchanged.

```text
duplicate_blocking_rate = passing duplicate attempts / duplicate attempts
```

The metric is about logical business effects, not physical HTTP exactly-once.
For live external systems, which are outside Phase 11, the report makes no
claim beyond this provider-free logical test.

### 7.4 Retry recovery

A retry case passes when the injected retryable failure produces the manifest's
expected durable failure, the authorized retry resumes the recorded origin or
the first missing sync step, and the final durable state matches the expected
recovery outcome. For order sync, successful prior receipts MUST remain
unchanged and the recovery MUST not repeat a completed logical step merely
because a later receipt was missing. For intake, a valid stale-ownership
recovery MUST retain the original source/idempotency identity and reject the
old fence.

```text
retry_recovery_rate = passing recovery cases / retry recovery cases
```

The result records failure code, attempt count, retry generation, resume point,
final state, receipt summary, and replay/stand-down disposition. A retry that
eventually succeeds after an unbounded or unauthorized extra owner is a
failure, not a success.

### 7.5 Execution eligibility and external logical duplication

The execution probe records whether the current order is eligible for external
execution and the calls made by the provider-free Odoo/HubSpot doubles.

- A case with `external_execution_eligible=false` passes only with zero Odoo
  and HubSpot mutation calls and zero logical external objects.
- A case with `true` must have an explicit deterministic/human approval step,
  then may execute the fixed Phase 9 step sequence through doubles.
- Each stable OpsFlow order identity may have at most one logical Odoo order,
  one HubSpot Deal, and one Company per stable trusted customer reference.
- A lost-response replay may call the adapter again, but it passes only when
  stable identity converges to the existing logical object and the persisted
  receipt is the same logical identity.

```text
execution_safety_rate = cases with eligibility, approval, and effect result
                       matching ground truth / execution cases
logical_duplication_count = sum(max(0, logical_objects_for_identity - 1))
```

### 7.6 Malformed-input safety

For each `security` and malformed `edge` case, the manifest defines the
expected bounded safe outcome. A case passes when parsing/schema handling or
the deterministic flow terminates in that outcome, produces no automatic
execution, and exposes no raw document text, prompt content, provider body,
credential, SQL, or traceback in the bounded result summary or captured
application event. The expected outcome may be a parser failure, `FAILED_FINAL`,
or `NEEDS_REVIEW` only when the manifest explicitly says so.

```text
malformed_security_safe_rate = passing malformed/security cases /
                               represented malformed/security cases
```

### 7.7 AI authority

AI-authority cases use a scripted extraction payload and/or source text that
contains approval-like or instruction-like content. The runner instruments the
side-effect boundary and asserts that neither document text nor provider
output directly calls or authorizes:

- approval or rejection;
- operator role selection;
- notification business eligibility;
- Odoo or HubSpot mutation;
- retry ownership or retry generation.

The only accepted authority path is deterministic validation plus an explicit
human review command plus durable sync eligibility. This is a deterministic
contract assertion, not an LLM judge. The gate numerator is the count of any
direct LLM-authorized side effect and MUST be zero.

## 8. Latency and observability methodology

### 8.1 Separate latency categories

The report MUST keep these categories separate:

1. `parse_ms`: monotonic elapsed time around `process_document()` for a case
   whose input is supported and parseable.
2. `deterministic_validation_ms`: monotonic elapsed time around the pure
   `validation_engine.validate()` call with canonical draft, trusted fixture,
   facts, policy, and fixed `ValidationContext` already available.
3. `provider_free_intake_ms`: monotonic elapsed time around one real Python
   orchestration application invocation using fake extraction/trusted data and
   isolated PostgreSQL. Database setup, migration, fixture creation, and
   process startup are excluded.
4. `live_gemini_call_ms`: monotonic elapsed time around each real
   `GeminiProvider.generate_structured()` invocation. It is present only in
   `live_gemini` mode.
5. M10D `intake_duration_ms`, `provider_duration_ms`, notification duration,
   and order-sync step duration are diagnostic cross-checks when the app is
   exercised through its existing runtime observer. They are not summed into a
   second production metric and do not replace the run-scoped timers.

The report MUST NOT publish a single field called `OpsFlow latency` without a
category and sample definition. These timings describe the local evaluation
environment; they are not a production SLA.

### 8.2 Samples and percentile calculation

One normal evaluation invocation runs each manifest case once. There is no
unreported warm-up. A direct timing sample is recorded only when that stage is
reached; setup/migration time is excluded. Provider-free intake percentiles use
one first-attempt sample per non-duplicate intake case. Duplicate/replay and
recovery timings are reported by scenario, not silently mixed into the normal
intake percentile. Live Gemini latency uses one sample per actual provider
call.

For a non-empty sample list of `n` values, sort ascending and use the
nearest-rank percentile:

```text
rank(p) = max(1, ceil((p / 100) * n))
percentile(p) = sorted_samples[rank(p) - 1]
```

This method is used for p50 and p95. It performs no interpolation. A missing
sample set produces `null` percentile values and a `sample_count` of zero.
The result records sample count, min, max, p50, p95, and sum where available.

### 8.3 Environment metadata

Every result records only contextual, non-personal fields:

- Python version;
- operating-system/platform string and CPU architecture;
- evaluation UTC timestamp;
- corpus version;
- Git SHA;
- evaluation mode;
- database engine/version family (`PostgreSQL 16` when using the repository
  Compose/CI service);
- sample counts and provider/model identifier where applicable;
- the relevant dependency-lock identity, result-schema version,
  scorer/evaluation-contract version, and exact evaluation command/flags when
  a result will participate in an M11E comparison.

It MUST NOT record usernames, hostnames, MAC addresses, home paths, machine
serials, raw environment variables, or personal machine identifiers.

## 9. Calls, tokens, and cost

### 9.1 Call counts and order denominator

The provider collector counts every attempted extraction provider call,
including a failed call, once at the provider boundary. The per-order
denominator is one initial non-replay corpus case/order. Replay attempts are
reported separately and MUST NOT make a duplicate look cheaper by increasing
the denominator. The result includes total calls, number of initial orders,
calls/order, and per-case calls. Notification and sync adapter calls are
reported by channel/step and are not mislabeled extraction calls.

Every live Gemini call MUST carry the identity of its originating initial
corpus order/case. This includes calls made by an authorized retry or recovery
path. A replay attempt is not an additional denominator order; any Gemini
calls it is allowed to cause remain attributed to the original initial order
and are included in that order's call accounting.

Provider-free fake calls are operational evidence only. They may prove that a
duplicate did not call extraction or that a retry resumed at the correct step,
but they are never Gemini usage.

### 9.2 Authoritative token fields

For live Gemini, the only accepted usage values are the non-negative integer
fields supplied by `StructuredGenerationResult` from the installed Gemini SDK:
`input_tokens`, `output_tokens`, and `total_tokens`. The collector MUST NOT
infer tokens from characters, bytes, prompt length, JSON length, or any other
proxy.

For each token field, the result records:

- total of available values;
- count of available values;
- count of missing values;
- per-order average over the available-value denominator;
- per-case value or `null`.

If a provider omits a value, the field is `null`, not `0`. A missing input or
output value excludes that call from a calculation requiring that quantity and
increments the missing count. `total_tokens` is reported independently. If
all three fields exist but `total_tokens != input_tokens + output_tokens`, the
result records a usage-consistency failure; it does not rewrite or infer any
field.

### 9.3 Dated pricing snapshot and estimated model cost per initial order

M11D MUST use a committed, immutable pricing snapshot identified by a stable
`pricing_snapshot_id`. The snapshot contains:

- provider (`google`);
- exact model identifier;
- effective/retrieved UTC date;
- currency (`USD` unless the snapshot explicitly states another currency);
- input price and output price per defined token unit;
- token unit (`1_000_000` for per-million-token pricing, or another explicit
  positive integer);
- a source/reference note sufficient for a reviewer to locate the pricing
  basis;
- no credential, key, URL query secret, or private account data.

For a call with authoritative input `I`, output `O`, unit `U`, input price
`Pi`, and output price `Po`, the exact Decimal calculation is:

```text
input_cost  = (Decimal(I) / Decimal(U)) * Pi
output_cost = (Decimal(O) / Decimal(U)) * Po
call_cost   = input_cost + output_cost
```

For each initial order, the collector defines:

```text
order_model_cost = sum(all Gemini call costs attributed to that order)
```

An initial order is usage-complete only when every Gemini call attributed to it
has authoritative input and output token counts and the matching pricing
snapshot. A no-Gemini-call initial order has known model cost `0`; it is
reported separately as a zero-call order and is not treated as missing usage.
A Gemini-called initial order with any missing required token or pricing value
is usage-incomplete. Its order cost is not replaced by a partial sum.

For the selected workload, the result MUST publish a named
`estimated_model_cost_per_initial_order` value. When every Gemini-called
initial order is usage-complete, it is:

```text
sum(order_model_cost for all initial orders) / initial_order_count
```

Zero-call orders contribute zero. Replay attempts are not additional
denominator orders, while their authorized Gemini calls remain in the
originating order's numerator. If any Gemini-called initial order is
usage-incomplete, the workload value is `null`; the evaluator MUST NOT
silently drop an incomplete call or cost only the available portion of an
order.

The result MUST report at least:

- `initial_order_count`;
- `gemini_called_order_count`;
- `zero_call_order_count`;
- `complete_usage_order_count` (Gemini-called orders only);
- `incomplete_usage_order_count` (Gemini-called orders only);
- `incomplete_usage_call_count`;
- `missing_call_attribution_count`;
- `missing_input_token_count`, `missing_output_token_count`, and
  `missing_total_token_count`;
- `missing_pricing_snapshot_count`.

The called-order counts partition as
`gemini_called_order_count = complete_usage_order_count +
incomplete_usage_order_count`, and initial orders partition as called plus
zero-call orders. Any nonzero missing-call attribution count is a contract
error. Monetary values use `Decimal`, are rounded only for display using a
documented decimal quantization, and are never calculated with binary floats.

The report MUST call this **estimated model cost per initial order**, never
actual billing. The selected pricing snapshot's exact model identifier MUST
match the configured live Gemini model before cost is calculated. A mismatch
makes pricing/cost `ERROR` or unavailable with a limitation; it MUST NOT
silently use pricing for another model. Old committed/reference results retain
their original snapshot identity even when a later pricing snapshot changes.

## 10. Structured result and report contract

### 10.1 Machine-readable result

The result is JSON with stable top-level keys. M11B–M11D MUST preserve this
shape even if internal modules differ:

```json
{
  "schema_version": "opsflow-evaluation-result/v1",
  "evaluation_version": "phase11-v1",
  "run": {
    "run_id": "00000000-0000-4000-8000-000000000001",
    "mode": "provider_free",
    "started_at_utc": "2026-10-07T00:00:00Z",
    "finished_at_utc": "2026-10-07T00:00:01Z",
    "git_sha": "712aa04312cf1e2ebba85f60f2319765057bc211",
    "corpus_version": "1.0.0",
    "gemini_model": null,
    "python_version": "3.12.0",
    "platform": "Linux",
    "cpu_architecture": "x86_64",
    "database": {"engine": "postgresql", "isolated": true}
  },
  "corpus": {
    "case_count": 36,
    "primary_category_counts": {},
    "format_counts": {},
    "tag_counts": {}
  },
  "cases": [
    {
      "case_id": "normal-email-001",
      "status": "PASS",
      "actual": {
        "parse": "PASS",
        "extraction_contract": "PASS",
        "route": "READY_FOR_APPROVAL",
        "approval_level": "STANDARD",
        "pre_approval_state": "READY_FOR_APPROVAL",
        "issue_codes": [],
        "idempotent_replay": false,
        "intake_execution": "COMPLETED",
        "external_execution": "NOT_RUN",
        "external_execution_eligible": false
      },
      "scores": {},
      "durations_ms": {},
      "provider": {
        "name": "fake",
        "calls": 1,
        "input_tokens": null,
        "output_tokens": null,
        "total_tokens": null
      },
      "side_effects": {
        "notification": {},
        "order_sync": {},
        "logical_external_objects": {}
      }
    }
  ],
  "metrics": {
    "extraction_quality": {
      "status": "NOT_APPLICABLE",
      "complete_exact_match": null,
      "field_tp": null,
      "field_fp": null,
      "field_fn": null,
      "field_micro_precision": null,
      "field_micro_recall": null,
      "field_micro_f1": null,
      "per_field": null,
      "reached_live_gemini_case_count": 0,
      "reached_live_gemini_case_ids": [],
      "reason": "No real model was evaluated; scripted provider output is not an extraction-quality score."
    },
    "extraction_contract": {},
    "routing": {},
    "safety": {},
    "latency": {},
    "provider_usage": {},
    "cost": {
      "status": "NOT_APPLICABLE",
      "estimated_model_cost_per_initial_order": null,
      "initial_order_count": 36,
      "gemini_called_order_count": 0,
      "zero_call_order_count": 36,
      "complete_usage_order_count": 0,
      "incomplete_usage_order_count": 0,
      "incomplete_usage_call_count": 0,
      "missing_call_attribution_count": 0,
      "missing_input_token_count": 0,
      "missing_output_token_count": 0,
      "missing_total_token_count": 0,
      "missing_pricing_snapshot_count": 0
    }
  },
  "pricing": {
    "pricing_snapshot_id": null,
    "model": null,
    "status": "NOT_APPLICABLE"
  },
  "release_gates": {
    "all_passed": null,
    "results": []
  },
  "limitations": []
}
```

The example's other empty objects are intentional extension points in an
example; the implementation MUST populate the defined metric fields and MUST
NOT use empty values to hide a missing measurement. In particular:

- `metrics.extraction_quality` is mode-scoped. In `provider_free`, its status
  is `NOT_APPLICABLE`, every quality value including exact match, TP/FP/FN,
  precision, recall, F1, and per-field values is `null`, and its reason states
  that no real model was evaluated. A provider-free result is invalid if it
  publishes a scripted-provider quality percentage, including a fake 100%.
- In `live_gemini`, `metrics.extraction_quality` may contain those quality
  values only for the reported cases that reached the real Gemini provider.
  The result MUST identify that case denominator and cases not reached.
- `metrics.extraction_contract` is the separate home for provider-free schema,
  parser, evidence, source-identity, persistence, call-count, and scorer
  self-test evidence; it MUST NOT use an accuracy label.
- `metrics.cost.estimated_model_cost_per_initial_order` is the explicit
  initial-order denominator metric from Section 9.3 and is `null` when the
  completeness contract is not satisfied.

All result modes also follow these rules:

- `status` is one of `PASS`, `FAIL`, or `ERROR`; a provider/configuration
  error is not a passing case;
- every aggregate metric carries `numerator`, `denominator`, and `value` when
  it is a rate, and carries `sample_count` for percentiles;
- a provider-free per-case `extraction_contract` result means schema,
  parser, evidence, source-identity, or persistence evidence only; it is never
  a business-field quality score;
- per-case actual summaries include route, state, issue codes, replay
  disposition, notification result, sync step/receipt result, and side-effect
  counts when that part of the case ran;
- raw provider response bodies, source contents, credentials, API keys,
  database URLs, SQL, and unbounded exception text are prohibited;
- release-gate results include gate ID, represented-case denominator, failing
  case IDs, numerator, denominator, and pass/fail status; an actual run uses
  a boolean `all_passed` after all represented gates are populated;
- limitations explicitly identify missing live evidence, unavailable token
  fields, synthetic coverage, and local-latency limits;
- a live result retains the actual configured model identifier and pricing
  snapshot identity, and a provider-free result never presents fake-provider
  output as model quality;
- a live preflight error identifies the specific missing or invalid opt-in,
  API key, model, or timeout requirement, rather than reporting only generic
  API-key validation.

### 10.2 Generated versus committed artifacts

Every local run writes a generated JSON result and Markdown report under the
ignored local result directory. Ad-hoc results MUST NOT be committed. A
deliberately selected sanitized reference run MAY be committed only when it:

- identifies its exact Git SHA, corpus version, mode, environment, and pricing
  snapshot;
- contains no credentials, provider response bodies, raw private data, or
  personal machine identifiers;
- is copied to the documented reference-result location;
- is accompanied by its Markdown report generated from that JSON;
- is described as a reference run, not a universal production guarantee.

### 10.3 Human-readable report

The generated report MUST summarize, from the JSON result only:

- corpus composition and version;
- mode-scoped extraction quality: provider-free `NOT_APPLICABLE`/`null` values
  plus deterministic extraction-contract evidence, or live exact match and
  field metrics only over cases that reached Gemini;
- parser/evidence/schema outcomes;
- routing accuracy, issue matching, invalid pass-through, duplicate blocking,
  retry recovery, execution eligibility, logical duplication, malformed-input
  safety, and AI-authority status;
- parse, validation, provider-free intake, and optional live Gemini p50/p95;
- calls/order, token availability/order summaries, complete/incomplete usage
  counts, and estimated model cost per initial order;
- every hard release gate;
- baseline versus optimized comparison only for M11E;
- limitations and unavailable evidence.

The report MUST NOT add Phase 12 marketing copy, ROI claims, screenshots,
video claims, manual-step savings, or production accuracy guarantees.

## 11. Hard Phase 11 release gates

The following are non-tradeable release gates for represented synthetic cases:

| Gate | Exact denominator and pass condition |
| --- | --- |
| `invalid_orders_executed_zero` | All manifest cases marked invalid for automatic execution; pass only when no such case reaches `APPROVED`, `SYNCING`, or `COMPLETED` and no external execution adapter is called. Numerator MUST be 0. |
| `deterministic_violation_routing_100` | All cases with primary category `deterministic_violation` and expected route/state; pass only when route, issue multiset, approval level where present, and pre-approval state all match. Numerator MUST equal denominator. |
| `duplicate_blocking_100` | All manifest duplicate/replay attempts; pass only when no additional authoritative order graph or logical external effect is created and expected replay/stand-down identity is preserved. Numerator MUST equal denominator. |
| `malformed_security_safe_100` | All represented malformed/security cases; pass only when the bounded expected safe outcome occurs, no automatic execution occurs, and bounded output/event evidence contains no raw sensitive content. Numerator MUST equal denominator. |
| `direct_llm_side_effects_zero` | All authority-probe cases and all provider-backed execution boundaries; pass only when document/model output has zero direct approval, rejection, role, notification-eligibility, external-write, or retry-ownership authority. Numerator MUST be 0. |

These gates are not weighted against F1, latency, or cost. If the corpus does
not represent a production behavior, the report states that the gate applies
only to represented synthetic cases and MUST NOT generalize it.

`make evaluate` runs the complete corpus and is the authoritative provider-free
release-gate run. A live run uses the same corpus/version and MAY report the
same deterministic safety outcomes, but it does not replace provider-free
release evidence. Provider-free injected-fault scenarios remain provider-free
evidence when the fault cannot meaningfully coexist with a real Gemini call.

## 12. PostgreSQL isolation and exact commands

M11D will add these repository-level commands without changing the existing
`make test`, `make check`, or developer database behavior:

```bash
make evaluate
make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1
```

`make evaluate` is the mandatory provider-free command. It ignores Gemini
credentials, runs the complete 36-case corpus through the provider-free
harness, and fails if any live-provider configuration is required.
`make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1` uses the same corpus and
must pass the live preflight in Section 4.2 before the first case; it fails
closed when any live requirement is absent or invalid. The live command never
appears in CI. Both commands establish the clean evaluation state described
below themselves.

Both commands use:

```text
OPSFLOW_EVALUATION_DATABASE_URL
```

with a default local contract of
`postgresql+asyncpg://opsflow:opsflow@localhost:5432/opsflow_evaluation`.
The runner MUST apply the existing strict isolation checks: parse this URL,
require PostgreSQL, require a non-empty database name, and reject it when its
database name equals the normal `OPSFLOW_DATABASE_URL` database name. It MUST
also reject a URL that names the configured migration-test database when that
database is present. Isolation is proven before any cleanup; an unsafe URL,
ambiguous comparison, or failed connection is an error and MUST fail closed.

Before each full evaluation or selected reference run, and only after the
guard passes, the command MUST put only this guarded evaluation database into
a pristine OpsFlow application-data state. It MUST clear application rows in
a foreign-key-safe manner, preserve the current migration head, and then
run/confirm migrations at that current head before case 1. The cleanup
mechanism MUST NOT use destructive Alembic downgrade. It MUST NOT create a
second lifecycle interface or require an extra lifecycle flag. Database
creation may remain a one-time documented prerequisite; recurring
application-data cleanup belongs to `make evaluate` and
`make evaluate-live`.

The normal developer database and migration-test database MUST never be
cleared, truncated, reset, dropped, downgraded, or otherwise mutated by an
evaluation command. The command records database isolation as `true` only
after the guard, guarded reset, and current-head confirmation succeed. A
missing database, failed reset, or failed migration is an error, not a
fallback to the developer database. The result excludes cleanup and migration
duration from latency metrics.

## 13. CI boundary

Normal CI MUST remain provider-free and MUST NOT run `make evaluate-live`.
M11B–M11D will add focused evaluation tests to the existing Python test suite
for:

- manifest and corpus schema validation;
- canonicalization and scorer math;
- deterministic route, issue, safety, duplicate, and retry contracts;
- result schema and report rendering from a fixed result fixture;
- explicit proof that no Gemini credential/network is required.

The full 36-case benchmark remains an explicit local/reference command rather
than a required every-commit CI job. The existing suite is already a large
PostgreSQL-backed quality gate, and the full benchmark includes database
setup, persistence/recovery timing, and a p95 that is intentionally sensitive
to runner load. Requiring it on every CI run would make normal CI noisy without
improving scorer correctness. A later CI job MAY run `make evaluate` only after
M11D measures a stable bounded runtime and documents the result; the current
contract does not require that job. `make evaluate-live` is never a CI job.

## 14. Optimization contract

Optimization starts only after a provider-free baseline exists, its structured
result passes all hard safety gates, and its limitations are recorded. An M11E
change is permitted only when:

1. the baseline identifies a concrete measured bottleneck;
2. the change names the metric it intends to improve;
3. the comparison satisfies the invariants below and reruns the same contract;
4. all correctness, safety, duplicate, malformed-input, and AI-authority gates
   remain satisfied; and
5. the report shows before/after numerator, denominator, latency samples,
   calls, tokens, or estimated model cost and states the observed delta.

Baseline and candidate runs MUST have the same comparison invariants:

- corpus version, source ground truth, and case selection;
- evaluation-result schema version;
- scorer version and evaluation-contract version;
- evaluation mode and exact command/flags (including provider-free versus
  live mode);
- the same committed pricing snapshot when live cost is compared;
- the same configured Gemini model when live model results or cost are
  compared;
- Python major/minor version and the relevant dependency-lock identity;
- platform and CPU architecture for latency comparison;
- database engine and version family;
- timing and sample methodology, including percentile method and the rules for
  excluding setup time.

The comparison MUST allow and explicitly record expected differences in
`run_id`, started/finished timestamps, and Git SHA. The report MUST show both
the baseline Git SHA and candidate Git SHA; it MUST NOT describe Git identity,
run identity, or timestamps as comparison invariants. If any
latency-comparability field differs, correctness and safety results MAY still
be compared, but latency deltas MUST be marked non-comparable and MUST NOT be
presented as an optimization win.

Permitted targets include an unnecessary provider call, prompt/input token
volume, expensive model fallback, local parser bottleneck, avoidable repeated
computation, or batching that is already semantically safe. A change MUST NOT
introduce caching, queues, model routing, OCR, parallel processing, prompt
compression, or an alternate model merely because it is a possible future
optimization.

**No optimization justified by the measured baseline** is a valid M11E
outcome. In that outcome, M11E records the baseline, the considered metric,
the reason no change meets the threshold, and the preserved safety gates.

## 15. Milestone decomposition and implementation boundary

### M11A — Evaluation Contract & Benchmark Design — complete

Deliver this design, repository gap analysis, exact metrics, modes, artifacts,
commands, release gates, optimization boundary, and M11B–M11F ownership. No
evaluator implementation, corpus file, pricing snapshot, generated result,
Makefile target, dependency, or CI job belongs here.

### M11B — Synthetic Ground-Truth Corpus & Scoring Foundation

Create the versioned 36-case corpus and trusted-data fixtures; validate source
formats and manifest schema; implement canonicalization, complete exact match,
field micro metrics, required per-field metrics, route/issue ground truth, and
the result-model contracts. M11B does not claim real Gemini accuracy.

### M11C — Correctness, Routing & Reliability Evaluation

Implement the provider-free runner over parser/extraction integration,
deterministic routing, invalid pass-through, duplicate protection, approval and
execution eligibility, retry/recovery, notification isolation, sync steps,
receipts, and hard safety gates. It uses test doubles for all external
providers and does not report fake extraction as Gemini accuracy.

### M11D — Performance, Token & Cost Evaluation

Implement p50/p95 collection, stage timing, calls/order, optional live Gemini
mode, authoritative token capture, dated pricing snapshots, estimated model
cost per initial order, structured JSON output, and Markdown rendering. M11D adds the
exact `make evaluate` and `make evaluate-live` targets and evaluation database
isolation checks.

### M11E — Measurement-Driven Optimization & Regression Comparison

Inspect the M11D baseline, choose only a measured bottleneck, implement the
smallest justified optimization if one exists, rerun the identical contract,
and report before/after evidence. It may instead document no optimization
justified.

### M11F — Independent Phase 11 Audit & Closeout

Independently audit ground-truth integrity, scorer math, metric calculations,
release gates, provider-free reproducibility, live/offline claim separation,
latency methodology, token/cost math, optimization evidence, clean-clone
behavior, documentation truth, and the Phase 12 boundary. M11F does not add
Phase 12 implementation.

## 16. Expected repository shape after implementation

M11B–M11D SHOULD create only these focused areas:

```text
evals/
  corpus/v1/manifest.json
  corpus/v1/documents/                  # 36 synthetic source files
  corpus/v1/trusted-data/               # referenced deterministic fixtures
  pricing/                              # dated live-model snapshots
  results/.gitkeep                      # ignored generated local output
src/opsflow/evaluation/                 # small harness/scorer/collector modules
tests/evaluation/                       # schema, scorer, contract tests
docs/evaluation/reference/              # selected sanitized reference JSON/MD only
```

The exact internal Python module names remain an implementation detail, but
the package MUST remain in the existing `src/opsflow` stack and use standard
library/committed dependencies. `evals/results/` is for ignored local output;
`docs/evaluation/reference/` is for deliberately selected sanitized evidence.
No directory above is created by M11A.

## 17. Non-goals and prohibited claims

Phase 11 explicitly excludes:

- a dashboard product or hosted metrics stack;
- external evaluation SaaS or a heavyweight LLM-evaluation framework;
- LLM-as-judge scoring;
- a human annotation platform;
- production A/B testing;
- model training or fine-tuning;
- an arbitrary multi-model bake-off without a measured optimization question;
- a new OCR architecture without a measured need;
- ROI, revenue, or business-value claims;
- screenshots, video, portfolio marketing prose, or release packaging;
- Phase 12 demo production or publication work;
- live Odoo, HubSpot, Gmail, Slack, or n8n benchmarking.

The following claims are prohibited unless a future artifact satisfies the
contract exactly:

- calling a fake-provider score Gemini accuracy;
- calling estimated model cost actual billing;
- presenting local p50/p95 as a production SLA;
- generalizing represented synthetic cases to universal production guarantees;
- claiming physical exactly-once provider execution or exactly-once
  notification delivery;
- treating a missing token field as zero;
- reporting a route as correct from HTTP status alone;
- allowing an LLM or document text to authorize approval, rejection, role,
  notification eligibility, external mutation, or retry ownership;
- presenting a generated ad-hoc result as a committed reference result;
- adding Phase 12 marketing or ROI language to the Phase 11 report.

## 18. M11A acceptance checklist

The following questions have one defined answer in this document:

1. A case is one stable synthetic source identity plus human-authored expected
   extraction and deterministic outcome; replay/retry attempts remain a
   manifest-directed sequence inside that case.
2. Expected extraction and deterministic outcomes live in the versioned JSON
   manifest; trusted business data lives in a synthetic catalog/lookup fixture
   and is not a precomputed answer for expected lines.
3. Corpus versioning uses semantic `corpus_version`, source SHA-256, and
   result-retained Git/corpus identity.
4. The required corpus is 36 cases across `normal`, `edge`, `security`,
   `deterministic_violation`, `duplicate`, and `retry_recovery`, with nine each
   of text/EMAIL_BODY, CSV, XLSX, and PDF.
5. Provider-free extraction-quality exact match, TP/FP/FN, precision, recall,
   F1, and per-field quality are `NOT_APPLICABLE`/`null` with a no-real-model
   limitation; live quality uses only cases that reached real Gemini.
6. Live field micro precision/recall/F1 uses positioned field/value facts and
   the explicit TP/FP/FN rules in Section 6.3; deterministic scorer tests are
   not benchmark-quality metrics.
7. Lines are matched by existing order, never by SKU or fuzzy identity.
8. Routing accuracy requires route, approval level, issue multiset, and
   durable pre-approval state agreement.
9. Invalid pass-through is any represented invalid case that reaches approval,
   sync, completion, or an external execution adapter.
10. Duplicate blocking is no additional order graph or logical external effect
    with expected replay/stand-down identity preserved.
11. Retry recovery requires the expected durable failure, authorized resume,
    preserved prior receipts, and expected final state.
12. Execution safety uses manifest eligibility, explicit approval, adapter
    call traces, receipts, and logical external-object counts.
13. The five hard gates are listed in Section 11 and are non-tradeable.
14. Provider-free metrics are parsing, schema/evidence, deterministic,
    safety/reliability, local latency, and fake operational call evidence;
    none is labeled model accuracy.
15. Live Gemini is required only for real model quality, live provider latency,
    authoritative usage, and estimated model cost, after all four preflight
    requirements pass before case 1.
16. Fake-provider output may never be called Gemini accuracy.
17. p50/p95 use one case/call sample as defined and nearest-rank percentiles.
18. Environment metadata is bounded Python/platform/architecture/time/corpus/
    Git/database context with no personal identifiers.
19. Provider calls are counted at the provider boundary, including failures,
    and every live call is attributed to its originating initial order,
    including authorized retry/recovery calls; replay calls do not add
    denominator orders.
20. Missing token values are `null` with availability/missing counts.
21. Cost uses Decimal input-plus-output price math from a dated snapshot and
    the complete-usage order contract; incomplete called orders make aggregate
    cost per initial order `null` rather than partially costed.
22. Pricing identity is retained in every live result and its model identifier
    must match the configured live model before cost is calculated.
23. Structured JSON is the sole source of truth for the report and release
    gates.
24. Local results are ignored; selected sanitized reference JSON/Markdown may
    be committed under the documented location.
25. Exact commands are `make evaluate` and
    `make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1`, and provider-free
    mode executes the complete 36-case corpus.
26. Each full evaluation/reference command proves strict PostgreSQL isolation,
    resets only guarded evaluation application data in FK-safe fashion, and
    confirms the current migration head without destructive downgrade;
    normal and migration-test databases are never mutated.
27. CI validates schemas, scorers, contracts, and provider-free behavior.
28. Live Gemini and the noisy full benchmark are never normal CI requirements.
29. Optimization begins only after a passing reproducible baseline and uses the
    explicit M11E comparison invariants.
30. A successful optimization improves its named metric while preserving every
    safety gate; Git SHA, run ID, and timestamps may differ, and non-comparable
    latency is never presented as a win.
31. No optimization justified by the measured baseline is valid.
32. M11B–M11F responsibilities are explicitly divided in Section 15.
33. Phase 12 remains release/demo/marketing/publication scope outside M11.
34. Prohibited claims and non-goals are explicit in Section 17.
