# Phase 11 Evaluation & Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. The repository requires single-agent sequential execution; do not use subagents or multi-agent workflows.

**Goal:** Implement M11B–M11F as one small, reproducible evaluation system for the existing OpsFlow intake, validation, review, notification, and order-sync seams. M11A remains the approved design and planning milestone; this plan does not authorize implementation during the planning task.

**Architecture:** Keep one cohesive `src/opsflow/evaluation/` package at the evaluation boundary. It loads a human-authored 36-case corpus, invokes existing production application services, observes durable outcomes through the existing persistence and provider protocols, scores extraction and deterministic behavior, measures run-scoped timing and authoritative provider usage, and writes structured JSON before rendering Markdown. Provider-free mode uses scripted providers only as deterministic contract doubles; it never treats them as model-quality evidence. Live Gemini is a separately gated mode and is never part of normal CI.

**Tech stack:** Python 3.12, existing Pydantic/dataclass contracts, existing document processors and application services, SQLAlchemy async sessions, PostgreSQL, Alembic, pytest, Ruff, mypy, Make, Docker Compose, and the repository's existing pinned security tooling. Do not add pandas, scikit-learn, MLflow, LangSmith, DeepEval, or another evaluation framework.

**Spec:** [approved M11A design](../specs/2026-10-07-phase-11-evaluation-optimization-design.md), approved at `bde63c54a66486aea8c1e7292887d004bf9e91f4`.

**Global constraints:**

- Use one lightweight Python harness and the existing OpsFlow production seams. Do not create a second state machine, retry implementation, provider abstraction, or orchestration subsystem.
- Provider-free mode is mandatory, costs `$0`, runs the complete v1 corpus, and reports extraction quality as `NOT_APPLICABLE`/`null` because no real model was evaluated. Scripted-provider output may prove schema acceptance, parser success, grounding, persistence, call counts, and scorer self-tests, but it is never called accuracy, precision, recall, F1, or model-quality evidence.
- Live Gemini is explicit opt-in, never normal CI, and must pass the exact runtime preflight: `OPSFLOW_EVALUATION_LIVE_GEMINI=1`, nonblank `OPSFLOW_GEMINI_API_KEY`, nonblank `OPSFLOW_GEMINI_MODEL`, and a finite positive `OPSFLOW_GEMINI_TIMEOUT_SECONDS`. There is no fake fallback.
- The v1 corpus is exactly 36 human-authored cases: 10 normal, 8 edge, 4 security, 7 deterministic violation, 4 duplicate, and 3 retry-recovery; nine each of EMAIL_BODY/text, CSV, XLSX, and PDF.
- Ground truth is human-authored. Trusted business data is a synthetic catalog/lookup fixture queried from the predicted draft, never a precomputed answer keyed by expected extraction values.
- Extraction scoring is positional for lines, uses exact/NFC/string/Decimal/date canonicalization from the spec, has no fuzzy matching, and reports TP/FP/FN with micro precision/recall/F1 only for live cases that reached the real Gemini provider.
- The five hard release gates are non-tradeable: zero invalid orders executed, 100% deterministic-violation routing, 100% duplicate blocking, 100% safe malformed/security handling, and zero direct LLM side effects.
- Structured JSON is the reporting source of truth. Markdown is rendered only from validated JSON. Ad-hoc results are ignored; only deliberately selected, sanitized reference evidence may be committed under `docs/evaluation/reference/`.
- The evaluation database is PostgreSQL, strictly distinct from the normal development and configured migration-test databases, and is guarded and reset to a pristine application-data state before every full/reference run. Current migration head is confirmed; destructive Alembic downgrade is not the cleanup mechanism.
- There is no live Odoo, HubSpot, Gmail, Slack, or n8n benchmark requirement. Provider-free doubles must prove logical external-object uniqueness, durable receipts, notification isolation, and replay behavior.
- M11E begins with a measured baseline. It may conclude `No optimization justified by the measured baseline`; caching, concurrency, model switching, OCR, queueing, prompt compression, and batching are not pre-authorized.
- No Phase 12 marketing, demo, publication, ROI, screenshot, or release work is included.

## Current execution status

M11B is `COMPLETE` at its independently reviewed technical baseline; its
historical approved corpus remains `1.0.0`. The recovery-authority correction
was corpus `2.0.0` at amendment SHA
`1bdd3763bd00e73a28a8eacb148f803d03ea7bfe`. The duplicate replay-contract
correction was corpus `3.0.0` at amendment SHA
`7184efb9589445d16e354decd486f28bc90ac09b`; it is the active executable
corpus. M11C — Correctness, Routing & Reliability Evaluation is `COMPLETE` at
independently reviewed technical baseline
`ce456f2928ed9773f26ec65dfa5776d29dd4e915`. M11D–M11F remain `NOT STARTED`;
Phase 11 remains `IN PROGRESS`; Phase 12 remains `NOT STARTED`.

### M11C closeout — local milestone verification

M11C delivered Tasks 5–7:

1. Provider-free evaluation runner through real OpsFlow application seams.
2. Durable correctness and deterministic routing evaluation.
3. Duplicate replay and idempotency evidence.
4. Explicit Phase 6 approval and authorized retry evidence.
5. Notification persistence and authority observations.
6. Phase 9 synchronization, recovery, and durable receipt-preservation evidence.
7. Five hard release gates and structured correctness/reliability metrics.
8. Guarded PostgreSQL integration-test evidence.

The independently reviewed technical baseline is
`ce456f2928ed9773f26ec65dfa5776d29dd4e915`. M11C-FINAL-01 was independently
reviewed and resolved at this baseline. The active executable corpus remains
`3.0.0`; chronology remains `1.0.0` (original M11B approval), `2.0.0`
(recovery-authority correction), and `3.0.0` (duplicate two-layer replay
contract). No live provider calls were made.

**Local milestone verification (not GitHub PR-head CI):** the full provider-free
corpus passed and accounted for 36/36 cases; full routing accuracy was
14/14; invalid execution was 0/13;
deterministic routing was 7/7; duplicate blocking was 4/4; retry recovery was
3/3; malformed/security handling was 4/4; direct authority violations were
0/36; execution safety was 14/14; logical duplication was 0; provider-free
extraction quality was `NOT_APPLICABLE`. All five hard release gates passed.
The M11C PostgreSQL suite passed 143 tests twice consecutively against the same
guarded disposable database. The integration suite passed 367 tests. Full
`make check` passed 1,907 tests with 6 skipped and 91.25% coverage. Frontend
tests passed 68 tests. Ruff, formatting, mypy, package build, frontend lint and
build, pinned Gitleaks v8.28.0 committed-range scan, Markdown links, and
`git diff --check` passed. The frontend install reported two high-severity npm
audit advisories; these were recorded as non-blocking and are not represented
as resolved.

M11C did not implement M11D Tasks 8–12: run-scoped latency and percentile
aggregation, authoritative token usage or model-cost evaluation, dated pricing
snapshots, evaluation-database runtime guard/reset lifecycle, public
`make evaluate`, live Gemini evaluation, reference JSON/Markdown result
artifacts, performance optimization, or the Phase 11 final audit. M11D–M11F
remain `NOT STARTED`; Phase 11 remains `IN PROGRESS`.

### M11C-FINAL-01 — duplicate order identity evidence

Independent review of candidate `a79aa9b4981351370b9bf37b6accb0b9c17117a1`
found that duplicate evidence selected a durable order by source SHA-256 and
UUID order. Because the seeded and evaluated documents can share that digest,
the selected order did not necessarily belong to the evaluated intake. The
ruling is to retain the order ID returned by initial intake, verify it against
the case's durable source document and Phase 2 creation idempotency record, and
use it for all intent counts and replay comparisons. Replay must return that
same order ID. SHA-256 remains source identity evidence and does not select the
authoritative order.

