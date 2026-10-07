# Phase 10 — Reliability, Security & Hardening Design

**Status:** M10A `COMPLETE` (approved SHA `ab7cec323e4d45dae57e5d418bc0755175aa0a88`); M10B `COMPLETE` (human-approved technical SHA `765c5030659d6c4d0aebe325b7d35d577766dbfd`); M10C `COMPLETE` (human-approved technical SHA `7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`); M10D `COMPLETE` (human-approved technical SHA `cf0b331864ca2cc5246aa32c7ce12827b79284d0`); M10E `IMPLEMENTED — PENDING HUMAN REVIEW`; M10F `NOT STARTED`; Phase 10 `IN PROGRESS`
**Baseline:** `07710b5b896ae97cd9b9d295906e923a805773a6` (`main` after the Phase 9 closeout and roadmap correction)
**Scope:** repository intelligence, threat/failure modeling, implementation design, and concise M10B–M10E implementation records below. M10F behavior remains outside this document's implementation scope.

## 1. Design decision

Phase 10 will harden the existing Phase 0–9 state machines and integration
seams. It will not introduce a generalized reliability platform. The system
remains a portfolio-sized local application with these invariants:

- AI interprets untrusted source material; deterministic Python code and human
  approval decide business outcomes and side effects.
- n8n transports, schedules, invokes, notifies, and routes bounded results;
  Python owns business correctness, persistence, state transitions, claims,
  retry classification, and integration contracts.
- Odoo, HubSpot, Gmail, and Slack remain adapter/provider boundaries. Provider
  execution is at-least-once where the existing contract says so; the project
  claims at-most-one logical external record or convergent replay under stable
  identities, not physical exactly-once execution.
- `/ready` continues to answer only whether the API can serve its core local
  responsibility, including the database check. External providers and n8n do
  not become readiness dependencies.
- Mandatory development cost remains `$0`. The implementation should use the
  existing Python, PostgreSQL, Docker Compose, n8n, GitHub Actions, and
  standard-library baseline.

The principal new reliability contract is a bounded, explicit recovery path
for an intake claim that commits before a later database failure. The current
Phase 7 behavior documents that matching redelivery can stand down after this
sequence. That is a real undetected-state gap. The fix belongs in M10B and
must preserve ordinary duplicate stand-down and human Retry semantics.

M10A is `COMPLETE` following final human approval at
`ab7cec323e4d45dae57e5d418bc0755175aa0a88`. At that historical M10A closeout,
M10B was recorded as `IN PROGRESS` and M10C through M10F remained `NOT STARTED`;
the later M10B/M10C records below do not change the approved M10A design.

## 2. Repository evidence reviewed

The inventory was based on the final merged repository, not prior reports.
The following implementation areas and evidence were inspected:

| Area | Actual implementation inspected | Representative verification |
| --- | --- | --- |
| Domain and lifecycle | `src/opsflow/domain/`, `src/opsflow/application/`, state transitions, audit events | `tests/unit/domain/`, `tests/integration/test_phase7_failure_matrix.py`, `tests/integration/test_phase9_order_sync_claims.py` |
| Core idempotency | `src/opsflow/application/orders.py`, `src/opsflow/persistence/models.py`, migration `0002` | `tests/unit/application/test_fingerprinting.py`, Phase 2 concurrency/idempotency integration tests |
| Intake and n8n | `src/opsflow/orchestration/`, `src/opsflow/api/orchestration.py`, `workflows/n8n/opsflow-sandbox-intake.json`, `workflows/n8n/opsflow-gmail-intake.json` | `tests/integration/test_phase7_concurrency.py`, `test_phase7_failure_matrix.py`, workflow README and graph checks |
| AI boundary | `src/opsflow/extraction/prompt.py`, `extractor.py`, `gemini.py`, strict Pydantic models | `tests/unit/extraction/test_prompt.py`, `test_gemini.py`, cross-format and prompt-injection fixtures |
| Deterministic validation | `src/opsflow/validation/`, business-data adapters and duplicate checks | Phase 5 unit/integration and orchestration application tests |
| Review/authentication | `src/opsflow/review/auth.py`, review routes and commands, `settings.py` | `tests/unit/test_settings.py`, Phase 6 authorization/concurrency tests |
| Notifications | `src/opsflow/notifications/`, notification routes, notification workflows | `tests/integration/test_phase8_notification_persistence.py`, `test_phase8_notification_api.py`, atomicity tests |
| ERP/CRM synchronization | `src/opsflow/application/order_sync.py`, `order_sync/`, `odoo.py`, `hubspot.py`, migration `0006` | Phase 9 claim, atomicity, Odoo, HubSpot, and API tests |
| Input boundaries | `src/opsflow/documents/limits.py`, parsers, `orchestration/transport.py`, API schemas | document limit/parser tests, Phase 7 transport tests, review/schema tests |
| SQL/data access | `src/opsflow/persistence/`, migrations, SQLAlchemy queries and locks | repository integration tests, migration tests, Ruff/mypy/CI |
| Operations and supply chain | `main.py`, `database.py`, `docker-compose.yml`, `Makefile`, `pyproject.toml`, `web/package-lock.json`, `.github/workflows/ci.yml` | readiness tests, `make check`, CI workflow, final Phase 9 audit |
| Audit and history | `docs/audits/phase-9-audit.md`, final Git history, Gitleaks workflow | final audit disposition and pinned Gitleaks v8.28.0 scan |

The final Phase 9 audit records the known `brace-expansion@5.0.9` advisory as
transitive development-only frontend tooling, absent from the production
bundle and production-only audit, unchanged by Phase 9, and not currently a
production blocker. M10C must preserve that classification unless fresh
evidence changes it; a clean audit number is not a reason to upgrade blindly.

## 3. Control and gap matrix

The category in the second column is intentionally one of the four required
categories. “Sufficient” means the current contract already meets the Phase
10 concern and M10 should preserve it, not reimplement it.

