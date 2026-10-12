# Phase 11 M11E Baseline Decision

## Decision

**Task 14 outcome: `NO_OPTIMIZATION`.** No production or evaluation runtime
behavior is changed. The measured baseline does not demonstrate a specific,
actionable bottleneck that meets the approved Phase 11 optimization contract.

## Evidence inspected

- Mandatory committed provider-free result:
  [`phase-11-provider-free-baseline.json`](phase-11-provider-free-baseline.json),
  run SHA `7b67e6e32a2c7f7c44894dcf38eb68968ce1195b`.
- Two existing local M11D provider-free result artifacts were inspected from
  ignored `evals/results/`; they are scratch evidence, not committed reference
  artifacts. Their run IDs are `0c7374d2-f00b-4cab-8a03-98f91a839376` and
  `85db4855-743c-4778-b05d-4fae30f447a1`; both record run SHA
  `9ecaaef9e2f7bf8e59529228d8576438d1a94f1a`. Their measured summaries are
  transcribed below so this decision does not depend on retaining the ignored
  raw files.
- Explicit no-live-evidence record:
  [`phase-11-live-gemini-unavailable.md`](phase-11-live-gemini-unavailable.md).
- The M11E comparison contract returned correctness-comparable and
  latency-comparable for the committed reference against each M11D run and for
  the two M11D runs against each other. No invariant mismatches were reported.
  The different run IDs, timestamps, and Git SHAs are permitted run identity
  differences; all are reported separately by the comparison result.

All three runs identify result schema `opsflow-evaluation-result/v1`, contract
`phase11-v1`, corpus `3.0.0`, the same 36 case identities and corpus
composition, provider-free mode and `make evaluate`, Python 3.12, `uv.lock`,
Darwin/arm64, PostgreSQL 16, and nearest-rank without interpolation. The
provider-free results contain no Gemini calls; extraction quality and cost
remain `NOT_APPLICABLE`.

## Measured timing evidence

Times are local diagnostic observations, not production SLAs. Percentiles use
nearest-rank without interpolation. Millisecond values are rounded to 0.001 ms.
Counts and p50/p95 below are from the
committed reference, M11D local run A, and M11D local run B, respectively.

| Stage | Samples (ref / A / B) | p50 ms (ref / A / B) | p95 ms (ref / A / B) |
| --- | --- | --- | --- |
| SYNCING recovery intake | 4 / 4 / 4 | 83.055 / 79.772 / 80.874 | 114.783 / 111.238 / 110.928 |
| Normal provider-free intake | 30 / 30 / 30 | 99.106 / 97.877 / 97.920 | 104.683 / 102.166 / 111.161 |
| Duplicate replay intake | 8 / 8 / 8 | 46.010 / 43.876 / 43.588 | 102.079 / 99.484 / 99.443 |
| Document parse | 38 / 38 / 38 | 0.062 / 0.049 / 0.051 | 1.511 / 1.529 / 1.525 |
| Deterministic validation | 35 / 35 / 35 | 0.021 / 0.019 / 0.019 | 0.027 / 0.026 / 0.027 |
| Live Gemini call | 0 / 0 / 0 | unavailable | unavailable |

Recovery has the largest observed p95 but only four samples and is intentionally
reported separately from normal first-attempt intake. Normal provider-free
intake is a broad orchestration measurement around the existing application
intake seam; the evaluator does not break it into database, scripted
extraction, validation, and persistence costs. Its p95 is approximately
105 ms in the reference, then approximately 102 ms and 111 ms in the two
comparable M11D runs. This direction-changing variation does not establish a
reproducible performance defect or identify an internal cause. Parse and
validation timings are much smaller, while replay is separately sampled.

## Correctness, safety, and limits

Each inspected run accounts for 36/36 passing cases and all five hard gates:

- Invalid execution: 0/13.
- Deterministic violation routing: 7/7.
- Duplicate blocking: 4/4.
- Malformed/security handling: 4/4.
- Direct LLM side effects: 0/36.

The active corpus and its source files are unchanged. No live Gemini extraction
accuracy, provider latency, token usage, or model cost was measured, so no live
model or spend improvement can be claimed. The local timing observations do
not imply a production target or SLA.

No optimization justified by the measured baseline. This is the approved
Task 14 no-change outcome: preserve the existing production seams, measurement
boundaries, five release gates, and historical M11D reference evidence. No
optimization candidate or replacement reference result was generated.