PostgreSQL RED→GREEN regression coverage creates two durable source documents
with the same SHA-256 and a seeded order UUID that sorts before the evaluated
order. Injected notification and order-sync intents on the evaluated order
produce structured duplicate-evidence FAIL results; a changed replay order ID
also fails. All four unmodified duplicate scenarios pass with
`REPLAYED_EXISTING + STANDING_DOWN` and unchanged durable intent counts. The
real corpus `3.0.0` run passes all 36 cases and all five hard gates, with zero
notification or sync intent deltas across duplicate replays. Corpus sources and
production behavior are unchanged. Independent technical review accepted the
remediation. M11C-FINAL-01 is resolved at the approved M11C technical baseline
`ce456f2928ed9773f26ec65dfa5776d29dd4e915`; M11C is `COMPLETE`. M11D–M11F
remain `NOT STARTED` and Phase 11 remains `IN PROGRESS`.

## Milestone Execution Gates

The execution unit is one milestone, not the whole Phase 11 plan. A single
`superpowers:executing-plans` invocation must execute only the selected
milestone’s tasks, then stop for review. Execution remains single-agent and
sequential; subagents and multi-agent workflows are prohibited.

- **M11B:** execute Tasks 1–4 only, then stop. Return implementation SHA(s),
  scope/files, RED→GREEN evidence, focused tests, regressions,
  M11B-appropriate quality/security checks, deviations/limitations, and clean
  branch/worktree state. M11C cannot begin until M11B has independent review,
  all findings have been remediated and re-reviewed, human approval is
  recorded, and M11B status closeout is durable.
- **M11C:** Tasks 5–7 are complete at approved technical baseline
  `ce456f2928ed9773f26ec65dfa5776d29dd4e915`; independent technical review and
  the documentation status closeout are recorded above. M11D remains a separate
  gated milestone and must not be started by this M11C closeout.
- **M11D:** execute Tasks 8–12 only, including the actual mandatory reference
  run described in Task 12, then stop with the same evidence report and
  independent-review/human-approval gate before M11E.
- **M11E:** execute Tasks 13–14 only, including the baseline decision and only
  a conditionally justified optimization, then stop with the same evidence
  report and independent-review/human-approval gate before M11F. Freeze the
  approved technical baseline SHA at this boundary.
- **M11F:** start only from that frozen technical baseline in a fresh Codex
  context/session as an audit-only milestone. M11F may inspect, verify, and
  write the audit/status prose permitted by its tasks; it must not silently
  remediate implementation findings.

The handoff between milestones must include the approved prior milestone SHA,
its durable status closeout, the independent review disposition, and the exact
next milestone task range. The plan must not be handed to
`superpowers:executing-plans` as an uninterrupted M11B–M11F run.

## Review Focus

Every high-risk failure below has an owning test task and an explicit acceptance condition.

1. **Fake/scripted extraction reported as model quality:** M11B result-contract tests and M11C full provider-free-run tests must assert that live/model exact match, field counts, and F1 are `null` with `NOT_APPLICABLE` and a no-real-model reason in provider-free results.
2. **Trusted fixtures repair or bias predicted customer/SKU:** M11B request-driven provider tests must use wrong, missing, and unknown predicted references/SKUs and prove the provider does not consult expected extraction values.
3. **Repeated runs contaminated by prior database rows:** M11D database tests must seed application rows, reset only the guarded evaluation database, rerun the same case, and prove equivalent duplicate, graph, notification, receipt, replay, and timing starting conditions.
4. **Incomplete usage understates spend:** M11D accounting tests must cover multiple calls per initial order, retries, zero-call orders, every missing authoritative token field, missing pricing, wrong pricing model, and aggregate `null` behavior without partial-cost summation.
5. **Non-comparable latency/optimization presented as a win:** M11E comparison tests must permit run ID/timestamp/Git SHA differences, require the approved invariants, and mark latency deltas non-comparable whenever platform, CPU, runtime, database, or timing methodology differs.

## Planned repository shape

The following paths are implementation targets for later execution. They are not created by this planning task.

```text
evals/
  corpus/v1/
    manifest.json
    documents/                 # exactly the 36 manifest-declared source files
    trusted-data/catalog.json  # catalog/lookup records, not expected answers
  pricing/                     # dated immutable live-model snapshots
  results/                     # ignored local JSON/Markdown output
src/opsflow/evaluation/
  __init__.py
  models.py
  corpus.py
  scoring.py
  runner.py
  doubles.py
  measurements.py
  database.py
  artifacts.py
  commands.py
  comparison.py
tests/evaluation/
  test_corpus_contracts.py
  test_trusted_lookup.py
  test_scoring.py
  test_result_contracts.py
  test_runner.py
  test_reliability.py
  test_release_gates.py
  test_measurements_cost.py
  test_evaluation_database.py
  test_artifacts_commands.py
  test_live_preflight.py
  test_reference_run.py
  test_comparison.py
docs/evaluation/reference/
  phase-11-provider-free-baseline.json
  phase-11-provider-free-baseline.md
  phase-11-live-gemini-reference.json       # optional
  phase-11-live-gemini-reference.md         # optional
  phase-11-live-gemini-unavailable.md       # selected only when live is unavailable
docs/audits/phase-11-audit.md
```

The exact source filenames and case identifiers are declared by `evals/corpus/v1/manifest.json`; the implementation must not discover arbitrary files outside that manifest. The package remains cohesive: split a module only when the responsibility above has a concrete interface and its focused tests justify the boundary.

## Interfaces and ownership boundaries

The implementation should preserve these existing seams rather than duplicate their behavior:

- Ingestion: `process_document(DocumentInput, limits=...) -> CanonicalDocument`.
- Extraction: `OrderExtractor.extract(CanonicalDocument) -> ExtractionDraft`, using `LLMProvider.generate_structured(...)`; provider-free tests use the existing `FakeProvider`, and live tests use the existing Gemini provider/configuration semantics.
- Trusted lookup: `BusinessDataProvider.get_validation_data(BusinessDataLookupRequest) -> TrustedBusinessData`, with `BusinessDataLookupRequest` built from the predicted draft.
- Deterministic validation: `validate_order(...)` and the existing pure validation engine; evaluation code observes its `ValidationResult` and durable route rather than reimplementing policy.
- Intake durability/recovery: `execute_orchestration_intake(...)`, existing claims/ownership/failure classification, and existing retry/recovery commands.
- Review and sync: existing approval/rejection/retry application commands, `OrderSyncStepExecutor`, and durable order-sync receipts; provider-free doubles implement the existing protocols.
- Notifications: existing notification intent/claim/outcome service and durable rows; no evaluator-owned notification state machine.
- Persistence: existing SQLAlchemy models and Alembic head; evaluation database cleanup uses an explicit allowlist of application tables after a fresh isolation guard.

No production-code modification is currently planned. If implementation finds a real measurement seam that cannot be adapted from evaluation code, pause before changing production behavior and record: the exact gap, why an adapter cannot solve it, the smallest change, and regression tests for existing behavior. Convenience, test injection, or evaluator observability alone is not sufficient justification.

## Evaluation contract type inventory

The plan uses the following minimal types. Types marked “existing” are imported
from the cited repository file; types marked “Task 1” are defined in
`src/opsflow/evaluation/models.py` and are produced before later tasks use
them. The inventory is intentionally small and uses immutable tuples for
deterministic serialization.

- **Existing:** `ExtractionDraft` and `ExtractedLine` from
  `src/opsflow/extraction/models.py`; `CanonicalDocument` from
  `src/opsflow/documents/models.py`; `ValidationFacts`, `ValidationRoute`,
  `ApprovalLevel`, `BusinessDataLookupRequest`, `TrustedBusinessData`,
  `TrustedCustomer`, and `TrustedProduct` from
  `src/opsflow/validation/models.py`; `SourceDocumentType`,
  `ValidationSeverity`, and `ValidationIssue` from
  `src/opsflow/domain/records.py`; `OrderState` from
  `src/opsflow/domain/order.py`; `BusinessDataProvider`,
  `normalize_customer_name`, and `validate_trusted_business_data` from
  `src/opsflow/validation/business_data.py`; `OrchestrationRuntime` from
  `src/opsflow/orchestration/composition.py`; and
  `OrderSyncStep`, `OrderSyncFailureCode`, and `ExecuteNextKind` from
  `src/opsflow/order_sync/contracts.py`; `async_sessionmaker[AsyncSession]`
  from `src/opsflow/database.py` / SQLAlchemy.