| Phase 10 concern | Category | Current implementation | Relevant tests/evidence | Sufficiency and remaining risk | Owner for remaining work |
| --- | --- | --- | --- | --- | --- |
| Core order-creation idempotency | `IMPLEMENTED — SUFFICIENT` | `Idempotency-Key` is stored in `order_creation_idempotency` with a request fingerprint, unique order link, and atomic graph creation/replay. | Phase 2 idempotency/concurrency tests; `tests/unit/application/test_fingerprinting.py`. | Same key and same fingerprint replay; same key with changed input conflicts. Do not replace the mechanism. | None; regression coverage remains in M10E. |
| Intake request key and source graph | `IMPLEMENTED — HARDENING NEEDED` | Phase 7 derives raw-byte SHA-256, creates one source document, binds the request key/fingerprint/source identity, and claims under a row lock. | `tests/integration/test_phase7_concurrency.py`, `test_phase7_transport.py`, Gmail provenance tests. | Ordinary duplicates stand down, but a committed claim followed by database loss can strand `PROCESSING`/`EXTRACTED` work and make redelivery stand down. | M10B. |
| Source message ID and Gmail identity | `IMPLEMENTED — SUFFICIENT` | Gmail requires `source_system=GMAIL`, a bounded message ID, and exact `gmail:<message_id>` idempotency key; persisted provenance gates approval replies. | `tests/integration/test_phase8_gmail_provenance.py`; Gmail workflow guide. | This is authoritative for Gmail provenance and replay. It is not a global unique constraint across all sources. | None; adversarial replay regression in M10E. |
| Canonical document SHA-256 | `IMPLEMENTED — SUFFICIENT` | Hash is computed from accepted raw bytes and bound to the source and extraction snapshot. `has_processed_source_sha` is a duplicate signal. | document hash tests; extraction snapshot and Phase 7 integration tests. | Hash is supporting identity/source integrity, not the sole order idempotency key. Do not make every equal hash globally unique without a business rule. | None; preserve in M10B/E. |
| Customer + PO duplicate detection | `IMPLEMENTED — SUFFICIENT` | Deterministic validation queries existing customer/PO combinations when both values are trusted/present. | Phase 5 validation matrix and duplicate tests. | This is a supporting duplicate signal, not an authoritative uniqueness constraint. The domain does not prove that customers cannot legitimately reuse a PO. | None unless a future business contract changes. |
| Approval command replay/concurrency | `IMPLEMENTED — SUFFICIENT` | Server-resolved roles, state checks, strong `If-Match`/audit-generation validators, and atomic transition plus audit/notification intent. | Phase 6 command, ABA, and atomicity tests. | Replays cannot silently approve a changed case; external effects begin only after durable approval/sync intent. | None; M10E replay drill. |
| Notification delivery identity and replay | `IMPLEMENTED — SUFFICIENT` | Unique trigger/channel/kind intents, durable claim leases, bounded attempts, stale-token rejection, and finalization. | Phase 8 notification persistence/API/atomicity tests. | External delivery remains at-least-once after a lost outcome, so duplicate Slack/email delivery is observable and isolated from business state. Exactly-once delivery is not claimed. | M10E verifies the stated duplicate outcome. |
| Odoo sale-order identity | `IMPLEMENTED — SUFFICIENT` | Odoo bridge and reconciliation use the stable OpsFlow order identity; persisted Odoo receipt prevents logical duplicate creation. | Phase 9 Odoo replay/lost-response tests. | At-most-one logical Odoo record/convergent replay is the existing contract. | None; preserve M9B/M9C. |
| HubSpot Company identity | `IMPLEMENTED — SUFFICIENT` | Company upsert uses the versioned trusted customer reference identity and portal guard. | HubSpot adapter identity, wrong-portal, and replay tests. | Stable company identity and bounded provider diagnostics are sufficient for current scope. | None; M10E fault drill. |
| HubSpot Deal identity | `IMPLEMENTED — SUFFICIENT` | Deal identity is the OpsFlow order ID; stable `objectWriteTraceId`, search/update behavior, and durable receipt are used. | Phase 9 HubSpot deal replay/lost-response tests. | Prevents duplicate logical deals under at-least-once calls; no exactly-once physical call claim. | None; preserve M9D/M9B. |
| Phase 9 durable receipts and partial sync | `IMPLEMENTED — SUFFICIENT` | One M9B sync row, lease/fence, in-flight checkpoint, one receipt per external step, bounded budget, and first-missing-step resume. | Phase 9 claim, API, atomicity, Odoo, HubSpot tests. | Odoo success followed by HubSpot failure resumes at HubSpot; lost receipt persistence replays stable identities. Do not create a second sync lifecycle. | M10E tests only; M10F audits. |
| n8n intake transport retry | `IMPLEMENTED — SUFFICIENT` | Standard-node graph retries only connection errors/HTTP 503, at most twice after the initial call, preserving source identity. | Workflow graph checks; M7E handoff and README. | n8n owns transport retry only. It does not own business retry or state. | M10B documents/enforces the single-owner contract. |
| AI/provider retry ownership | `IMPLEMENTED — SUFFICIENT` | Gemini SDK retries are disabled; one provider call maps timeout/unavailable/invalid responses to bounded Python errors. | `tests/unit/extraction/test_gemini.py`. | Automatic provider retry is intentionally absent; safe retry is a later human Retry/redelivery path. | M10E fault tests; no generic provider retry. |
| Business-processing retry ownership | `IMPLEMENTED — HARDENING NEEDED` | Processing/extracted classifiers persist `FAILED_RETRYABLE` or `FAILED_FINAL`; human Review Retry creates a generation consumed once by intake redelivery. | `tests/integration/test_phase7_failure_matrix.py`, concurrency tests. | Classifier coverage is explicit, but unexpected exceptions and the post-claim DB failure window can leave a nonterminal state without a durable recovery owner. | M10B. |
| ERP/CRM retry ownership and classification | `IMPLEMENTED — HARDENING NEEDED` | M9B owns leases, attempts, retry generations, provider-step checkpointing, automatic transient delays, and human retry after exhaustion. | Phase 9 claim/failure/API tests. | The catch-all non-final branch and provider/configuration classification need a reviewed table so one failure has one owner and no unsafe duplicate retry. Preserve current inventory/reconciliation semantics unless a test proves a defect. | M10B. |
| External-failure isolation | `IMPLEMENTED — SUFFICIENT` | Notification failures do not alter order state; provider adapters return bounded failures; sync persists completed predecessors and resumes missing steps. | Phase 8 atomicity; Phase 9 partial-sync and diagnostics tests. | Existing isolation is the required foundation. M10B/E should test database/provider boundaries rather than replace adapters. | M10B/E verification. |
| Orchestration authentication and structured creation | `IMPLEMENTED — HARDENING NEEDED` | Fixed server-configured bearer token, constant actor `orchestration:n8n`, constant-time comparison, bounded 401; the existing orchestration dependency protects programmatic intake routes. `POST /v1/orders` is currently not yet behind that dependency. | Phase 7 auth/API and Phase 9 API tests; `src/opsflow/orchestration/auth.py`; `src/opsflow/api/orders.py`. | The service credential must protect `POST /v1/orders` without granting human read/review/approval capability. This remains a local/demo service boundary, not production identity. | M10C: enforce the exact core creation boundary and test separation from human tokens. |
| Human authentication and role authorization | `IMPLEMENTED — HARDENING NEEDED` | Configured development operator bearer tokens resolve server-side to REVIEWER, APPROVER, or ELEVATED_APPROVER; token overlap with orchestration is rejected. Core order reads currently lack the dependency. | settings/auth and Phase 6 authorization tests; `src/opsflow/review/auth.py`; `src/opsflow/api/orders.py`. | `GET /v1/orders`, `GET /v1/orders/{order_id}`, and `GET /v1/orders/{order_id}/audit` must use `get_operator_context` plus `require_view_access`. Any configured human role may view; browser actor/role claims are never trusted. These fixed credentials are local/demo development authentication, not production user identity, OAuth, SSO, sessions, or internet-facing IAM. | M10C: close the core read boundary and document the development-only posture. |
| Provider credential boundaries | `IMPLEMENTED — SUFFICIENT` | Odoo/HubSpot secrets are `SecretStr`; n8n provider credentials remain in local n8n storage and sanitized workflow exports; providers are adapter-owned. | settings tests, workflow hygiene checks, Phase 9 diagnostics tests. | No credentials are passed through LLM prompts or persisted provider responses. | M10C regression scan only. |
| File type and parser validation | `IMPLEMENTED — SUFFICIENT` | Exact supported types, MIME checks, filename basename normalization, PDF signature/encryption/page checks, XLSX ZIP/sheet/row/cell/expanded-size bounds, CSV/text decoding and bounds. | Phase 3 parser/limit/corrupt-input tests; Phase 7 transport tests. | The application document contract is strong. It must not be duplicated or loosened. | M10E adversarial fixtures. |
| HTTP body and multipart resource limits | `MISSING — REQUIRED` | `read_bounded_upload` caps accepted document bytes after Starlette has accepted the multipart request; there is no application-wide body/receive limit. | Existing bounded-upload tests demonstrate only the downstream 10 MiB document cap. | M10C must enforce a 12 MiB absolute request ceiling, an 11 MiB orchestration multipart ceiling, a 512 KiB ordinary JSON ceiling, and a 16 KiB notification command/result ceiling. The parser still owns the exact 10 MiB accepted-document rule; exact-limit documents must remain transportable. | M10C. |
| API field/count bounds | `MISSING — REQUIRED` | Idempotency key, message ID, filename, and list pagination are bounded, but core/review strings, source-document counts, line counts, metadata counts, and Decimal transport representation lack a complete policy. | `src/opsflow/api/schemas.py`, `review_schemas.py`, notification schemas, and Phase 7 transport tests. | M10C must apply the ratified count/string/Decimal caps across every structured and review transport route, preserve stricter existing limits, reject boundary+1 safely, and never truncate. | M10C. |
| Prompt-injection resistance and authority separation | `IMPLEMENTED — SUFFICIENT` | Canonical source is marked untrusted in an extraction-only prompt; strict provider schema/evidence grounding and deterministic validation prohibit LLM side effects. | prompt, provider, cross-format, and adversarial fixtures. | No generic prompt firewall is justified. Add regression cases only where M10E exercises the existing boundary. | M10E regression coverage. |
| Safe validation/provider errors | `IMPLEMENTED — HARDENING NEEDED` | Orchestration, review, notification, and provider adapters use bounded errors; core route validation is less consistently non-echoing and unhandled exceptions have no common safe envelope. | route/API tests and provider diagnostic tests. | M10C should standardize safe error codes without exposing bodies, tokens, SQL, or tracebacks. | M10C. |
| SQL injection and query safety | `IMPLEMENTED — SUFFICIENT` | SQLAlchemy expressions, typed enums/UUIDs, fixed `SELECT 1` and fixed interval fragments, and no user-derived raw SQL/sort expression. | repository/migration tests; source audit of `text()`/`execute()` uses. | No ORM rewrite or SQL abstraction is justified. Add a static review guard and regression test for future raw SQL. | M10C verification only. |
| Secret storage and history hygiene | `IMPLEMENTED — SUFFICIENT` | `.env` ignored, `.env.example` sanitized, `SecretStr` settings, sanitized workflows, CI full-history Gitleaks v8.28.0. | final Phase 9 audit and CI workflow. | Existing secret posture is adequate; keep scans and safe fixtures. | M10C policy/check maintenance. |
| Sensitive logging | `MISSING — REQUIRED` | There is no application logging layer; provider failures are intentionally bounded but there is no allowlisted log policy or redaction test. | adapter tests assert raw diagnostics do not leak; absence of logger instrumentation verified in source. | Add a small allowlist-based structured logger and redaction tests, never log payloads/tokens/provider bodies. | M10D, with security regression in M10E. |
| Structured logs/correlation/latency | `MISSING — REQUIRED` | No request ID, n8n workflow correlation, order/provider fields, duration, or bounded failure-code log events exist. | No current application instrumentation; readiness tests are separate. | This is the highest-value observability gap and should be implemented without a hosted stack. | M10D. |
| LLM usage visibility | `MISSING — REQUIRED` | Gemini adapter returns only normalized extraction output; no provider usage metadata is persisted or logged. | Gemini tests intentionally verify SDK object/body is not retained. | Expose usage only when the provider response supplies trustworthy counts; otherwise record `unavailable`, never estimate. | M10D, then Phase 11 may consume it. |
| Basic operational metrics | `MISSING — REQUIRED` | No counters/histograms or metrics endpoint/library exists. | CI/readiness evidence only. | Add only a small standard-library process-local registry. Dimensions are fixed/bounded: route class/name, HTTP status/class, provider, operation, state, retry outcome, and bounded failure code. Request/workflow/order/customer/PO/filename/actor/email/raw-exception values are log-only, never metric labels. Reset on restart is acceptable and documented; no Prometheus/Grafana/OTel. | M10D. |
| Core readiness | `IMPLEMENTED — SUFFICIENT` | `/health` is liveness; `/ready` performs only database `SELECT 1` and returns bounded 200/503. | `tests/integration/test_readiness.py`, Compose healthcheck. | Do not make readiness depend on Gmail, Slack, Gemini, Odoo, HubSpot, or n8n. | None; M10D regression test. |
| Integration/provider health visibility | `MISSING — REQUIRED` | No separate health view exists beyond readiness and provider execution failures. | Compose/API health checks only. | Add passive, non-blocking, human-view-protected diagnostics only: configured/unconfigured, healthy/unavailable from the last real operation, not checked/no observation, and bounded last failure code/time where justified. Do not actively call Gemini, Gmail, Slack, Odoo, HubSpot, or n8n. `/ready` remains database-only. | M10D. |
| Dependency vulnerability policy | `IMPLEMENTED — HARDENING NEEDED` | npm audit and Gitleaks exist in evidence/CI; the known `brace-expansion@5.0.9` advisory is classified as transitive dev-only and non-production. | final Phase 9 audit; `.github/workflows/ci.yml`; `web/package-lock.json`; verified `uv 0.12.2` and `pip-audit 2.10.1` command behavior. | M10C must add a pinned developer/CI-only `pip-audit==2.10.1` audit of a frozen production-only `uv export`, excluding dev groups, without mutating `uv.lock` or the runtime image. Production Python vulnerabilities fail by default; visible, human-approved, evidence-based exceptions are required. Preserve the frontend advisory classification and `npm audit --omit=dev --audit-level=high`. | M10C. |
| Failure drills and clean-clone proof | `MISSING — REQUIRED` | Individual phase tests and sandbox guides exist; no bounded whole-system fault-injection matrix or Phase 10 clean-clone gate exists. | Phase 7/8/9 integration evidence is phase-specific. | M10E must use fakes/fault injection by default and make live provider checks explicit opt-in. | M10E/M10F. |
| Unsupported enterprise architecture, Phase 11 evaluation, and Phase 12 release work | `OUT OF SCOPE` | The repository has no OAuth/OIDC server, user-account system, Vault, WAF, service mesh, Kubernetes, hosted observability stack, multi-tenancy, billing, benchmark program, or portfolio-release capability. | Roadmap Phase 11/12 boundaries; current Compose/CI/repository inventory. | Adding these would exceed the portfolio complexity/cost budget and the M10A brief. They are not reliability/security gaps for this repository. | None in Phase 10; revisit only in the named later phase if explicitly approved. |

