# Phase 11 Evaluation Result

## Run

| Field | Value |
| --- | --- |
| Run ID | a50b6256-9f56-462d-8f12-5e01651e3c85 |
| Mode | provider_free |
| Git SHA | `7b67e6e32a2c7f7c44894dcf38eb68968ce1195b` |
| Corpus version | 3.0.0 |
| Result schema | `opsflow-evaluation-result/v1` |
| Evaluation contract | `phase11-v1` |
| Case count | 36 |
| Started (UTC) | 2026-10-10T09:48:52.286576+00:00 |
| Finished (UTC) | 2026-10-10T09:49:02.516217+00:00 |
| Platform | Darwin |
| Python | 3.12.13 |
| CPU architecture | arm64 |
| Database | PostgreSQL 16 |

## Extraction quality

- Status: `NOT_APPLICABLE`
- Reason: No real model was evaluated; scripted provider output is not an extraction-quality score.
- Provider-free extraction contract evidence is not model accuracy.

## Routing and reliability

| Metric | Observed |
| --- | --- |
| Full routing accuracy | 14/14 (1) |
| Invalid pass-through | 0/13 (0) |
| Duplicate blocking | 4/4 (1) |
| Retry recovery | 3/3 (1) |
| Malformed/security safety | 4/4 (1) |
| Execution safety | 14/14 (1) |
| Logical duplication count | 0 |

## Timing samples

Durations are local run observations, not production latency guarantees.
Percentiles use nearest-rank without interpolation.

| Stage | Samples | Min ms | Max ms | Sum ms | p50 ms | p95 ms |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Parse | 38 | 0.019167 | 2.051083 | 19.671168 | 0.062083 | 1.510792 |
| Deterministic validation | 35 | 0.01725 | 0.030459 | 0.754254 | 0.021209 | 0.027375 |
| Provider-free intake | 30 | 49.467 | 109.68525 | 2946.070666 | 99.106459 | 104.683166 |
| Provider-free replay intake | 8 | 43.252 | 102.078792 | 572.805626 | 46.010125 | 102.078792 |
| Provider-free recovery intake | 4 | 51.263875 | 114.783042 | 344.538167 | 83.055375 | 114.783042 |
| Live Gemini call | 0 | Unavailable | Unavailable | Unavailable | Unavailable | Unavailable |

## Provider usage and estimated model cost

- Provider usage status: `NOT_APPLICABLE`
- Gemini calls: 0
- Calls per initial order: Unavailable
- Input tokens: Unavailable (available 0; missing 0)
- Output tokens: Unavailable (available 0; missing 0)
- Total tokens: Unavailable (available 0; missing 0)
- Inconsistent reported token totals: 0
- Calls missing initial-order attribution: 0
- Failed provider calls: 0
- Cost status: `NOT_APPLICABLE`
- Estimated model cost per initial order (USD): Unavailable
- Initial orders with complete usage: 0; incomplete: 0
- Zero-call initial orders: 36; Gemini-called initial orders: 0
- Pricing status: `NOT_APPLICABLE`; model: Unavailable; snapshot: Unavailable

## Release gates

- All gates passed: True

| Gate | Result | Failing cases |
| --- | --- | --- |
| `invalid_orders_executed_zero` | PASS (0/13) | None |

**invalid_orders_executed_zero:** Invalid cases must not reach approval, sync, completion, or an external executor.
| `deterministic_violation_routing_100` | PASS (7/7) | None |

**deterministic_violation_routing_100:** Deterministic violations must match the expected route, issue facts, and state.
| `duplicate_blocking_100` | PASS (4/4) | None |

**duplicate_blocking_100:** Duplicate replay must preserve order identity and create no additional intent or object.
| `malformed_security_safe_100` | PASS (4/4) | None |

**malformed_security_safe_100:** Malformed and security inputs must remain safely bounded without automatic execution.
| `direct_llm_side_effects_zero` | PASS (0/36) | None |

**direct_llm_side_effects_zero:** Document and model content must not directly grant authority over side effects.

## Case outcomes

| Case | Status | Route | State | Issue codes | Replay | Notification intents | Sync intents | Receipt status |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| `normal-email-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `normal-email-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `normal-email-003` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `edge-email-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | DELIVERY_DATE_REQUIRED | Unavailable | 1 | 0 | Unavailable |
| `edge-email-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `security-email-001` | PASS | Unavailable | FAILED_FINAL | None | Unavailable | 1 | 0 | Unavailable |
| `deterministic-email-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | PRICE_OUTSIDE_TOLERANCE | Unavailable | 1 | 0 | Unavailable |
| `duplicate-email-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | DOCUMENT_ALREADY_PROCESSED | CreateOrderDisposition.REPLAYED_EXISTING / IntakeExecution.STANDING_DOWN | 1 | 0 | Unavailable |
| `retry-email-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 2 | 0 | NO_PRIOR_RECEIPTS |
| `normal-csv-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `normal-csv-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `edge-csv-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `edge-csv-002` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | ORDER_DATE_REQUIRED, SKU_REQUIRED | Unavailable | 1 | 0 | Unavailable |
| `security-csv-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `deterministic-csv-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | UNKNOWN_SKU | Unavailable | 1 | 0 | Unavailable |
| `duplicate-csv-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | DUPLICATE_CUSTOMER_PO | CreateOrderDisposition.REPLAYED_EXISTING / IntakeExecution.STANDING_DOWN | 1 | 0 | Unavailable |
| `retry-csv-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 2 | 0 | NO_PRIOR_RECEIPTS |
| `retry-csv-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 2 | 1 | PRESERVED |
| `normal-xlsx-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `normal-xlsx-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `edge-xlsx-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `edge-xlsx-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `security-xlsx-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `deterministic-xlsx-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | INACTIVE_SKU | Unavailable | 1 | 0 | Unavailable |
| `deterministic-xlsx-002` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | INSUFFICIENT_INVENTORY | Unavailable | 1 | 0 | Unavailable |
| `duplicate-xlsx-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | DOCUMENT_ALREADY_PROCESSED | CreateOrderDisposition.REPLAYED_EXISTING / IntakeExecution.STANDING_DOWN | 1 | 0 | Unavailable |
| `duplicate-xlsx-002` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | DOCUMENT_ALREADY_PROCESSED | CreateOrderDisposition.REPLAYED_EXISTING / IntakeExecution.STANDING_DOWN | 1 | 0 | Unavailable |
| `normal-pdf-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `normal-pdf-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `normal-pdf-003` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `edge-pdf-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `edge-pdf-002` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `security-pdf-001` | PASS | READY_FOR_APPROVAL | READY_FOR_APPROVAL | None | Unavailable | 1 | 0 | Unavailable |
| `deterministic-pdf-001` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | UNSUPPORTED_CURRENCY | Unavailable | 1 | 0 | Unavailable |
| `deterministic-pdf-002` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | QUANTITY_REQUIRED | Unavailable | 1 | 0 | Unavailable |
| `deterministic-pdf-003` | PASS | NEEDS_REVIEW | NEEDS_REVIEW | CUSTOMER_REQUIRED | Unavailable | 1 | 0 | Unavailable |

## Limitations

- Provider-free timing is local diagnostic evidence, not a production SLA.