- **Standard/dependency types:** `Path`, `Mapping`, and `Sequence` are from the
  standard library; `Decimal`, `date`, `datetime`, `UUID`, and `Literal` retain
  their standard-library meanings; `AsyncEngine` is SQLAlchemy’s existing async
  engine type; and `Config` is `alembic.config.Config`.
- **Task 1:** `CanonicalValue = str | Decimal | date | None`.
- **Task 1:** `EvaluationMode` is an enum with exactly `provider_free` and
  `live_gemini`; `CaseCategory` is an enum with exactly `normal`, `edge`,
  `security`, `deterministic_violation`, `duplicate`, and `retry_recovery`.
- **Task 1:** `SourceSpec(path: str, document_type: SourceDocumentType,
  mime_type: str, sha256: str)`, where `path` is the serialized
  `source.path` relative to the corpus-version directory. It uses the existing
  `SourceDocumentType` enum; it is not a free-form document-type string and is
  not renamed to `relative_path`.
- **Task 1:** `ExpectedLine(sku: str | None, description: str | None,
  quantity: Decimal | None, submitted_price: Decimal | None)` and
  `ExpectedExtraction(customer_name: str | None, customer_reference: str | None,
  po_number: str | None, order_date: date | None,
  requested_delivery_date: date | None, currency: str | None,
  notes: str | None, lines: tuple[ExpectedLine, ...])`. These are the
  human-readable named manifest fields; they are not generic header tuples.
- **Task 1:** `ExpectedValidation(route: ValidationRoute,
  approval_level: ApprovalLevel | None, issue_codes: tuple[str, ...],
  issue_severities: Mapping[str, ValidationSeverity],
  pre_approval_state: OrderState, external_execution_eligible: bool)`. These
  fields serialize the approved `issue_codes` and `issue_severities` manifest
  members directly; the scorer canonicalizes their paired code/severity facts
  into a multiset for comparison.
- **Task 1:** `TrustedBusinessDataExpectation(fixture_path: str,
  facts: ValidationFacts)`; it is present only when deterministic validation
  runs. `fixture_path` identifies a synthetic catalog/lookup fixture and
  `facts` carries the manifest-directed OpsFlow-local duplicate/document
  facts.
- **Task 1:** `ApprovalScenario(role: str, action: str,
  expected_state: OrderState)` is present only for approval cases;
  `expected_state` is validated as the approved `OrderState.APPROVED` value.
  The role and action are deterministic test configuration, and the runner
  supplies the actor; neither document text nor provider output can supply
  them.
- **Task 1:** `ReplayDisposition` is an evaluation enum containing exactly
  `REPLAYED_EXISTING` and `STANDING_DOWN`; `ReplayScenario(duplicate_group_id: str,
  seed_case_id: str, replay_attempt_count: int,
  expected_disposition: ReplayDisposition)` is present only for duplicate
  cases.
- **Task 1:** `RecoveryScenario(injected_stage: str, failure_code: str,
  expected_resume_origin: OrderState, expected_durable_outcome: str,
  expected_final_state: OrderState, preserve_prior_receipts: bool)` is present
  only for retry cases. `injected_stage`, `failure_code`,
  `expected_resume_origin`, and `expected_durable_outcome` are bounded to the
  approved manifest values during validation; they are not arbitrary runtime
  instructions. Existing `OrderState` is reused for resume/final state; when
  the injected stage or failure is an order-sync scenario, validation reuses
  the existing `OrderSyncStep`, `OrderSyncFailureCode`, and bounded execution
  outcome values rather than inventing a parallel production enum.
- **Task 1:** `CorpusCase(case_id: str, primary_category: CaseCategory,
  tags: tuple[str, ...], source: SourceSpec,
  expected_extraction: ExpectedExtraction | None,
  trusted_business_data: TrustedBusinessDataExpectation | None,
  expected_validation: ExpectedValidation | None,
  approval: ApprovalScenario | None, replay: ReplayScenario | None,
  recovery: RecoveryScenario | None)`. Validation enforces the M11A
  category/scenario requirements: extraction is omitted for parser-only or
  failure cases; trusted data and validation are both required and paired when
  validation runs and both omitted otherwise; approval, replay, and recovery
  appear only for their corresponding scenarios; irrelevant optional objects
  are omitted. A repeated source SHA is allowed and is not a case-identity
  constraint.
- **Task 1:** `CorpusManifest(schema_version: str, corpus_version: str,
  cases: tuple[CorpusCase, ...], trusted_catalog_path: str | None)`. The
  serialized identity remains `schema_version` and `corpus_version`; the
  optional catalog path is retained only if the implementation keeps a global
  catalog reference in addition to per-case fixture paths.
- **Task 1:** `TrustedCatalog(customers: tuple[TrustedCustomer, ...],
  products: tuple[TrustedProduct, ...])`.
- **Task 2:** `EvaluationBusinessDataProvider(catalog: TrustedCatalog)` is a
  frozen evaluation-only implementation of the existing `BusinessDataProvider`
  protocol; its only produced method is
  `get_validation_data(request: BusinessDataLookupRequest) -> TrustedBusinessData`.
- **Task 1:** `FieldCounts(tp: int, fp: int, fn: int)`;
  `CanonicalExtractionProjection(field_facts: tuple[tuple[str, CanonicalValue], ...])`
  is an internal immutable scoring projection produced by
  `project_extraction(...)` from either an `ExpectedExtraction` or an
  `ExtractionDraft`; it is not a manifest model and is never hand-authored in
  the corpus JSON. `RateMetric(numerator: int, denominator: int,
  value: Decimal | None)` represents an aggregate rate and keeps undefined
  math as `value=None`.
- **Task 1:** `FieldMetric(counts: FieldCounts, precision: RateMetric,
  recall: RateMetric, f1: RateMetric)` preserves TP/FP/FN and each rate’s
  numerator, denominator, and nullable value. `PositionedExtractionScore(
  exact_match: bool, total: FieldCounts,
  per_field: tuple[tuple[str, FieldMetric], ...],
  micro_precision: RateMetric, micro_recall: RateMetric,
  micro_f1: RateMetric)` uses a boolean only for the per-case positioned
  complete match; undefined precision, recall, and F1 remain null rather than
  becoming zero.
- **Task 1:** `ValidationOutcomeScore(route_match: bool,
  approval_level_applicable: bool, approval_level_match: bool | None,
  pre_approval_state_match: bool, issue_multiset_match: bool,
  expected_route: ValidationRoute | None, actual_route: ValidationRoute | None,
  expected_approval_level: ApprovalLevel | None,
  actual_approval_level: ApprovalLevel | None,
  expected_pre_approval_state: OrderState | None,
  actual_pre_approval_state: OrderState | None,
  missing_issue_facts: tuple[tuple[str, ValidationSeverity], ...],
  unexpected_issue_facts: tuple[tuple[str, ValidationSeverity], ...],
  overall_match: bool)`. Routing agreement therefore exposes route,
  approval-level applicability, durable pre-approval state, and the canonical
  code/severity multiset separately.
- **Task 1:** `ExtractionQuality(status: Literal["AVAILABLE", "NOT_APPLICABLE"],
  complete_exact_match: RateMetric | None, field_tp: int | None,
  field_fp: int | None, field_fn: int | None,
  field_micro_precision: RateMetric | None,
  field_micro_recall: RateMetric | None, field_micro_f1: RateMetric | None,
  per_field: tuple[tuple[str, FieldMetric], ...] | None,
  reached_live_gemini_case_count: int, reason: str)`. A live complete exact
  match is the reached-case rate; provider-free mode has status
  `NOT_APPLICABLE` and null quality metrics. `CaseResult` contains the
  serialized per-case envelope and, when exercised, actual route, approval
  level, durable state, issue code/severity facts, replay disposition,
  notification result, sync step/receipt facts, logical side-effect counts,
  provider reachability/call information (using existing `ValidationIssue`
  facts where applicable), bounded contract evidence, and an
  optional internal predicted extraction used for scoring but excluded from
  serialized artifacts. `EvaluationRunResult` contains the run-level corpus
  composition, extraction-contract evidence, mode-scoped extraction quality,
  routing/safety metrics, latency, provider usage, cost, pricing
  identity/status, release gates, limitations, and run/environment identity,
  including `run_id`, timestamps, Git SHA, corpus version, result schema
  version, scorer/evaluation contract version, mode, and command. Raw source
  bytes/text and secrets are never fields of serialized result models.