## 4. Identity contract

The following identities have different meanings. Phase 10 must not turn every
duplicate signal into a database uniqueness constraint.

| Identity | Classification | Authority and use |
| --- | --- | --- |
| Core `Idempotency-Key` plus canonical request fingerprint | Authoritative idempotency key | Owns Phase 2 order graph creation/replay. A changed fingerprint is a conflict. |
| Gmail `gmail:<message_id>` plus persisted `source_system=GMAIL` | Authoritative source/intake replay key | Binds one Gmail event to one source graph and gates the sender-only approval reply. It is not a universal source-message uniqueness rule for other systems. |
| Raw accepted document SHA-256 | Supporting duplicate/integrity signal | Binds source bytes to processing and snapshots; it can flag previously processed content but cannot identify a business order by itself. |
| Customer reference + PO number | Supporting business duplicate signal | The validation engine checks the pair when trusted values exist. The current domain does not prove global uniqueness; no constraint is proposed. |
| Review `If-Match`/audit generation | Concurrency validator | Prevents stale human commands and ABA replay. It is not an intake idempotency key. |
| Notification intent ID, claim token, trigger/channel/kind unique key | Authoritative delivery claim identity | Ensures one durable logical intent/claim generation; provider delivery remains at-least-once after lost acknowledgement. |
| Odoo OpsFlow order identity and persisted sale-order receipt | Authoritative external replay identity | Adapter reconciliation and M9B receipt recovery ensure at-most-one logical Odoo record. |
| HubSpot versioned customer identity and OpsFlow order deal identity | Authoritative external upsert identity | Company and Deal replays converge on the existing logical record; portal guard prevents cross-portal writes. |
| M9B order-sync row, claim token, generation, and step receipts | Authoritative synchronization lifecycle identity | One durable sync lifecycle owns all ERP/CRM steps and recovery. |
| Request ID and n8n workflow execution ID | Correlation identifiers only | Join logs and operational diagnostics; neither grants authority, determines replay, or becomes a business uniqueness constraint. |

## 5. Threat model

This model covers the actual local Compose/API/provider system. It does not
assume multi-tenancy, public-internet exposure, billing, or a cloud control
plane.

| Trust boundary / threat | Untrusted input and harmful effect | Existing control | Remaining gap | Required Phase 10 control | Verification |
| --- | --- | --- | --- | --- | --- |
| External document/email sender | Malicious text, spreadsheet formulas/content, embedded “approve” instructions, malformed or huge bytes could influence routing or exhaust resources. | Parser/type/size limits; canonicalization; prompt marks source as data; deterministic validation; no LLM side effects. | HTTP envelope/body limits and some API field counts are absent. | M10C receive/body and transport caps; M10E hostile fixtures and resource-bound tests. | Provider-free tests with prompt injection, corrupt, boundary, and oversized fixtures. |
| Browser/user | Forged actor/role, stale command, overlong draft, unauthorized approval/retry, or sensitive read. | Server-resolved development operator tokens, fixed roles, `If-Match`, review state checks, bounded schemas. | Core order reads and structured creation are not yet separated by their required credentials; the token model is only local/demo development authentication. | M10C must require human view access for the three core reads and the orchestration credential for `POST /v1/orders`; no browser actor/role claims, fourth role, OAuth, SSO, session, or production-IAM claim. | 401/403/credential-separation/stale-replay route tests. |
| n8n | Forged service call, repeated delivery, workflow retry loop, leaked provider secret, or business decision in a workflow. | Fixed orchestration bearer; n8n only transports/routes; bounded intake retry; sanitized exports; Phase 9 no retry loop. | Claim recovery after DB loss needs one explicit owner; workflow correlation is absent. | M10B recovery contract and graph regression; M10D correlation; M10C credential/input review. | Workflow graph assertions and repeated synthetic deliveries. |
| OpsFlow API | Unbounded request, reflected validation/provider diagnostics, forged credentials, missing auth, or unsafe error handling. | FastAPI/Pydantic, bounded specialized routes, safe adapter errors, local Compose port binding. | No global receive limit, no complete transport cap table, open core routes, and no security telemetry. | M10C exact receive/auth/error policy; M10D allowlisted logs/metrics and protected diagnostics. | HTTP boundary, credential-separation, secret-sentinel, and local-only deployment checks. |
| LLM provider | Prompt injection in source, timeout, malformed/unsafe output, token/data leakage. | Extraction-only prompt, strict `extra=forbid` schema, evidence grounding, deterministic post-validation, timeout, SDK retry disabled. | Usage/latency visibility absent; unexpected application exceptions can be under-observed. | M10D optional trustworthy usage metadata and provider timing; M10E timeout/invalid fixtures. | Fake provider fault injection and prompt-injection regression; no live provider in CI. |
| PostgreSQL | Unavailability, transaction rollback, lock contention, query injection, partial persistence. | SQLAlchemy parameterized expressions, transactions, row locks, `pool_pre_ping`, durable audit/receipts, `/ready`. | Intake claim can commit before later persistence; request correlation/diagnostics absent. | M10B claim/recovery proof; M10C SQL and limits review; M10D bounded DB failure telemetry. | PostgreSQL interruption/transaction fault tests and replay checks. |
| Gmail/Slack | Timeout, rejected send, provider error, lost outcome acknowledgement, duplicate external delivery. | Python-owned durable intents/leases/attempts; n8n transport only; fixed payloads and bounded references. | At-least-once duplicate delivery remains possible by contract; visibility is limited. | Preserve isolation; add explicit duplicate/failed-delivery metrics and fault drills, not exactly-once claims. | Fake transport loss-after-success and retry/final tests; live sandbox only opt-in. |
| Odoo | Timeout after possible commit, duplicate create, bad credential, invalid response, wrong data. | Adapter timeout, stable bridge identity, lookup/reconciliation, M9B in-flight checkpoint/receipt, provider diagnostics redaction. | Cross-boundary classification and lost local receipt recovery need whole-system proof. | M10B failure table/replay tests; M10E provider fake faults. | Odoo fake with commit-then-timeout, invalid response, and recovery. |
| HubSpot | Wrong portal, timeout/partial success, deal/company mismatch, bad credential, invalid response. | Verified portal ID, versioned company/deal identities, stage-safe update, stable trace, durable receipts. | Whole-system wrong-portal/partial-sync observability and classification need a single documented owner. | M10B preserve receipts and classify config/provider errors; M10E fault injection. | HubSpot fake and explicit opt-in sandbox checks. |