- **Task 8:** `ProviderCallRecord(initial_case_id: str, initial_order_id: UUID | None,
  attempt_index: int, duration_ms: Decimal, input_tokens: int | None,
  output_tokens: int | None, total_tokens: int | None,
  pricing_snapshot_id: str | None, pricing_model: str | None,
  call_cost: Decimal | None)`.
- **Task 8:** `PricingSnapshot(snapshot_id: str, effective_date: date, model: str,
  input_price_per_million: Decimal, output_price_per_million: Decimal,
  source: str)` is the immutable file-backed pricing record used only by cost
  calculation; `RunMeasurements` is the result model for the four named timing
  summaries, nearest-rank p50/p95, and the timing/sample methodology metadata.
- **Task 9:** `EvaluationDatabaseConfig(evaluation_url: str, normal_url: str,
  migration_test_url: str | None, evaluation_database_name: str)`.
- **M11E Task 13:** `ComparisonResult(correctness_comparable: bool,
  latency_comparable: bool, invariant_mismatches: tuple[str, ...],
  latency_limitation: str | None, baseline_git_sha: str,
  candidate_git_sha: str)` returned by
  `compare_runs(baseline: EvaluationRunResult, candidate: EvaluationRunResult)`.

## M11B — Synthetic Ground-Truth Corpus & Scoring Foundation

### Task 1 — Freeze strict corpus, case, and result contracts

**Files:**

- Create `src/opsflow/evaluation/__init__.py` with the small public evaluation package surface.
- Create `src/opsflow/evaluation/models.py` containing strict Pydantic/dataclass models for `EvaluationMode`, corpus source metadata, case category/format, named expected extraction, conditional trusted-data/validation/approval/replay/recovery scenarios, trusted catalog records, per-case results, extraction-quality status, release-gate facts, usage counters, run metadata, and the initial versioned result schema.
- Create `src/opsflow/evaluation/corpus.py` with the manifest loader and source-verification interface:
  - `load_manifest(corpus_root: Path) -> CorpusManifest`;
  - `resolve_manifest_source(corpus_root: Path, source_path: str) -> Path`;
  - `verify_source_sha256(source_path: Path, expected_sha256: str) -> None`.
- Create `tests/evaluation/test_corpus_contracts.py`.
- Create `tests/evaluation/test_result_contracts.py`.

**Interfaces consumed:** approved manifest rules; `Path`; existing extraction/validation model shapes; existing supported MIME/document-type values.

**Interfaces produced:** strict manifest/case/result models consumed by Tasks 2–4 and later runner/artifact tasks. Result models must represent provider-free extraction quality as `status="NOT_APPLICABLE"`, nullable live-quality fields, and an explicit limitation reason.

**RED:** write tests first for malformed manifests, unsupported category/format, duplicate case IDs, missing required extraction sections only on extraction cases, missing trusted-data/validation sections only when validation runs, illegal optional scenario/category combinations, illegal result status combinations, and a provider-free result that attempts to provide an extraction score. Assert serialization is JSON-safe and rejects raw document bytes, raw document text, API keys, authorization headers, and arbitrary secret-bearing metadata.

**Focused command:** `uv run pytest tests/evaluation/test_corpus_contracts.py tests/evaluation/test_result_contracts.py -q`.

**Minimal implementation:** add only the strict models and pure contract validation required by the tests. Do not load the corpus yet, call an application service, or write an artifact.

**GREEN:** the focused tests pass; model serialization contains identifiers, hashes, expected/result facts, and bounded error/limitation fields only; no result model can encode fake-provider output as live extraction quality.

**Commit:** `feat(phase11): add evaluation contract models`.

### Task 2 — Add the exact 36-case corpus and request-driven trusted catalog

**Files:**

- Create `evals/corpus/v1/manifest.json`, version `1.0.0`, declaring exactly 36 cases, their human-authored expected extraction and conditional route/issue/approval/replay/recovery outcomes, source paths, SHA-256 digests, document formats/MIME values, category distribution, and manifest-driven local `ValidationFacts` where needed.
- Create the 36 manifest-declared source files below `evals/corpus/v1/documents/`: nine EMAIL_BODY/text cases, nine CSV cases, nine XLSX cases, and nine PDF cases. Use the manifest’s explicit case IDs and ensure every path is safe and every digest is committed with the source.
- Create `evals/corpus/v1/trusted-data/catalog.json` containing only synthetic lookup data sufficient for exact customer reference, normalized customer name, product SKU, active state, currency, catalogue price, and available quantity. It must not contain an expected-extraction-to-result map.
- Extend `src/opsflow/evaluation/corpus.py` with `load_catalog(catalog_path: Path) -> TrustedCatalog` and `EvaluationBusinessDataProvider`, implementing the existing `BusinessDataProvider` request contract and canonical candidate ordering.
- Extend `tests/evaluation/test_corpus_contracts.py` for digest, path, distribution, format, and MIME checks.
- Create `tests/evaluation/test_trusted_lookup.py`.

**Interfaces consumed:** Task 1 models; `BusinessDataLookupRequest`; `TrustedBusinessData`; `TrustedCustomer`; `TrustedProduct`; `normalize_customer_name(...)`, `validate_trusted_business_data(...)`, and the `BusinessDataProvider` protocol from `src/opsflow/validation/business_data.py`. The provider must return customer candidates sorted by reference because that is the canonical ordering enforced by `validate_trusted_business_data(...)`; no production sandbox provider is introduced.

**Interfaces produced:** an immutable manifest/corpus loader and an evaluation provider that accepts the actual predicted request and returns `products_by_line` with length equal to the predicted line count.

**RED:** add tests for a malformed digest, declared-versus-actual digest mismatch, `../` traversal, absolute path, symlink/escape attempt, duplicate `case_id`, wrong format/MIME, and the exact category/format counts. Add an intentional replay/duplicate-source case whose manifest entries reuse the same source SHA/content and assert corpus validation accepts it; repeated digest alone is not a uniqueness constraint. Add request-driven lookup tests proving: wrong customer reference returns no customer unless that value exists; wrong name follows the existing `normalize_customer_name(...)` rule; wrong/unknown SKU and missing SKU return `None` in the predicted position; returned SKU equals the requested predicted SKU; candidate ordering is canonical; and expected values cannot affect lookup. Add a test that a predicted wrong customer/SKU cannot receive the expected customer/product data.

**Focused command:** `uv run pytest tests/evaluation/test_corpus_contracts.py tests/evaluation/test_trusted_lookup.py -q`.

**Minimal implementation:** author the small fixture set and manifest, verify digests at load time, reject unsafe paths before reading, and implement lookup from the request only. Keep manifest facts such as prior duplicate/document state separate from catalog lookup records.

**GREEN:** all 36 sources load and verify; distribution and format/MIME assertions pass; the provider follows the existing contract for every request shape; no expected extraction field is consulted by trusted lookup.

**Commit:** `feat(phase11): add v1 evaluation corpus and trusted catalog`.

### Task 3 — Implement canonical positioned scoring and route/issue scoring

**Files:**

- Create `src/opsflow/evaluation/scoring.py` with pure functions:
  - `canonicalize_value(field_name: str, value: object) -> CanonicalValue`;
  - `project_extraction(extraction: ExtractionDraft | ExpectedExtraction) -> CanonicalExtractionProjection`;
  - `score_positioned_extraction(expected: CanonicalExtractionProjection, predicted: CanonicalExtractionProjection) -> PositionedExtractionScore`;
  - `score_validation_outcome(expected: ExpectedValidation | None, actual: CaseResult) -> ValidationOutcomeScore | None`;
  - `score_extraction_quality(results: Sequence[CaseResult], mode: EvaluationMode) -> ExtractionQuality`.
- Create `tests/evaluation/test_scoring.py`.

**Interfaces consumed:** existing `ExtractionDraft`/line fields; Task 1 expected/result models; spec canonicalization and positioned-line rules.

**Interfaces produced:** exact-match, field TP/FP/FN, micro precision/recall/F1, per-field scores, route/issue comparison, and mode-gated extraction-quality values for the result/artifact layers.

**RED:** test NFC normalization, exact case-sensitive identifiers, string trimming rules, Decimal normalization, ISO date normalization, null handling, equal and unequal complete projections, wrong value as one FN plus one FP, missing/extra lines, line-position mismatch, per-field counts, micro formulas including undefined nullable precision/recall/F1, and validation comparison across route, optional approval level, durable pre-approval state, and code/severity issue multiset. Test that parser-only/failure cases bypass extraction and validation scoring cleanly. Test that provider-free input containing a scripted perfect prediction returns `NOT_APPLICABLE` and all live/model quality values `null`; test that only live results whose cases reached real Gemini can contribute quality denominators.

**Focused command:** `uv run pytest tests/evaluation/test_scoring.py -q`.

**Minimal implementation:** implement only the specified canonicalization and positioned comparisons. Keep route/issue scoring separate from extraction quality. Do not infer fuzzy matches, reorder lines, or call a provider.

**GREEN:** scorer self-tests prove the formulas and edge cases; provider-free scoring cannot publish a fake 100% extraction-quality result; live quality excludes cases that did not reach Gemini and records the denominator explicitly.

**Commit:** `feat(phase11): add positioned evaluation scoring`.

### Task 4 — Lock mode-safe structured result serialization

**Files:**

- Extend `src/opsflow/evaluation/models.py` with explicit provider-free contract-evidence fields, live extraction-quality fields, case reachability/attempt fields, limitation/error fields, and result schema version validation.
- Create `tests/evaluation/test_result_contracts.py` cases for provider-free and live result shapes.

**Interfaces consumed:** Task 1 result models; Task 3 score types; approved JSON schema and live/provider-free semantics.

**Interfaces produced:** stable result objects consumed by the M11C runner and M11D artifact writer.

**RED:** assert a provider-free result serializes contract evidence under non-accuracy names, has nullable live/model exact-match/precision/recall/F1/per-field fields, states that no real model was evaluated, and rejects any attempt to populate those fields. Assert live results can distinguish real-provider-reached cases from provider-free scenario evidence. Assert serialized output cannot contain raw source payloads or secrets.

**Focused command:** `uv run pytest tests/evaluation/test_result_contracts.py -q`.

**Minimal implementation:** add validation and serialization rules without writing files or reports. Keep the structured result schema versioned and forward-compatible only where the spec permits.

**GREEN:** result-contract tests pass and a provider-free reference object cannot display fake extraction quality through any normal serialization path.

**Commit:** `feat(phase11): enforce mode-safe evaluation results`.

## M11C — Correctness, Routing & Reliability Evaluation

### Task 5 — Run provider-free cases through existing OpsFlow seams

**Files:**

- Create `src/opsflow/evaluation/runner.py` with the narrow runner interfaces:
  - `run_case(session_factory: async_sessionmaker[AsyncSession], case: CorpusCase, runtime: OrchestrationRuntime, mode: EvaluationMode) -> CaseResult`;
  - `run_corpus(session_factory: async_sessionmaker[AsyncSession], corpus: CorpusManifest, runtime: OrchestrationRuntime, mode: EvaluationMode) -> EvaluationRunResult`.
- Create `src/opsflow/evaluation/doubles.py` for provider-free observation hooks and bounded side-effect probes, using existing protocols rather than new business logic.
- Create `tests/evaluation/test_runner.py`.

**Interfaces consumed:** Task 1–4 contracts; `process_document`; `OrderExtractor`; `FakeProvider`; `execute_orchestration_intake`; `OrchestrationRuntime`; `async_sessionmaker[AsyncSession]`; existing validation application service and persistence session factory; `EvaluationBusinessDataProvider`.

**Interfaces produced:** provider-free per-case/run results containing parser/extraction-contract evidence, durable state, route/issues, provider call counts, side-effect observations, and enough reachability data for later scoring.

**RED:** run focused representative cases through real document processing, extraction, and deterministic validation seams. Prove valid, malformed, unsupported, security, and provider-contract failures are observed with the expected durable result. Patch/assert the provider-free runtime makes no network call and does not instantiate live Gemini or external integration adapters.

**Focused command:** `uv run pytest tests/evaluation/test_runner.py -q`.

**Minimal implementation:** compose the existing application services and fakes; use manifest facts only where they represent OpsFlow-local history; build trusted lookup requests from the predicted draft; record outcomes without duplicating state transitions or validation rules.

**GREEN:** focused runner tests pass; provider-free mode remains network-free and produces contract evidence only; runner output is serializable by Task 4 models.

**Commit:** `feat(phase11): run provider-free corpus through application seams`.

### Task 6 — Exercise durable routing, replay, recovery, notifications, and sync doubles

**Files:**

- Extend `src/opsflow/evaluation/runner.py` with case setup/observation for duplicate, stale/retry, approval, invalid, notification, and order-sync scenarios.
- Extend `src/opsflow/evaluation/doubles.py` with an `OrderSyncStepExecutor` test double, notification outcome observer, logical external-object identity tracker, and bounded authority probe; all must conform to existing application protocols.
- Create `tests/evaluation/test_reliability.py`.

**Interfaces consumed:** existing claim/ownership/recovery functions; review commands; `OrderSyncStepExecutor`; order-sync receipt/coordinator functions; notification intent/claim/outcome service; existing persistence models.

**Interfaces produced:** durable reliability evidence consumed by release-gate scoring and JSON reporting.

**RED:** prove invalid represented cases never execute externally; deterministic-violation cases route exactly to manifest ground truth; duplicate attempts do not add an authoritative order graph/effect; stale/retry cases converge to expected durable state; notifications do not mutate business state; sync doubles produce durable receipts and stable logical external-object uniqueness; authorized retry calls remain attached to the originating case/order.

**Focused command:** `uv run pytest tests/evaluation/test_reliability.py -q`.

**Minimal implementation:** drive the existing commands and coordinators with seeded database state and provider-free doubles. Do not add evaluator-owned retry/state-machine logic or claim physical exactly-once behavior for external HTTP.

**GREEN:** all reliability tests pass and observations are derived from durable application state, receipts, and bounded doubles rather than parallel evaluator state.

**Commit:** `feat(phase11): cover durable evaluation reliability seams`.

### Task 7 — Calculate the five hard release gates and authority/network evidence

**Files:**

- Extend `src/opsflow/evaluation/scoring.py` with pure release-gate aggregation over provider-free case outcomes.
- Extend `src/opsflow/evaluation/runner.py` with complete v1 provider-free corpus execution and direct-LLM-authority probe collection.
- Create `tests/evaluation/test_release_gates.py`.

**Interfaces consumed:** Task 5–6 case outcomes; each `CorpusCase` optional
scenario and validation expectation; `ValidationOutcomeScore` components for
route, optional approval level, durable pre-approval state, and issue
code/severity facts; approved five release-gate definitions; existing
application authority boundaries.

**Interfaces produced:** gate facts and pass/fail reasons included in the structured run result.

**RED:** assert all 36 provider-free cases are included; assert zero invalid execution, exact deterministic-violation routing, exact duplicate blocking, safe malformed/security handling, and zero direct LLM side effects. Add probes showing document/model instructions cannot authorize approval, roles, writes, notifications, external effects, or retry ownership. Add a network guard proving provider-free mode has no live network call.

**Focused command:** `uv run pytest tests/evaluation/test_release_gates.py -q`.

**Minimal implementation:** aggregate the existing observed outcomes; do not weaken a gate for missing evidence, and do not turn fake-provider contract evidence into model quality.

**GREEN:** all five gates are non-tradeable, explicitly named, and calculated over their specified provider-free represented cases; failures include actionable case IDs and do not get hidden by a summary score.

**Commit:** `feat(phase11): enforce Phase 11 release gates`.

## M11D — Performance, Live Gemini, Token & Cost Evaluation

### Task 8 — Add run-scoped timing, provider attribution, token accounting, and Decimal cost rules

**Files:**