## 6. Failure and retry model

The owner column is deliberately singular. n8n may retry transport only where
the existing workflow says it may; it never retries business state, provider
effects, or database recovery on its own.

| Scenario | HTTP/business outcome | Durable state | Single retry owner and mode | External effects / replay | Observable signal |
| --- | --- | --- | --- | --- | --- |
| Duplicate intake with same key/fingerprint/source | `200` replay or `202` stand-down according to current lifecycle | Existing order graph and audit remain authoritative | Python Phase 2/7 idempotency and claim logic; n8n may repeat only its bounded transport call | No second order/source/provider call; same bytes/source identity required | Replay flag, order ID, bounded duplicate event/metric |
| Same key with changed request/source | `409` conflict | No mutation to the original graph | No retry; caller must choose a new request | No external effects | `IDEMPOTENCY_CONFLICT` / source conflict |
| Malformed or unsupported document | `200`/terminal business result after claim, current classifier | `FAILED_FINAL` with failure origin/audit and failure notification intent | No automatic retry; human cannot turn a deterministic malformed input into a provider retry | No ERP/CRM mutation; replay stands down | bounded final failure code and order ID |
| Oversized document or request | `422`/`413` at boundary; no order for rejected envelope | No durable order when rejected before creation; document-limit failures after claim follow final classifier | No retry; sender must submit a bounded valid input | No external effects | bounded input-limit code and request ID |
| Prompt injection in source content | Normal extraction if fields are valid, otherwise existing validation/final failure path | No state change based on embedded instruction; trusted routing remains deterministic | No special retry; human review only when deterministic rules require it | No automatic approval or external effect | prompt-safety regression result; no source text in logs |
| LLM timeout/unavailable | Current processing failure response with persisted `FAILED_RETRYABLE` | Failure origin `PROCESSING` or `EXTRACTED`, audit/notification durable | Human Review Retry, followed by one authorized n8n redelivery; no SDK/n8n business retry | No external mutation; replay consumes one restore generation | provider code, duration, attempt/generation |
| LLM malformed/invalid response | Current processing/extraction final failure | `FAILED_FINAL`, failure origin/audit durable | No automatic retry; operator supplies a new input or a future explicit human retry policy | No external mutation | bounded invalid-response code |
| PostgreSQL unavailable before creation/claim | `503` unavailable | No claimed business state if transaction did not commit | Caller/n8n transport may retry the same idempotent request; Python owns eventual replay | No provider call before durable claim | DB-unavailable code, request ID, duration |
| PostgreSQL fails after intake claim or during result persistence | `503` bounded-unavailability result; the committed order remains `PROCESSING`/`EXTRACTED` under its durable intake fence | The fence remains until expiry; later identical delivery can recover only the known stale owner, while the stale worker cannot persist | Phase 7 durable intake lease/recovery owner; n8n only repeats transport after the API is available | No external side effect occurred in Phase 7; extraction may replay under the same source identity | recovery audit event, bounded stale-owner result, and order ID |
| Persistence fails after Odoo/HubSpot success | Sync endpoint returns bounded unavailable/recovery result | In-flight step remains or durable receipt is absent; M9B checkpoint is authoritative | M9B sync coordinator on next eligible tick; human Retry only after exhaustion | Stable provider identity reconciles possible existing record; no new logical record | in-flight step, provider, receipt/recovery metric |
| Gmail or Slack failure | Notification endpoint records outcome; order business response is not changed | Intent remains retryable until bounded attempt three, then `FAILED_FINAL` | Python notification lease/schedule owner; n8n performs one provider call and reports outcome | A lost successful outcome may duplicate delivery; business state remains unchanged | channel, attempt, bounded failure code |
| Odoo timeout/unavailable response | Sync result `retry_wait` or `needs_review` per M9B | `SYNCING` with failed step/retry schedule or `FAILED_RETRYABLE` after budget | M9B automatic transient retry up to limit, then human Retry | Odoo stable identity/reconciliation handles uncertain commit | step, code, attempt, next-attempt time |
| HubSpot timeout/unavailable response | Same M9B bounded sync outcome | Prior Odoo receipt remains; HubSpot step remains missing/retryable | M9B only; n8n has no retry loop | Replays only missing HubSpot logical identity | provider/step and receipt count |
| Odoo success followed by HubSpot failure | No completion claim; bounded sync result | Odoo receipt durable, order `SYNCING`, HubSpot step failed/missing | M9B resumes at first missing HubSpot step | Odoo is not repeated | receipt summary and failure code |
| Repeated n8n order-sync execution | `no_work`, `retry_wait`, or current bounded result | Row lock/fence and sync lifecycle unchanged | M9B claim/lease owner; n8n schedule is not a retry owner | At most one active worker; stale token cannot mutate | claim result, order ID, workflow correlation |
| Stale worker/claim | Bounded stale/recovery result | M9B lease rotates; after bounded expirations `FAILED_RETRYABLE` | M9B lease owner; human Retry after exhaustion | Fencing prevents stale side effects from being recorded | lease expiry, generation, worker result |
| Partial configuration or bad credential | `503` before claim when configuration is absent; provider failure when configured but unusable | No sync intent mutation before claim for absent config; otherwise bounded M9B failure | M10B classification table chooses no duplicate owner; configuration correction/operator action, not an n8n loop | No provider write if preflight rejects; stable identity for uncertain calls | sanitized config/provider code |
| Wrong HubSpot portal | Existing adapter fails closed before company/deal mutation | Sync failure must remain bounded and operator-visible; M10B confirms final/retry classification without repeating unsafe writes | Operator/configuration correction; do not let n8n retry business state | No cross-portal mutation | portal guard failure code, no portal ID/secret leakage |

### M10B stale-ownership contract

The current Phase 7 claim commits `PROCESSING` plus
`ORDER_PROCESSING_STARTED`, then parsing/provider work and later persistence run
outside that transaction. A database loss after the claim can therefore leave
ordinary matching redelivery looking at `PROCESSING` or `EXTRACTED` and standing
down. Phase 7 has no durable lease or fencing token comparable to M9B.

M10B must not make every bare `PROCESSING` or `EXTRACTED` delivery resumable.
Before choosing a lease schema or timeout, M10B must inspect and record:

- every Phase 7 parser, processing, and provider timeout. Current evidence is a
  configurable Gemini timeout (the checked-in example is 30 seconds), disabled
  SDK retries, and no aggregate Phase 7 deadline;
- n8n intake request timeout as observed in the pinned runtime and its current
  three-total-attempt transport behavior with two one-second waits. The
  exported intake nodes do not set an explicit request timeout, so the pinned
  runtime default must be verified rather than assumed;