- Create `src/opsflow/evaluation/measurements.py` with run-scoped monotonic collectors for parse, deterministic validation, provider-free intake, and live Gemini call timing; `ProviderCallRecord` carrying initial case/order attribution, attempt/retry identity, duration, authoritative input/output/total tokens, pricing snapshot identity/model, and completeness flags; nearest-rank percentile calculation for p50/p95; and complete-usage order aggregation with Decimal-only cost calculation.
- Create one dated immutable pricing snapshot under `evals/pricing/`, named with its effective date and model identifier, containing the authoritative input/output rates and source metadata selected and verified during M11D implementation. Do not browse for or hard-code that snapshot during planning.
- Create `tests/evaluation/test_measurements_cost.py`.

**Interfaces consumed:** Task 1 result models; existing provider result token fields; approved timing definitions; pricing snapshot model identity; `Decimal`.

**Interfaces produced:** run-scoped latency summaries, per-call/per-order usage records, complete/incomplete usage counters, and `estimated_model_cost_per_initial_order` with an explicit denominator.

**RED:** test nearest-rank p50/p95; exclude setup/migration time; attribute multiple Gemini calls and retry calls to one initial order; distinguish no-call order cost `0`; count initial, Gemini-called, zero-call, complete-usage, and incomplete-usage orders; count missing attribution/token/pricing fields; reject missing input tokens, missing output tokens, missing pricing, and wrong pricing model as incomplete for cost purposes; assert any incomplete Gemini-called order makes aggregate cost `null` without partial summation; assert all arithmetic remains Decimal. Also test that extraction/latency evidence remains representable when pricing is unavailable and that a pricing-model mismatch cannot produce a numeric cost.

**Focused command:** `uv run pytest tests/evaluation/test_measurements_cost.py -q`.

**Minimal implementation:** collect timing around the defined boundaries only, preserve authoritative provider token fields without estimates, use dated immutable pricing records supplied later, and apply the spec’s initial-order denominator.

**GREEN:** measurement tests prove no incomplete usage can understate spend; every call has an originating initial case/order; zero-call orders contribute zero; latency summaries are method-labeled and run-scoped.

**Commit:** `feat(phase11): add evaluation timing and complete usage accounting`.

### Task 9 — Guard and safely reset the dedicated evaluation database

**Files:**

- Create `src/opsflow/evaluation/database.py` with `EvaluationDatabaseConfig.from_environment(environ: Mapping[str, str], normal_url: str, migration_test_url: str | None) -> EvaluationDatabaseConfig` parsing `OPSFLOW_EVALUATION_DATABASE_URL`; `assert_evaluation_database_isolated(config: EvaluationDatabaseConfig) -> None` validating PostgreSQL, nonblank database name, distinct normal/migration-test names, and unambiguous strict configuration; `reset_evaluation_application_data(config: EvaluationDatabaseConfig, engine: AsyncEngine) -> None` that rechecks the guard immediately before a transactional, foreign-key-safe delete of only the allowlisted OpsFlow application tables; and `confirm_current_migration_head(alembic_config: Config, expected_revision: str) -> None` without downgrade.
- Create `tests/evaluation/test_evaluation_database.py` before implementing destructive reset behavior.

**Interfaces consumed:** existing `Settings.database_url`, migration-test URL semantics, `Mapping` from `collections.abc`, `AsyncEngine` from SQLAlchemy, `Config` from `alembic.config`, SQLAlchemy URL parsing, existing application metadata/models, and Alembic current-head metadata.

**Interfaces produced:** a fail-closed clean-state operation used by both `make evaluate` and `make evaluate-live`, with no lifecycle-management flag.

**RED:** tests must reject the normal development DB, migration-test DB, non-PostgreSQL URL, blank database name, aliases/ambiguous URLs, and any configuration that cannot prove the guarded evaluation target. Integration tests must seed rows across the order/source-document/line/validation/audit/notification/sync graph, run reset, and prove only the evaluation database application data is cleared; normal and migration-test databases are untouched. Prove migration head remains current and repeated runs begin with equivalent clean state, including duplicate facts, graph counts, notifications, receipts, replay behavior, and timing setup.

**Focused command:** `uv run pytest tests/evaluation/test_evaluation_database.py -q` for guard/unit tests, followed by the isolated PostgreSQL evaluation-database integration invocation documented by the task when the database fixture is available.

**Minimal implementation:** fail closed before any delete; use an explicit application-table allowlist and foreign-key-safe ordering inside a transaction; preserve Alembic tables/current head; never drop/reset/truncate/downgrade the normal or migration-test database. Database creation remains a one-time documented prerequisite, not a command lifecycle feature.

**GREEN:** safety and reset tests pass; both evaluation commands establish clean state themselves before case 1; no undefined “explicit lifecycle management” behavior exists.

**Commit:** `feat(phase11): guard and reset evaluation database state`.

### Task 10 — Write JSON source-of-truth artifacts and Markdown renderer

**Files:**

- Create `src/opsflow/evaluation/artifacts.py` with validated JSON writing, result-schema/version metadata, sanitized reference selection, ignored ad-hoc path handling, and Markdown rendering from an already validated JSON object only.
- Create `tests/evaluation/test_artifacts_commands.py` cases for JSON/report separation and sanitization.
- Add the narrow ignore rules needed for `evals/results/` and local evaluation artifacts; keep selected sanitized evidence under `docs/evaluation/reference/` explicit and reviewable.

**Interfaces consumed:** Task 4 result models; Task 7 gates; Task 8 measurements/cost; corpus/version and run metadata.

**Interfaces produced:** deterministic result JSON as the only reporting source of truth, a Markdown renderer that consumes JSON and never reruns scoring or reads raw documents, and a safe distinction between ignored ad-hoc output and selected sanitized reference evidence.

**RED:** write JSON, mutate or remove any source/input object, render Markdown from the JSON, and assert the report is unchanged; attempt raw-document/secret serialization and assert rejection; assert ad-hoc files under `evals/results/` are ignored while an explicitly selected sanitized reference path is not silently treated as generated output.

**Focused command:** `uv run pytest tests/evaluation/test_artifacts_commands.py -q`.

**Minimal implementation:** validate the result before writing, include contract/mode/denominator/limitation metadata, render tables and gate explanations from JSON fields only, and never include raw documents or credentials.

**GREEN:** artifact tests pass; a Markdown report cannot invent a score not present in JSON and cannot convert provider-free evidence into model accuracy.

**Commit:** `feat(phase11): add JSON and Markdown evaluation artifacts`.

### Task 11 — Add exact commands and live Gemini preflight

**Files:**

- Create `src/opsflow/evaluation/commands.py` with provider-free/live command entrypoints, preflight validation, evaluation-database reset invocation, corpus execution, and artifact publication orchestration.
- Create `tests/evaluation/test_live_preflight.py`.
- Extend `tests/evaluation/test_artifacts_commands.py` for command mode/result behavior.
- Modify `Makefile` with exactly `make evaluate` and `make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1` targets; do not add a lifecycle flag or CI live target.
- Modify `docs/development/development-guide.md` only as needed to document one-time evaluation database setup, exact commands, safety guard, and live opt-in.

**Interfaces consumed:** existing `GeminiConfig` semantics; `Settings` environment names; Task 5 runner; Task 8 measurements; Task 9 database guard/reset; Task 10 artifact writer; `evals/corpus/v1/manifest.json`.

**Interfaces produced:** exact reproducible command behavior and preflight errors before case 1.

**RED:** assert live mode refuses missing/blank opt-in, blank API key, blank model, non-finite timeout, zero timeout, and negative timeout before loading/executing case 1; these are the complete live execution preflight checks. Assert provider-free mode requires no Gemini configuration and runs all 36 cases; assert live mode uses no fake fallback. Separately test that valid live runtime configuration can proceed when pricing is unavailable, preserving extraction, latency, call-count, and authoritative-token evidence while cost is `null`/unavailable with an explicit reason. Before calculating cost, assert configured live model must match the selected pricing snapshot model; mismatch produces unavailable/error cost and never a numeric value or another model’s price. Assert no normal CI command invokes live mode.

**Focused command:** `uv run pytest tests/evaluation/test_live_preflight.py tests/evaluation/test_artifacts_commands.py -q`.