- the business-data provider timeout used on the Phase 7 path, when configured.
  Current Odoo calls use a 20-second per-request timeout; one validation lookup
  can make several setup/customer/product calls and has no aggregate deadline;
- relevant PostgreSQL connection, statement, lock, transaction, and
  persistence-operation bounds. Current engine setup only enables
  `pool_pre_ping`; it does not establish these deadlines; and
- the longest valid single intake execution under the existing 10 MiB and
  parser limits.

If those facts do not establish a defensible total execution maximum, M10B
must define that bounded maximum first. Any recovery lease must be longer than
that complete execution budget. The likely minimal implementation is a durable
intake execution lease and fencing token, possibly with a small migration, but
the exact columns, values, and migration decision belong to M10B evidence and
tests. M10B must not create a generic worker framework or reuse the M9B sync
state machine.

The resulting contract must prove that an active owner cannot be reclaimed, a
stale owner can be recovered after the defined bound, and a stale worker cannot
persist over a newer owner. Normal duplicate delivery must still stand down;
human Retry generation semantics must remain authoritative; no second order or
source graph may be created; and n8n must not acquire business-retry state.

Fresh PostgreSQL concurrency/fault tests are mandatory for concurrent
duplicates during active ownership, stale lease recovery, stale-token
persistence rejection, database loss after claim, database loss after
extraction/provider work, ordinary duplicate stand-down, human Retry, and
source/fingerprint mismatch. M10B must test these edges and the complete M9B
failure-code table without replacing the existing Phase 7 state machine or M9B
coordinator merely to make the matrix look uniform.

### M10B implementation record — human-approved closeout

M10B derives a bounded Python intake execution budget of **180 seconds** from
the checked-in 30-second no-retry Gemini call, the Phase 7 Odoo validation
ceiling of seven sequential 20-second requests (140 seconds), and a 10-second
reserve for bounded parsing and database work. An outer application deadline
returns the existing safe unavailability result; n8n's later transport retries
are intentionally outside this active-execution budget. The durable lease is
**210 seconds**, giving a 30-second safety margin. Ownership decisions use
PostgreSQL `clock_timestamp()` after the order row lock; tests force expiry in
the database rather than sleeping for the production lease.

The one focused migration `0007_phase7_intake_ownership` adds nullable,
timezone-aware `orders.intake_claim_token` and
`orders.intake_claim_expires_at` columns plus a pair-consistency check. Existing
rows remain inactive (`NULL`, `NULL`); bare historical `PROCESSING` or
`EXTRACTED` rows still stand down rather than being guessed stale. A current
token and expiry form the fence: initial claims, human Retry claims, and stale
recovery rotate it; recovery emits only bounded
`ORDER_PROCESSING_RECOVERED`/`ORDER_EXTRACTION_RECOVERED` audit evidence. The
fence is checked in extraction completion, validation promotion/routing, and
failure/audit/notification persistence. It remains active across the
`EXTRACTED` intermediate state and is cleared with persisted `NEEDS_REVIEW`,
`READY_FOR_APPROVAL`, `FAILED_RETRYABLE`, or `FAILED_FINAL` outcomes.

The independent M10B review identified two remediation findings. **M10B-01
(HIGH)** was that the existing two one-second n8n transport waits could end on
a live `202 PROCESSING`/`EXTRACTED` stand-down before stale recovery was
eligible. The API now exposes a bounded `retry_after_seconds` hint only for a
valid live in-progress history with current ownership. Both Phase 7 intake
workflows route that backend-provided value through one delayed Wait and one
final same-identity multipart redelivery. The workflow does not contain the
210-second lease value, ownership state, or recovery classification. The final
recovery response routes to the existing backend-state path and cannot loop.
The maximum wait from a live stand-down response is the remaining lease,
rounded up and capped at 210 seconds; the existing two one-second transport
waits remain separate. Therefore an abandoned claim receives another recovery
attempt within at most 210 seconds after the live stand-down response, or
within the two bounded transport waits before that response if the initial
caller returned `503`.
The recovery-versus-delay branch makes that choice from one PostgreSQL
`clock_timestamp()` read after the locked order row is acquired, so the
lease-boundary decision and the returned hint cannot disagree.

**M10B-02 (MEDIUM)** was that stale recovery ignored the existing fail-closed
audit-history decision. Recovery and the backend retry hint now require the
single existing audit-history interpretation to report a valid recoverable
`PROCESSING` or `EXTRACTED` phase. Unknown, malformed, misordered, approval,
rejection, or otherwise impossible histories remain `STAND_DOWN`, do not
rotate ownership, do not emit recovery audit evidence, and do not enter the
pipeline. No lease, execution-budget, migration, M9B, or human Retry semantics
changed during this remediation.

| Failure boundary | Durable outcome | Sole retry owner |
| --- | --- | --- |
| malformed/unsupported document or invalid AI response | `FAILED_FINAL` | no automatic retry; human supplies a valid input |
| AI timeout/unavailable or trusted-data transient failure | `FAILED_RETRYABLE` | human Retry, then one authorized intake redelivery |
| database unavailable before claim | no claimed state; bounded `503` | same idempotent caller/n8n transport |
| database unavailable after claim | nonterminal state with fence; bounded `503` | stale Phase 7 recovery after lease expiry |
| stale Phase 7 worker | no authoritative write; bounded unavailable result | newer fenced intake owner |
| Phase 7 validation-facts change | `FAILED_RETRYABLE` | human Retry |
| M9B provider/configuration/pending/reconciliation failure | existing `order_syncs` state/code | M9B coordinator or human Retry after exhaustion, per existing code |
| lost M9B receipt persistence | existing in-flight/checkpoint state | M9B first-missing-step recovery |

No M9B production behavior changed: its single sync row, lease/fence, retry
generation, receipts, stable provider identities, and first-missing-step
recovery remain the authoritative Phase 9 lifecycle. The Phase 7 n8n workflow
change is transport-only: it waits on a backend-provided bounded hint and
resends the same idempotent source; it does not acquire ownership or business
retry state.

The M10B review history is preserved: the initial candidate was
`053278d348aad8c346d82676c1f4c5d54aef3e53`; independent review found
M10B-01 HIGH (bounded retries could terminate on a live `202
PROCESSING`/`EXTRACTED` lease) and M10B-02 MEDIUM (expired recovery could bypass
invalid audit-history fail-closed semantics); remediation was committed at
`765c5030659d6c4d0aebe325b7d35d577766dbfd`; targeted independent re-review
returned `PASS`; and human approval recorded M10B `COMPLETE` at that technical
SHA.

The final bounded contract remains: Python owns a 180-second intake execution
budget; the Phase 7 durable `orders` token/expiry fence is 210 seconds, with a
30-second safety margin; ownership decisions use PostgreSQL
`clock_timestamp()` after row locking; only valid recoverable in-progress
audit history may recover; live active-owner stand-down may carry a bounded
`retry_after_seconds`; and n8n performs at most one backend-directed delayed
same-identity resend for transport only. Stale workers cannot persist
authoritative results, and human Retry remains authoritative for durable
`FAILED_RETRYABLE` outcomes. This does not claim exactly-once physical
execution. If PostgreSQL remains unavailable, a future recovery attempt can
still fail visibly; the contract is bounded recovery, not infinite transport
retry, and this is an operational limitation rather than an unresolved M10B
defect.

## 7. Observability design

M10D should add the smallest useful layer:

1. A standard-library structured event logger emits one JSON object per
   request boundary, state-transition/failure boundary, and provider call.
   Allowlisted fields are `timestamp`, `level`, `event`, `request_id`,
   `workflow_execution_id` when safely supplied, `order_id` when known,
   `provider`, `operation`, `failure_code`, `state`, `attempt`, and bounded
   `duration_ms`. Values have fixed length caps.
2. A request context generates a UUID request ID when the caller does not send
   one. A valid bounded request ID may be echoed as a correlation value but is
   never an authentication or idempotency key. The API returns it in
   `X-Request-ID`. n8n workflow execution IDs are correlation-only and are
   accepted only as bounded metadata; they do not change state behavior.
3. Logs never include bearer tokens, API keys, authorization headers, raw
   documents, prompt text, provider bodies, full exception strings, email
   contents, Slack payloads, or database URLs. Error codes are an allowlisted
   enum/string vocabulary. A redaction test uses sentinel secrets and source
   content.
4. Provider timing is recorded around the existing adapter call. Gemini usage
   fields are recorded only if the SDK response exposes trustworthy input,
   output, and total counts. Missing values are explicitly absent/unavailable;
   no token estimate is made.
5. A small standard-library, process-local registry records counters and
   bounded duration histograms for HTTP outcomes, intake state outcomes,
   provider calls, notification attempts, order-sync steps, retries, and
   failure codes. It may use only fixed/bounded dimensions: route class/name,
   HTTP status/status class, provider, operation, state, retry outcome, and
   bounded failure code. Request ID, workflow execution ID, order ID, customer,
   PO number, filename, actor, email, and raw exception text are never metric
   labels; they belong only in bounded structured logs. Reset on application
   restart is acceptable and must be documented. No collector, Prometheus,
   hosted APM, Grafana, ELK, or OpenTelemetry stack is justified.
6. `/health` remains unauthenticated liveness and `/ready` remains
   unauthenticated, database-only readiness. A separate non-blocking
   integration-health/diagnostic view may report only passive state: configured,
   unconfigured, healthy or unavailable from the last observed real operation,
   not checked/no observation yet, and a bounded last failure code/time where
   justified. It must not actively call Gemini, Gmail, Slack, Odoo, HubSpot, or
   n8n. Metrics and diagnostics require existing human development
   `require_view_access`; they are not public status endpoints. Their failure
   never changes `/ready`.

The observability contract is diagnostic, not a Phase 11 evaluation program.
It may expose the trustworthy data Phase 11 later consumes, but M10D must not
produce extraction F1, routing benchmarks, p50/p95 evaluation reports, token
cost reports, or model/prompt optimization.

## 8. Security hardening design

M10C owns a narrow posture tied to the gaps above:

- Add an ASGI receive/body budget before multipart/JSON parsing. The ratified
  absolute application request ceiling is 12 MiB; orchestration multipart is
  11 MiB; ordinary JSON is 512 KiB; notification transport/result commands are
  16 KiB. Retain the existing exact 10 MiB accepted-document limit so a
  document at that boundary remains transportable. Reject oversized requests
  with a non-echoing `413` before an order is created.
- Apply the ratified transport caps for order/review strings, descriptions,
  MIME/name and storage references, source-document and line/metadata counts,
  evidence and rejection text, headers, and Decimal representation. Reuse
  existing document parser limits rather than adding a second parser policy.
  Tests must exercise exact boundary and boundary+1 values; inputs are rejected,
  never silently truncated, and an already-stricter contract is never loosened.
- Keep constant-time comparison and separate credentials for n8n versus human
  development operators. `GET /v1/orders`, `GET /v1/orders/{order_id}`, and
  `GET /v1/orders/{order_id}/audit` require `get_operator_context` plus
  `require_view_access`; any configured REVIEWER, APPROVER, or
  ELEVATED_APPROVER may view. `POST /v1/orders` requires the existing
  orchestration/service bearer mechanism. A human token cannot create through
  that route, and an orchestration token cannot gain human view/review/approval
  capability. `/health` and `/ready` remain unauthenticated. These fixed
  credentials are local/demo development authentication only, not production
  identity, OAuth, SSO, sessions, or internet-facing IAM; no browser actor/role
  claims are accepted.
- Normalize core validation and unexpected transport errors to safe bounded
  codes/messages. Never return Pydantic input values, tracebacks, SQL, provider
  response bodies, or secrets. Preserve useful HTTP status semantics.
- Keep `.env`, `SecretStr`, sanitized workflow exports, provider adapter
  boundaries, and pinned full-history Gitleaks. Add a repeatable dependency
  policy: production-only frontend audit plus the verified Python command
  below. `pip-audit==2.10.1` is a CI/developer tool only, not an application
  dependency:

  ```sh
  set -o pipefail
  uv export --frozen --no-dev --no-emit-project --format requirements.txt \
    | uvx --from 'pip-audit==2.10.1' pip-audit \
        --requirement /dev/stdin --no-deps --disable-pip --strict
  ```

  `uv export --frozen` derives the frozen production-only, hashed dependency
  set from the committed `uv.lock`, excludes development groups, and refuses
  to update the lockfile. The pinned audit tool reads that exported set from
  standard input without installing into the application runtime image.
  `--no-deps` and `--disable-pip` avoid a second dependency-resolution path;
  the exported requirements are fully pinned/hashed, and `--strict` makes
  incomplete collection fail. `set -o pipefail` also propagates an export
  failure. This verified workflow is preferred over claiming that
  `pip-audit --locked` directly audits `uv.lock`. Any known vulnerability in a
  Python production dependency fails by default. An exception must visibly
  record the vulnerability ID, technical rationale, affected/not-affected
  analysis, and human approval; it must not be hidden with `|| true`. Retain
  `npm audit --omit=dev --audit-level=high` and the existing transitive,
  development-only `brace-expansion@5.0.9` classification unless fresh evidence
  changes it.

### Ratified M10C transport/resource cap table

These are implementation contracts, not business-rule changes. A current
stricter field or parser limit remains authoritative.

| Boundary or field | Maximum |
| --- | ---: |
| Absolute HTTP request body | 12 MiB |
| Orchestration multipart request | 11 MiB |
| Accepted document bytes inside that request | 10 MiB, exact Phase 3 limit |
| Ordinary JSON business/review/core command body | 512 KiB |
| Notification result command body: `POST /v1/integrations/notifications/{notification_id}/outcome` | 16 KiB; bodyless claim and unrelated routes are excluded |
| Order/review lines | 200 |
| Source documents on structured core order creation | 8 |
| Metadata pairs per source document | 32 |
| List/query result limit | 100 |
| Ordinary business identifier, including customer reference, PO number, SKU | 256 characters |
| Filename/name | 255 characters |
| MIME type | 128 characters |
| Message ID | 256 characters |
| Description | 2,048 characters |
| Storage/source reference | 2,048 characters |
| Metadata key | 128 characters |
| Metadata value | 512 characters |
| Evidence quote/review text | 4,096 characters |
| Rejection reason | 500 characters |
| Client-supplied quantity/price Decimal significant digits | 28 |
| Client-supplied quantity/price Decimal fractional digits | 8 |

Exact boundary values pass and boundary+1 values fail safely. The transport
Decimal caps preserve positive quantity and non-negative price semantics; they
do not change trusted-price tolerance or other monetary business rules. The
source-document count applies to every structured core create route, and the
same string/count/Decimal policy must cover alternate review and structured
transport schemas rather than allowing a bypass. The ordinary JSON budget
applies to `POST /v1/orders` and review draft/command bodies unless the
notification result budget is narrower. The Decimal cap covers every
client-supplied quantity/price field in those core and review schemas,
including `quantity`, `submitted_price`, and any client-visible catalogue-price
transport field; it does not make a client-supplied catalogue value trusted.

- Verify SQLAlchemy parameterization and fixed raw SQL fragments. Do not add
  an ORM abstraction or query builder.
- Preserve the prompt/data authority separation. Security tests should prove
  that source instructions cannot select validation, approval, or provider
  execution.

Generic CORS, security headers, host policy, and reverse-proxy controls are
not automatically required by the current localhost-bound Compose deployment.
M10C may add only a narrowly justified control if the actual frontend/API
deployment path demonstrates a need; it must not imply public-internet
hardening that the repository does not contain.

### M10C independent-review remediation record

The initial M10C candidate was `b666673162b26cfc63fe9c9e3ef609e47b16f23d`.
Independent review identified two MEDIUM findings:

- M10C-01: known JSON command routes selected the 512 KiB budget primarily
  from `Content-Type`, allowing missing or misleading media types to fall
  through to the 12 MiB ceiling.
- M10C-02: the request-constrained `MetadataPair` model was reused by
  `SourceDocumentResponse`, so historical persisted metadata outside new
  request limits could fail response serialization.

The remediation adds deterministic RED-to-GREEN ASGI tests for `/v1/orders`
and review draft/reject commands with correct, missing, and misleading media
types. Known body-bearing JSON business/review routes now resolve the 512 KiB
budget by method/path before the generic Content-Type fallback. The
orchestration, notification, and global budgets remain unchanged.

The remediation also separates `MetadataPairCreate` from
`MetadataPairResponse`. New client input retains the 128/512 key/value limits
and 32-pair limit, while persisted response metadata is returned unchanged.
An integration regression seeds over-limit metadata through the application
path and verifies authenticated order detail reads succeed without truncation
or mutation. The targeted independent re-review passed, and human approval
records M10C `COMPLETE` against technical SHA
`7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`. M10D–M10F remain `NOT STARTED`.

## 8A. M10C implementation record — human-approved closeout