**Minimal implementation:** reuse current Gemini runtime/configuration validation rather than introducing evaluation-specific defaults; perform only the four runtime preflight checks, then the isolation guard, clean reset, and migration-head confirmation before the first corpus case. Load pricing for cost calculation after provider evidence exists; missing pricing or model mismatch limits cost only and does not block truthful live extraction/latency evidence. Both modes load the same v1 manifest, source SHAs, and human-authored ground truth. Provider-free mode executes the complete 36-case release-gate corpus; live mode uses that same corpus/version, while deterministic injected-fault cases remain explicitly provider-free scenario evidence rather than being attributed to Gemini.

**GREEN:** command tests pass; `make evaluate` is provider-free and `$0`; `make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1` is explicit, fails closed, and never silently evaluates scripted output as Gemini quality.

**Commit:** `feat(phase11): add evaluation commands and live preflight`.

### Task 12 — Produce and select the mandatory M11D reference evidence

**Files:**

- Create `tests/evaluation/test_reference_run.py` for reference-selection acceptance rules.
- Create the mandatory sanitized provider-free reference pair:
  - `docs/evaluation/reference/phase-11-provider-free-baseline.json`;
  - `docs/evaluation/reference/phase-11-provider-free-baseline.md`.
- If an explicitly authorized live run is configured and completed, create the optional sanitized pair:
  - `docs/evaluation/reference/phase-11-live-gemini-reference.json`;
  - `docs/evaluation/reference/phase-11-live-gemini-reference.md`.
- If the optional live run is unavailable, create `docs/evaluation/reference/phase-11-live-gemini-unavailable.md` recording that real LLM extraction and cost evidence is unavailable; do not substitute provider-free scores.
- Do not commit generated scratch output from `evals/results/`.

**Interfaces consumed:** Task 11 commands; Task 10 JSON writer/Markdown renderer; Task 9 guarded database reset; the v1 manifest and source SHAs; `EvaluationRunResult` and its schema/version metadata.

**Interfaces produced:** the committed mandatory provider-free M11E baseline and, only when explicitly authorized and configured, the optional live reference evidence. The JSON and Markdown in each pair must come from the same run, with Markdown rendered from that exact JSON.

**RED:** add acceptance tests that reject reference selection unless the JSON records the complete 36-case corpus, exact Git SHA, corpus version, environment metadata, result schema, provider-free extraction quality `NOT_APPLICABLE`, latency summaries, passing five release gates, limitations, and no raw source material/secrets. Assert the selected Markdown is rendered from the selected JSON and cannot carry different metrics. Add optional-live acceptance cases for reached-Gemini denominator, model identifier, exact/field metrics, provider latency, authoritative token availability, and cost limitation when pricing is unavailable or mismatched.

**Focused command:** `uv run pytest tests/evaluation/test_reference_run.py tests/evaluation/test_artifacts_commands.py -q`.

**Minimal implementation:** after all M11D implementation tests pass, use a clean guarded evaluation database and run the exact `make evaluate` command. Require all 36 cases and all five provider-free gates to pass before selecting the output. Inspect the generated JSON fields listed above, generate Markdown from that JSON, sanitize only permitted metadata, and copy/select the pair under the fixed reference paths. If explicitly authorized live credentials are available, run exactly `make evaluate-live OPSFLOW_EVALUATION_LIVE_GEMINI=1` over the same corpus/version/source truth and select only truthful sanitized live evidence; otherwise record live unavailability. A matching dated pricing snapshot is preferred for live cost evidence, but missing/mismatched pricing limits cost and does not invalidate real extraction or latency evidence.

**GREEN:** the provider-free pair is committed from one passing `$0` run and becomes the mandatory M11E provider-free baseline; any live pair or unavailability record is explicit, sanitized, and never used to relabel provider-free evidence as model quality.

**Commit:** `docs(phase11): record M11D reference evidence`.

## M11E — Measurement-Driven Optimization & Regression Comparison

### Task 13 — Validate comparison invariants and make the baseline decision

**Files:**

- Create `src/opsflow/evaluation/comparison.py` with `compare_runs(baseline: EvaluationRunResult, candidate: EvaluationRunResult) -> ComparisonResult` and comparison metadata validation over corpus version, result schema version, scorer/evaluation contract version, mode/command, pricing snapshot for live cost, Gemini model for live comparison, Python major/minor and dependency lock, platform/CPU, database engine/version family, and timing/sample methodology. It must explicitly allow run ID, timestamps, and Git SHA to differ and require both Git SHAs in comparison output.
- Create `tests/evaluation/test_comparison.py`.
- Create the selected sanitized decision evidence at `docs/evaluation/reference/phase-11-baseline-decision.md` only after the mandatory provider-free baseline has been inspected; it must record the measured bottleneck ranking, comparison metadata, and either the exact justified change or `No optimization justified by the measured baseline`.

**Interfaces consumed:** Task 8 measurements/artifacts; Task 11 command metadata; mandatory `docs/evaluation/reference/phase-11-provider-free-baseline.json`; optional `docs/evaluation/reference/phase-11-live-gemini-reference.json` when present, otherwise the explicit live-unavailability record; current Git SHA and dependency/platform/database facts.

**Interfaces produced:** a comparison result that separates correctness/safety comparability from latency comparability and a durable baseline decision for the next conditional task.

**RED:** test baseline/candidate pairs with allowed run ID/timestamp/Git SHA differences; reject corpus/schema/contract/mode/pricing/model/runtime/platform/database/method differences; allow correctness comparison when only latency fields differ but mark latency delta non-comparable; reject any claimed optimization win without comparable latency fields; require both Git SHAs.

**Focused command:** `uv run pytest tests/evaluation/test_comparison.py -q`.

**Minimal implementation:** first inspect the mandatory committed provider-free baseline and optional committed live reference, then rank actual measured bottlenecks. Apply the comparison contract to the baseline decision. If no justified change exists, record the exact no-change outcome and preserve baseline evidence; do not create an optimization patch. If a bottleneck exists, record its exact metric and smallest proposed change before any implementation.

**GREEN:** comparison tests pass; no unmeasured optimization is authorized; latency is never presented as improved across non-comparable environments; a no-change decision is a valid successful M11E outcome.

**Commit:** `feat(phase11): add baseline comparison invariants`.

### Task 14 — Conditionally implement and remeasure one justified optimization

**Files:**

- No production or evaluation implementation file is authorized before Task 13 produces a measured bottleneck decision.
- If Task 13 records no justified change, create no optimization code; preserve the selected baseline and close M11E with the decision evidence.
- If Task 13 records a justified change, modify only the exact production/evaluation path named in that decision record, add its focused regression/performance test beside the owning existing module, and update only the comparison/reference evidence required to rerun the same contract. The decision record is the source of the exact path list; do not broaden it to caching, concurrency, model switching, OCR, queueing, prompt compression, or batching without new measured evidence.

**Interfaces consumed:** Task 13 decision record; existing production seam and tests; Task 11 command; Task 8 measurements; all five release gates.

**Interfaces produced:** a candidate result using the same corpus/version, scoring contract, mode, pricing/model, runtime, platform, database, and timing methodology, or an explicit no-change M11E result.

**RED:** for a justified change, add a failing focused regression/performance assertion for the measured bottleneck and rerun all relevant correctness/safety gates before accepting a candidate. For no-change, add a failing test to the comparison evidence if it would incorrectly label the baseline as improved.

**Focused command:** the owning focused test command named by the baseline decision, followed by `uv run pytest tests/evaluation -q` and the comparison command from Task 13.

**Minimal implementation:** make the smallest measured change, preserve every release gate, rerun the exact evaluation contract, and compare only through `comparison.py`. If latency metadata is non-comparable, report correctness/safety comparison and mark latency deltas unavailable.

**GREEN:** the justified candidate passes focused and full evaluation tests, all five gates remain passing, cost/token/report semantics remain intact, and any claimed improvement has comparable metadata. A no-change result remains accepted when no optimization is justified.

**Commit:** `perf(phase11): apply measured optimization` only when the conditional branch is justified; otherwise `docs(phase11): record no justified optimization`.