M10C is `COMPLETE` at human-approved technical SHA
`7d7ec4a2e2135b2280e16bdad8ac6c6315765a28`, following implementation commits
`827782d` and `477e416` and the remediation commit above. It adds a pure-ASGI receive wrapper that enforces the 12 MiB
absolute ceiling, 11 MiB orchestration multipart budget, 512 KiB ordinary JSON
budget, and 16 KiB notification-outcome budget before normal body parsing. It
counts actual received bytes when `Content-Length` is absent or misleading and
returns a bounded non-echoing `413`; the existing 10 MiB document parser limit
remains authoritative.

Transport schemas now enforce the approved collection, string, header, and
Decimal budgets across structured order creation and review edits. Core order
reads resolve server-side human development operators through
`get_operator_context`/`require_view_access`; structured creation requires only
the orchestration bearer. `/health` and database-only `/ready` remain public.
Fixed bearer values remain a local/demo development authentication boundary,
not production identity, OAuth, SSO, sessions, or internet-facing IAM.

Core domain and global request-validation errors now use bounded stable
messages, while existing orchestration/review/notification error contracts are
preserved. Secret-sentinel regressions verify that settings, auth, provider
configuration, and request-validation responses do not echo credentials,
payloads, SQL, provider bodies, or tracebacks.

The repository exposes `make dependency-audit`, `make frontend-audit`, and
`make security-audit`. The Python gate derives frozen production-only
requirements from `uv.lock` and runs pinned `pip-audit==2.10.1`; the frontend
gate runs `npm audit --omit=dev --audit-level=high`. Both pass, and the known
`brace-expansion@5.0.9` development-only advisory remains non-blocking. SQL
review found no user-controlled SQL syntax interpolation; existing prompt/data
authority tests are sufficient, so no ORM rewrite, prompt filter, or second AI
safety component was added. No CORS/host/security-header change is required
under the localhost/demo deployment contract.

M10D–M10F remain `NOT STARTED`; this record adds no observability, Phase 11
evaluation, or Phase 12 release behavior.

The final M10C boundary is a pure-ASGI receive counter before normal body
parsing: orchestration multipart is 11 MiB, the accepted document remains the
existing 10 MiB limit, known JSON business/review bodies are 512 KiB by route
before Content-Type, notification outcomes are 16 KiB, and the generic
non-JSON fallback is 12 MiB. Exact string/count/Decimal transport limits remain
request-only and separate from unconstrained persisted response serialization.
Core reads require human development view access; `POST /v1/orders` requires
the orchestration bearer; `/health` and database-only `/ready` remain public.
Errors are bounded and non-echoing. Python production dependencies use pinned
`pip-audit==2.10.1`, frontend production auditing remains enabled, and pinned
full-history Gitleaks remains required. SQL review found no user-controlled
SQL interpolation, and deterministic software remains authoritative over AI
output. No CORS, WAF, OAuth, or public-IAM architecture was introduced; the
development bearer boundary remains local/demo-only. GET/HEAD/OPTIONS routes
do not consume request bodies through application parsing.

## 8B. M10D implementation record — human-approved closeout

M10D implements a standard-library-only observability boundary. A pure-ASGI
correlation middleware validates or generates `X-Request-ID` values, accepts a
bounded optional `X-Workflow-Execution-ID`, returns the effective request ID
on responses, and runs outside the existing streaming body limiter so `413`
responses are correlated without a second body buffer. Correlation values are
diagnostic only and do not affect idempotency, ownership, review authorization,
or provider identities.

Structured events are one JSON object per line with an explicit allowlist for
event, request/workflow correlation, order UUID, provider, operation, state,
bounded failure code, attempt, duration, HTTP route/status, and trustworthy
Gemini usage counts. Payloads, prompts, documents, credentials, headers,
provider responses, database URLs, customer/PO/filename values, and raw
exception text are not accepted event fields. Durations use a monotonic clock.

The process-local registry exposes fixed counters and small duration buckets for
HTTP, intake, provider, notification, and order-sync outcomes. Labels are
bounded route/status/provider/operation/state/retry/channel/step/failure
dimensions only; request IDs, workflow IDs, order IDs, customer data, filenames,
actors, email, and exception text are never labels. Metrics reset on process
restart by design. `GET /v1/operations/metrics` and
`GET /v1/operations/integrations` require existing human view access and do not
probe providers.

Integration health is passive last-observed state: Gemini, Odoo, HubSpot,
Gmail, Slack, and n8n distinguish configuration from `NOT_OBSERVED`, `HEALTHY`,
or `UNAVAILABLE` outcomes. Gemini/Odoo/HubSpot state is updated only by the
existing logical provider seams; the trusted-data Odoo lookup is one
`ODOO_LOOKUP` observation and Phase 9 Odoo/HubSpot steps reuse provider metrics
without emitting a duplicate provider event. Only explicit provider-operational
failure codes (`PROVIDER_ERROR`, `PROVIDER_TIMEOUT`,
`PROVIDER_UNAVAILABLE`, `PROVIDER_RATE_LIMIT`, and
`PROVIDER_INVALID_RESPONSE`) make a failed provider operation an unavailable
observation; configuration, pending/rejected, business/data, reconciliation,
and worker-state outcomes leave the prior health observation unchanged.
Gmail/Slack state is sourced only from authenticated notification outcomes;
n8n is marked healthy only after a successful authenticated workflow-bound
response and is never marked unavailable from an inbound failure response.
Notification events include only the bounded channel/provider and order UUID.
`/ready` remains strictly database-only and does not depend on any of these
observations.

The installed `google-genai` SDK is 2.24.0 and its Interaction response exposes
`usage.total_input_tokens`, `usage.total_output_tokens`, and `usage.total_tokens`.
Those non-negative integers are propagated only as optional provider-neutral
telemetry; no token estimate is made. The four committed n8n workflows use the
documented `={{ $execution.id }}` expression for the diagnostic header on every
OpsFlow API request, preserving one execution correlation value across retries
and the M10B delayed resend. n8n still owns transport only.

No CORS, host-policy, public-IAM, collector, tracing stack, database telemetry
table, or new runtime dependency was introduced. M10E adversarial drills,
Phase 11 evaluation, and Phase 12 release work remain outside this record.

The initial M10D candidate was `424ba74b91b3fae13721e7eb93f20a3dad9ad3f5`.
Independent review found three MEDIUM issues: M10D-01 (forged workflow
metadata and business failures could poison passive health), M10D-02 (trusted
data Odoo calls and Phase 9 provider metrics were incomplete), and M10D-03
(notification events lacked provider and order correlation). The focused
remediation adds the authenticated-success-only n8n observation rule, the
bounded provider-health classification above, one logical trusted-data Odoo
instrumentation seam, provider metric reuse for Phase 9 steps, and safe
notification provider/order fields. The targeted independent re-review returned
`PASS` with no unresolved High or Medium findings. Human approval records M10D
`COMPLETE` against technical SHA
`cf0b331864ca2cc5246aa32c7ce12827b79284d0`. At M10D closeout, M10E–M10F
were `NOT STARTED`; M10E is now `IN PROGRESS` and M10F remains `NOT STARTED`.
Phase 10 remains `IN PROGRESS`; Phase 11–12 remain `NOT STARTED`.

### M10E implementation record — candidate closeout

The provider-free M10E matrix contains 12 executable scenario tests and one
retry-owner matrix assertion, covering 18 explicit rows plus composed Phase
2–9 claim, receipt, notification, parser, provider, workflow, and
observability regressions. The drills use isolated PostgreSQL and existing
fakes/MockTransport seams; normal test execution makes no live calls to
Gemini, Odoo, HubSpot, Gmail, Slack, or n8n.

The matrix found one concrete Phase 7 boundary defect: a refused PostgreSQL
connection before initial order creation escaped as `ConnectionRefusedError`
instead of the existing bounded `503 ORCHESTRATION_UNAVAILABLE` result. The
minimal repair in `38ad89f` classifies raw socket `OSError` alongside existing
SQLAlchemy persistence failures at the already-defined orchestration writes.
The RED regression remains in
`tests/integration/test_phase10_failure_drills.py`, and the matrix plus full
prior-phase integration regressions are green. No migration, dependency,
workflow, or generic fault framework was added; no M9B behavior changed.

The candidate remains bounded: notification duplicates after a lost external
send remain possible under the existing at-least-once contract, and a future
recovery attempt can still fail visibly while PostgreSQL is unavailable. This
does not claim exactly-once physical execution or infinite transport retry.
M10E is `IMPLEMENTED — PENDING HUMAN REVIEW`; M10F remains `NOT STARTED`.

### M10E independent-review remediation record

The initial M10E candidate was `2397244fc594c8a6986bd84b86fd998bf70e3dd9`.
Independent review found three MEDIUM proof/coverage findings:

- M10E-01: the focused matrix did not directly index the complete approved
  corrupt-document, Gemini-adapter, Gmail/Slack, Odoo, HubSpot, and repeated
  n8n-equivalent invocation scenarios;
- M10E-02: the retry-owner assertion accepted non-empty prose and an ambiguous
  invalid-response owner instead of one deterministic owner per row;
- M10E-03: representative failure-path sentinel checks did not inspect both
  structured events and process-local metric snapshots for authorization,
  document, provider, and notification payload markers.

The remediation expands
`tests/integration/test_phase10_failure_drills.py` to 21 executable
provider-free scenario tests plus one typed retry-owner matrix assertion. The
matrix now contains 34 explicit rows with exact durable-state, retry-owner,
and external-effect expectations. It directly covers corrupt PDF/XLSX,
Gemini SDK timeout/unavailable/malformed/schema-invalid responses, both Gmail
and Slack lost-outcome/claim-recovery paths, Odoo and HubSpot adapter fault
seams, repeated intake/notification/order-sync API invocation, and structured
event/metric sentinel exclusion. The test-only retry-owner vocabulary is
`CALLER_TRANSPORT`, `PHASE7_STALE_RECOVERY`, `HUMAN_RETRY`,
`NOTIFICATION_LIFECYCLE`, `M9B_COORDINATOR`,
`M9B_STABLE_IDENTITY_RECOVERY`, and `NONE`; no ambiguous owner is permitted.

The existing production repair in `38ad89f9defc3d7f846bbfa20e7f9f34c0c730dc`
is unchanged. A focused Odoo business-data `OSError` guard confirms that the
widened Phase 7 persistence exception boundary does not reclassify typed Odoo
provider failures as generic `ORCHESTRATION_UNAVAILABLE`. No additional
production defect was found, so no production file, migration, workflow,
dependency, or CI change was made.

The remediation clean-clone procedure is recorded for M10F reuse: clone the
local repository with `git clone --no-local --branch
phase/10-reliability-security-hardening <local-repository> <temporary-clone>`;
check out the exact remediation SHA; create only a synthetic ignored `.env`
with non-secret local settings; start a newly named disposable PostgreSQL
container/database outside the developer database; run `uv sync --frozen` and
`npm ci --prefix web`; validate `docker compose config --quiet`; run isolated
`uv run alembic upgrade head` and `uv run alembic current`; run
`uv run pytest tests/integration/test_phase10_failure_drills.py -q --no-cov`;
run `uv run pytest tests/unit/workflows/test_n8n_contract.py -q --no-cov`, the
standard-library relative-Markdown checker from the M10E plan,
`make security-audit`, and pinned Gitleaks changed-content/full-history checks;
then stop/remove the disposable database and delete the temporary clone. No
`.env`, database, workspace residue, generated files, caches, or provider
credentials are copied from the original checkout.

The remediation is recorded as the continuation of the original review
history. M10E remains `IMPLEMENTED — PENDING HUMAN REVIEW`; M10F remains
`NOT STARTED`; Phase 10 remains `IN PROGRESS`.

The first pushed remediation run also exposed two Gitleaks false positives in
the immutable test commit `be8322e`: synthetic idempotency identities assigned
to variables named `key`. The current test source renames those variables, and
`8ad3f47` adds only the two exact historical commit/file/rule/line fingerprints
to `.gitleaksignore`. Current-file and full-history scans are clean; no broad
rule, path, or secret-pattern suppression was added.

### M10E final focused-coverage remediation record

Targeted review identified one remaining MEDIUM evidence gap in remediation
`13e5dbe69962b1cd8b897dccfdf77fa8f59bcc28`:

- M10E-04 — the declared Odoo transport-timeout case and the Gmail/Slack
  rejected and timeout outcome cases were not all backed by executable focused
  drills.

The final test-only remediation adds a real `httpx.ReadTimeout` fault through
`OdooERPAdapter.get_validation_data()`. The adapter still produces the bounded
`PROVIDER_UNAVAILABLE` code, the timeout sentinel is absent from the bounded
failure, `MockTransport` makes the case provider-free, and the matrix retains
`M9B_COORDINATOR` as the retry owner. Existing Odoo unavailable, malformed
response, configuration, and stable-identity lost-response cases remain.

The notification matrix now invokes the persisted claim/outcome boundary for
both `GMAIL` and `SLACK` with both `DELIVERY_REJECTED` and `TIMEOUT`. Each case
proves a current claim token is required, attempt one returns to bounded
`PENDING`, the exact failure code is retained, claim fields are cleared, and
the order remains `NEEDS_REVIEW`. Existing rate-limit, lost-outcome, stale
claim, lease recovery, attempt-three finalization, and no-fourth-attempt cases
remain. These additions do not add matrix rows: all 34 declared
`FAILURE_DRILLS` rows were reviewed and now have executable focused coverage or
an explicitly invoked existing production-boundary helper.

No production file changed, and the accepted PostgreSQL repair
`38ad89f9defc3d7f846bbfa20e7f9f34c0c730dc` remains unchanged. The original
candidate `2397244fc594c8a6986bd84b86fd998bf70e3dd9`, first remediation
`13e5dbe69962b1cd8b897dccfdf77fa8f59bcc28`, M10E-01/02/03 findings and
dispositions, and the earlier Phase 7 connection defect/fix remain preserved.
M10E remains `IMPLEMENTED — PENDING HUMAN REVIEW`; M10F remains `NOT STARTED`;
Phase 10 remains `IN PROGRESS`.

## 9. Phase 10 decomposition and gates

| Milestone | Scope | Observable acceptance gate |
| --- | --- | --- |
| M10A — Hardening Contract, Threat Model & Implementation Plan | This document, the executable plan, actual Phase 0–9 inventory, status alignment, and no production behavior. | Every roadmap concern has a matrix row; threat boundaries match the repository; every failure has one retry owner; Phase 11/12 are separated; docs/link/secret/scope checks pass. |
| M10B — Cross-Boundary Idempotency, Failure Semantics & Recovery Hardening | Repair only proven intake/database recovery and retry-owner/classification gaps; preserve Phase 7/8/9 state machines and stable identities. | Concurrency/replay tests show no stranded post-claim intake; failure-code table has one owner; DB/provider lost-response and partial-effect tests show no duplicate unsafe execution or silent state. |
| M10C — Security Boundaries, Input Safety & Secret Hygiene | HTTP/resource limits, bounded schemas/errors, explicit development-auth boundary, dependency policy, SQL verification, and security regressions. | Oversized/malformed hostile requests fail before resource exhaustion; unauthorized core routes fail closed; sentinel secrets/payloads never appear in errors/logs/history; CI audits are reproducible and the known advisory remains correctly classified. |
| M10D — Structured Observability, Correlation & Operational Health | Allowlisted structured logs, request/workflow/order/provider correlation, latency, conditional LLM usage, process-local metrics, and separate integration health. | Synthetic requests/provider faults produce bounded correlated events and metrics; `/ready` remains DB-only; no secret or payload leakage; provider health failure does not make readiness fail. |
| M10E — Adversarial Resilience & Whole-System Failure Drills | Fault-injection matrix across duplicate/replay, malformed/huge input, prompt injection, AI faults, DB interruption, notifications, Odoo/HubSpot faults, partial sync, restore/recovery, and clean clone. | Provider-free default tests cover every matrix row; no unexpected external writes/calls in CI; explicit opt-in sandbox checks pass where a real boundary is necessary; recovery is observable. |
| M10F — Independent Phase 10 Audit & Closeout | Fresh whole-phase review, clean clone, history secret scan, unresolved finding disposition, and human approval. | No unresolved Critical/High/Medium finding; all M10B–M10E gates pass; Phase 11/12 remain untouched; human approves Phase 10 closeout. |

## 10. Explicit boundaries

Phase 10 may expose telemetry needed later, but it does not implement:

- Phase 11 extraction accuracy/F1/exact-match studies, routing benchmarks,
  p50/p95 evaluation reports, cost-per-order reports, benchmark optimization,
  or model/prompt optimization.
- Phase 12 marketing/case-study rewriting, screenshot or demo-video
  production, public-release polish, licensing/publication work, or proposal
  assets.
- OAuth/OIDC/SSO, a user-account system, Vault, WAF, service mesh,
  Kubernetes, SIEM, distributed tracing, hosted monitoring, multi-tenancy,
  billing, or unsupported uptime/SLA/exactly-once claims.

M10A therefore concludes with a design and implementation plan, not changed
runtime behavior.