## M11F — Independent Phase 11 Audit & Closeout

M11F begins only after M11E has completed, received independent technical
review, had findings remediated and re-reviewed, and received human approval.
At that point the approved technical baseline SHA is frozen and the M11E
implementation context stops. M11F is not a continuation of that context.

The M11F handoff starts a fresh Codex context/session with the frozen technical
baseline SHA, approved M11A design, approved implementation plan, repository
sources of truth, and selected reference evidence. Its audit-only prompt must
state that the new agent may inspect code and evidence, run verification, and
write the audit/status prose permitted below, but must not implement or silently
remediate defects. Fresh context means a new session, not a spawned subagent;
repository policy remains one agent with no subagents or multi-agent workflow.

### Task 15 — Perform the independent Phase 11 audit

**Files:**

- Create `docs/audits/phase-11-audit.md`.
- Do not change evaluator behavior or silently fix findings inside the audit task.

**Interfaces consumed:** committed corpus/manifest and SHAs; scorer tests/results; provider-free/live JSON and sanitized reference evidence; database guard/reset tests; command and CI configuration; M11E baseline/candidate/no-change evidence; prior independent audit severity policy.

**Interfaces produced:** an independent audit record covering corpus integrity and 36-case composition, human-authored ground truth, trusted lookup independence, scorer math and positional lines, provider-free/live separation, all release gates, database isolation/reset, reproducibility, p50/p95, token completeness, pricing-model match, Decimal costs, artifact separation, optimization evidence, clean-clone behavior, CI/provider boundaries, Phase 12 scope, and documentation claims.

**RED:** before writing PASS conclusions, run the audit checklist against a clean clone and the selected evidence; record every Critical/High/Medium/Low finding with evidence, severity, owner, and disposition. Do not claim closure when required evidence is absent.

**Focused command:** the audit’s documented read-only verification sequence, including `uv run pytest tests/evaluation -q`, relevant existing regression checks, current-head verification, Markdown-link validation, and pinned Gitleaks scan; no live provider.

**Minimal implementation:** write the audit as an independent assessment using the same severity policy as prior audits. If a Critical, High, or Medium finding exists, record it, mark the audit `FAIL`, leave Phase 11 `IN PROGRESS`, and stop the fresh audit context. Remediation occurs in a separate implementation task/context, followed by independent re-review and a final audit-disposition update that preserves the initial finding.

**GREEN:** the audit explicitly records the evidence and disposition; Phase 11 cannot close with unresolved Critical, High, or Medium findings.

**Commit:** `docs(phase11): add independent evaluation audit`.

### Task 16 — Close Phase 11 only after audit disposition

**Files:**

- Modify `README.md`, `docs/roadmap/project-roadmap.md`, and `docs/development/development-guide.md` only after independent audit approval, recording M11B–M11F and Phase 11 statuses according to the repository’s completion protocol.
- Update `docs/audits/phase-11-audit.md` only for transparent disposition references; never erase the original finding.

**Interfaces consumed:** Task 15 audit; all committed result/reference evidence; clean-clone and verification outputs.

**Interfaces produced:** final Phase 11 status documentation and a clean, reviewable closeout commit.

**RED:** verify that status cannot be marked complete while Task 15 has unresolved Critical/High/Medium findings, while the final audit has not received independent human review, while live-only evidence is missing from a claim, while generated ad-hoc results are being treated as reference evidence, or while Phase 12 files/claims have leaked into Phase 11.

**Focused command:** the complete Phase 11 verification hierarchy below, with no live Gemini requirement for ordinary CI.

**Minimal implementation:** update only the status facts supported by the approved audit and preserve M11A’s design/plan approval history.

**GREEN:** status documentation, audit, code, artifacts, links, security scan, and clean-clone evidence agree; Phase 12 remains outside the implementation.

**Commit:** `docs(phase11): close evaluation and optimization phase`.

## Evaluation database safety plan

The evaluation command must receive a dedicated PostgreSQL URL through `OPSFLOW_EVALUATION_DATABASE_URL`. The guard parses the URL with the same strict URL machinery used by the repository, requires an actual PostgreSQL driver and nonblank database name, and compares the normalized target against the normal development URL and configured migration-test URL. Any missing, aliased, ambiguous, or unprovable distinction fails closed before cleanup. The command then rechecks the target immediately before reset, deletes only the explicit application-data allowlist in foreign-key-safe order inside a transaction, confirms the current Alembic head, and starts the corpus run. It never creates/drops databases, truncates broad schemas, downgrades migrations, or touches the normal/migration-test databases. The same sequence runs for provider-free and live modes, so a second invocation cannot inherit duplicate facts, graph rows, notifications, receipts, or replay state.

## Live Gemini safety plan

Live mode is a separate command path and cannot be reached through provider-free defaults. Before case 1 it validates only exact opt-in, nonblank API key, nonblank model, and finite positive timeout, using the existing `GeminiConfig` semantics. Pricing availability and pricing-model equality are checked at cost calculation, not live execution preflight. A valid live run may retain extraction exact match, TP/FP/FN, precision/recall/F1, provider latency, call counts, and authoritative token evidence when pricing is unavailable; cost is then `null`/unavailable with an explicit limitation. A pricing-model mismatch never blocks or reclassifies the real model run and never applies another model’s price. No fake provider substitutes for a failed preflight or failed live call. Every provider call is attributed to its originating initial case/order, including authorized retries. Live extraction quality denominators include only corpus cases that actually reached Gemini, while provider-free deterministic fault scenarios remain provider-free evidence and are never attributed to Gemini.

## Verification hierarchy

Execution should progress from the smallest owned check to the full release evidence:

1. Focused RED→GREEN evaluation tests for each task.
2. `uv run pytest tests/evaluation -q`.
3. Existing relevant unit/integration regressions, then `make test-integration`.
4. `make check` and `make security-audit`.
5. Alembic/current-head verification and Docker Compose validation for the isolated evaluation database.
6. Markdown relative-link validation and `git diff --check`.
7. Pinned Gitleaks changed-content scan using the repository’s pinned version.
8. Clean-clone provider-free `make evaluate` verification with no live provider; live Gemini remains separately opt-in and is never required for ordinary CI.

No application tests or live providers are run during this planning task.

## Plan self-review checklist

- M11B owns strict contracts, all 36 human-authored cases, source SHAs/path safety, request-driven trusted lookup, canonical positioned scoring, and mode-safe result foundations.
- M11C owns existing-seam execution, durable routing/replay/recovery/notification/sync observation, authority probes, network isolation, and all five release gates.
- M11D owns timing, nearest-rank percentiles, live/provider attribution, complete-usage Decimal costs, pricing identity, JSON/report separation, guarded DB reset, commands, preflight, and the mandatory provider-free reference run plus optional live/unavailability evidence.
- M11E begins with the committed M11D references, permits a no-change outcome, and forbids non-comparable latency claims and unmeasured optimization categories.
- M11F audits every normative contract independently from a frozen M11E SHA in a fresh context and blocks close for unresolved Critical/High/Medium findings.
- Every Review Focus risk has an owning test: fake-quality leakage (Tasks 3–4), trusted-data bias (Task 2), DB contamination (Task 9), incomplete cost usage (Task 8), and non-comparable optimization (Task 13).
- Manifest-facing types remain human-readable and conditional: named
  `ExpectedExtraction`, optional validation/trusted-data/approval/replay/recovery
  scenarios, serialized `source.path`, and `schema_version`/`corpus_version`.
- `ExpectedExtraction` remains distinct from the internal
  `CanonicalExtractionProjection`; per-case exact match is boolean, while
  aggregate rates use `RateMetric` and preserve undefined values as null.
- Validation scoring exposes route, optional approval level, durable state, and
  code/severity issue-multiset agreement; parser-only/failure cases can omit
  extraction and validation without placeholder objects. Tasks 1–16 use these
  contracts consistently.
- The plan does not add a second state machine, a second retry implementation, a live external benchmark, a Phase 12 deliverable, an implementation-plan file beyond this artifact, or an unresolved placeholder step.
- Production changes are not pre-authorized; any later change must satisfy the documented measurement-gap and regression-test policy.
