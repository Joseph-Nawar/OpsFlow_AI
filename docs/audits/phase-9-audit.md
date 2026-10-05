# Phase 9 Independent Audit and Closeout Assessment

> The assessment-status fields, findings, matrices, and FAIL verdict in the original assessment below are the historical M9F result at the immutable audit baseline. The final remediation and independent targeted re-review disposition is appended at the end of this report and supersedes that initial status without erasing it.

- **Audit date:** 2026-10-04
- **Assessment status:** Partial
- **Phase status:** IN PROGRESS
- **M9F status:** IN PROGRESS
- **Verdict:** FAIL — Phase 9 requires remediation

## Audit identity and scope

The implementation candidate was audited at full SHA
b93001e3bcfb4ae72ebeb4a8fab40ed926b8e27 on branch
phase/9-erp-crm-integrations. This is the required frozen candidate. The
literal review clone had the same SHA and full Git history. The original
worktree was clean at audit start. The human-approved M9E provenance SHA,
8b1f6941f2070017724346c4acb93d1d16cfa492, is an ancestor of the candidate.
The later audit documentation commit is separate from this implementation
candidate.

M9F was treated as an independent whole-Phase-9 assessment of the approved
design, source, migrations, tests, n8n export, setup guides, live sandbox
behavior, repository hygiene, cost, and release evidence. No application
source, workflow, migration, dependency, fixture, or test was changed. Two
findings remain unresolved: an application role-boundary defect and a
clean-clone documentation defect. No remediation was authorized or made.
The canonical status remains IN PROGRESS and this report is not linked from
the roadmap as a successful closeout.

The audited architecture keeps Python responsible for policy, state,
validation, provider contracts, and durable receipts. n8n schedules one
execute-next request and routes its bounded result. The audit found no second
sync lifecycle or provider-write implementation in n8n.

## Findings

### M9F-01 — HIGH — Orchestration token may authenticate as an approver

**Requirement affected:** review and execution role separation; the
orchestration bearer must not review, correct, revalidate, or approve.

**Evidence:** [settings.py](../../src/opsflow/settings.py) validates
duplicates among review operator tokens but does not reject an
orchestration_token that equals a configured review token. In
[review/auth.py](../../src/opsflow/review/auth.py),
resolve_operator_token resolves a presented bearer against the review
operator list and require_approval accepts the APPROVER role. A one-off
synthetic configuration probe confirmed that Settings accepts a shared
value and that the orchestration bearer then resolves to the APPROVER and
satisfies the approval check. No secret value was retained in this report.

**Impact:** if the two settings overlap, the n8n credential can call the
approval API as the configured approver. An approved order can then create
sync intent and reach external provider writes without an independent human
approval. The normal clean-clone run used three distinct tokens and did not
exercise this misconfiguration.

**Recommended bounded remediation:** reject any orchestration-token match
against every configured review token during settings validation, and add a
regression test for reviewer and approver collisions. This is an unresolved
high-severity release blocker. No code or test change was made during M9F.

### M9F-02 — MEDIUM — Odoo clean-clone fixture staging omits a required permission step

**Requirement affected:** clean-clone reconstruction from committed
instructions without undocumented setup state.

**Evidence:** [odoo-m9c-sandbox.md](../development/odoo-m9c-sandbox.md)
copies a synthetic fixture from the host into the Odoo container and then
reads it from an Odoo shell. The clean-clone fixture was mode 0600 on the
host; Compose copied it root-owned into the container, where the Odoo process
could not read it. The documented helper failed with a permission error.
The run proceeded only after an additional, undocumented container
permission change. The fixture contains only synthetic identifiers, not a
credential.

**Impact:** a literal first-time clean-clone run stops during documented
Odoo setup unless the operator knows an extra permission or ownership step.
The eventual E2E success therefore does not establish reproducibility from
the committed instructions as written.

**Recommended bounded remediation:** update the sandbox procedure to stage
the synthetic fixture with readable ownership or permissions, then verify
the exact documented commands from a fresh clone. Keep API-key and result
files private. This medium finding is unresolved. No guide change was made
during M9F.

## Initial M9F Requirement-to-Evidence Traceability (historical at the immutable baseline)

Status is about the Phase 9 requirement, not whether a prior milestone is
labelled complete. E1–E9 are detailed in the evidence record below.

| # | Required audit dimension | Status | Direct evidence |
| --- | --- | --- | --- |
| 1 | M9A–M9E traceability, ownership, implementation, automated/live proof, limits | PASS | E1, E2, E4–E7; approved [Phase 9 design](../superpowers/specs/2026-09-29-phase-9-erp-crm-integrations-design.md) |
| 2 | Approval intent, atomicity, eligibility, and no writes before approval | PASS | E2, E3, E6; pre-approval DB and provider counts were zero |
| 3 | One durable sync lifecycle and no competing queues or receipts | PASS | E1; M9B repository/coordinator, adapter composition, workflow export |
| 4 | Claims, fencing, lease recovery, provider I/O outside DB transactions | PASS | E1, E2; PostgreSQL-backed concurrency and stale-claim suites |
| 5 | Failure taxonomy, retry limits, generation ownership, human Retry, clean yield | PASS | E1, E2, E7; unit/integration evidence and live bounded outage |
| 6 | Aggregate deadline, receipt reserve, provider timeout, lease, and schedule | PASS | E1, E2, E6; implementation configuration and observed five-minute n8n cadence |
| 7 | Ordered receipts, resume from first missing receipt, stale claim rejection | PASS | E2, E5, E6; M9D live partial recovery and durable E2E receipts |
| 8 | Odoo UUID idempotency, races, lost response, confirmation, ACL, trusted price/stock | PASS | E4, E6, E7; five JSON-2 live tests and one independently read confirmed E2E order |
| 9 | Exclusive HubSpot v2 customer identity | PASS | E1, E5, E6; code review and independent Company search |
| 10 | Deal update preserves human-progressed stage | PASS | E1, E5; M9D live race/stage suite |
| 11 | Lost-response recovery for Odoo, Company, Deal, and association | PASS | E2, E4–E6; synthetic live replay and adapter tests |
| 12 | Strict provider response, item-error, trace, cardinality, and association validation | PASS | E1, E2, E5; provider contract suites and live response checks |
| 13 | HubSpot portal/account guard before writes | PASS | E1, E2, E5; portal identity and configuration guard checks |
| 14 | Provider credentials and orchestration bearer remain in their intended stores | PASS | E6, E9; no secret appeared in tracked files, workflow export, or n8n environment |
| 15 | Thin n8n with one scheduled call, bounded branches, and success-data privacy | PASS | E1, E2, E6; static export review and live 200/401/503/transport branches |
| 16 | Literal clean-clone reconstruction at the immutable candidate SHA | FAIL | E8; fixture copy requires an undocumented permission change (M9F-02) |
| 17 | Approved n8n → OpsFlow → Odoo → HubSpot success path | PASS | E6; one approved synthetic order completed and all receipts were read back |
| 18 | Replay preserves one Odoo order, Company, Deal, association, and durable state | PASS | E5, E6; stable-identity searches and replay returned no additional records |
| 19 | Insufficient-stock failure has no external order/deal and no automatic retry | PASS | E2, E7; live outcome was INVENTORY_INSUFFICIENT with no external receipts |
| 20 | Transient provider outage and later due-time recovery without duplication | PASS | E7; one failed Odoo lookup, then scheduled recovery and one record at each provider |
| 21 | REVIEWER, APPROVER, and orchestration role separation | FAIL | E1, E3, E6; distinct-token path works, but overlap is accepted (M9F-01) |
| 22 | Missing/partial/malformed configuration, wrong portal, invalid credential and preclaim behavior | PASS | E2, E6; missing-provider 503, unauthorized 401, and transport branches |
| 23 | Minimal authenticated execute-next API with no ID/step override | PASS | E1, E2; route/schema and API contract tests |
| 24 | Durable approval, claim, failure, receipt, completion, explicit Retry, bounded diagnostics | PASS | E1, E2, E6, E7; PostgreSQL records and audit/read contracts |
| 25 | Migration/schema justification and fresh database upgrade | PASS | E1, E2, E9; isolated upgrade reached 0006_phase9_order_syncs |
| 26 | Provider-free default tests and explicit live opt-ins | PASS | E2, E4, E5; default suite skipped live writes and both guarded live suites passed |
| 27 | Full-history and changed-content secret hygiene | PASS | E9; pinned full-history scan, docs scan, Git ignore/tracked-file review |
| 28 | Unchanged dev-only brace-expansion advisory and production exposure | PASS | E9; dependency tree, audit excluding dev dependencies, and bundle inspection |
| 29 | $0 mandatory local infrastructure cost | PASS | E9; local Compose, Odoo Community, n8n CE, and HubSpot developer-test account |
| 30 | Durable documentation agrees on status, roles, cadence, retry, and cost | PASS | E1, E9; current canonical status remains IN PROGRESS |
| 31 | No unsupported speculative Phase 9 complexity | PASS | E1; static scope review found no second lifecycle or future-phase module |
| 32 | Focused/full verification, migration, workflow, Compose, docs, and security checks | PASS | E2, E4, E5, E9 |
| 33 | Complete matrix and eligibility for Phase 9 closeout | FAIL | This report; two unresolved findings and clean-clone failure prevent closeout |

## Initial Phase 9 Acceptance Matrix (historical at the immutable baseline)

| Criterion | Status | Evidence and limitation |
| --- | --- | --- |
| Approval gate | PASS | E2 and E3: repeated pre-approval execute-next calls made no sync row or provider record; reviewer and orchestration credentials could not approve in the valid distinct-token configuration; separate approver approval succeeded. |
| Exactly-once logical Odoo order | PASS | E4 and E6: bridge UUID/replay tests passed; independent JSON-2 read found one confirmed sale order for the approved E2E UUID. |
| Exactly-once logical HubSpot Company | PASS | E5 and E6: M9D synthetic live suite passed; independent search by opsflow_customer_reference_v2 returned one matching Company. |
| Exactly-once logical HubSpot Deal | PASS | E5 and E6: independent search by order UUID returned one matching Deal; schedule replay created no second Deal. |
| Intended association | PASS | E6: independent association read returned the expected Company with HubSpot default type 341 (and type 5); one association target matched the intended Company. |
| Durable partial recovery | PASS | E2 and E5: adapter replay resumed from the missing receipt and kept earlier Company/Deal work stable. |
| Fencing and concurrency | PASS | E2 and E4: PostgreSQL claim/stale-worker suites and forced Odoo UUID race tests passed. |
| Bounded retries | PASS | E2 and E7: the Odoo outage recorded attempt 1, a due time owned by M9B, and completed at the next eligible scheduled call without an n8n retry loop. |
| Provider failure mapping | PASS | E2, E4, E5, and E7: inventory insufficiency and provider unavailability mapped to bounded codes; M9D live contract suite passed. |
| Account guard | PASS | E2 and E5: portal identity and pre-write guard tests passed; live writes were confined to the approved developer-test portal. |
| Human Deal-stage preservation | PASS | E5: live M9D stage race and existing-Deal checks passed. |
| Thin n8n | PASS | E1 and E6: one five-minute trigger/call, bounded 200/401/503/transport branches, and success data retention disabled. |
| Clean-clone reproducibility | FAIL | E8: documented fixture copy failed for the Odoo service user until an undocumented permission change was applied. |
| Secret isolation | PASS | E9 and E6: scans were clean; provider keys remained in ignored API runtime settings and the orchestration bearer remained in n8n's local credential store. M9F-01 is the separate role-collision defect. |
| Live end-to-end success | PASS | E6: one approved synthetic order reached COMPLETED, with independent provider identity and receipt checks. |
| Idempotent replay | PASS | E5 and E6: replay left the logical Odoo order, Company, Deal, association, and completion receipts unchanged. |
| Unavailable inventory | PASS | E2 and E7: zero-stock order recorded INVENTORY_INSUFFICIENT; independent Odoo and HubSpot reads found no order, Deal, or association. It was intentionally not manually retried, so the external no-write condition remained measurable. Human Retry semantics are covered by provider-free review tests. |
| Outage recovery | PASS | E7: one scheduled attempt failed at Odoo lookup with PROVIDER_UNAVAILABLE; after restoration, the due scheduled run completed and independent provider reads found one Odoo order, one Deal, and the intended Company association. |
| $0 mandatory infrastructure | PASS | E9: the required local path uses no paid infrastructure or paid AI call. |
| No unsupported claims | PASS | Evidence and limitations are identified in this report; milestone labels are not used as proof. |
| Fresh verification | PASS | E2, E4, E5, and E9: focused/full checks, isolated migration, opt-in Odoo/HubSpot suites, Compose/workflow/docs/security checks passed. Live suites are listed separately from the provider-free default suite. |

## Evidence record

### E1 — Independent source, contract, and workflow review

Reviewed the Phase 9 design and M9B–M9E plans against application services,
domain transitions, persistence models/repositories, migrations, provider
adapters, API routes, settings, Odoo bridge addon, n8n export, Compose
configuration, and sandbox guides. The audit confirmed a single
PostgreSQL-backed order_syncs lifecycle with Python-owned policy and external
provider calls outside OpsFlow database transactions. The collision in
M9F-01 is the exception to the documented role boundary.

### E2 — Provider-free automated evidence at the candidate

- Focused Phase 9 unit/workflow/adapter command:
  uv run pytest tests/unit/order_sync tests/unit/orchestration
  tests/unit/workflows/test_phase9_order_sync_contract.py
  tests/unit/workflows/test_phase9_order_sync_compose_contract.py
  tests/unit/hubspot/test_adapter.py tests/unit/odoo/test_adapter.py -q
  --no-cov — 202 passed in 0.52 seconds.
- PostgreSQL-backed Phase 9 adapter/API/migration command:
  uv run pytest tests/integration/test_phase9_odoo_adapter.py
  tests/integration/test_phase9_order_sync_api.py
  tests/integration/test_phase9_order_sync_atomicity.py
  tests/integration/test_phase9_order_sync_claims.py
  tests/integration/test_phase9_order_sync_hubspot.py
  tests/integration/test_phase9_order_sync_migrations.py
  tests/integration/test_phase9_order_sync_odoo.py -q --no-cov — 50 passed
  in 22.13 seconds, using isolated runtime database
  opsflow_m9f_verify2_20261004 and migration database
  opsflow_m9f_migration2_20261004.
- The first make test-integration invocation stopped because the fresh audit
  database had not yet been initialized. After upgrading the isolated
  database, make test-integration passed with 297 tests.
- make check passed: Ruff, format, mypy, full pytest (1,622 passed, 6
  skipped), 90.52% coverage, backend package checks, frontend tests (68
  passed), lint, and build.
- The default checks did not call live providers. Odoo and HubSpot live suites
  were separately opt-in.

### E3 — Human review and approval boundary in the literal clone

The literal clone began at the frozen candidate SHA with fresh OpsFlow and
n8n state and ignored local credentials entered only for the synthetic
sandbox. Intake reached NEEDS_REVIEW; order_syncs count and external Odoo and
HubSpot matching-record counts were zero before approval. A reviewer could
correct/revalidate but received 403 on approval. The orchestration bearer
received 401 on approval. A distinct APPROVER token approved successfully.
M9F-01 demonstrates that settings do not enforce this token distinction.

### E4 — Odoo-native and JSON-2 bridge live suites

The final opt-in run used fresh disposable database
opsflow_m9e_m9f_live_20261004 and Odoo 19.0-20260926 with the documented
test-support addon path. It passed 5 tests in 0.58 seconds, covering
commit/replay, concurrent UUID collision and fresh replay, both confirmation
rollback cases, and rejection of an ordinary Sales/Stock user without the
bridge role. Test-only bot and ordinary-user keys were local mode-600 files.
The opt-in invocation was OPSFLOW_ODOO_LIVE_TESTS=1 uv run pytest
tests/odoo_live/test_phase9_bridge_json2.py -q --no-cov, with the required
disposable settings injected through the test process.

The Odoo-native bridge addon suite separately reported 0 failures and 0
errors across 13 tests in disposable database
opsflow_m9f_native_20261004, with both the bridge and test-support addons
loaded from the explicit add-on path.

An earlier attempt against the E2E database ran while its server registry did
not include the test-support path; it failed two rollback probes and left
their reserved synthetic UUID records in that disposable database. The final
suite was rerun in a fresh test database with the helper installed and runtime
path active; the final result above is the valid live-suite evidence. The
failed setup attempt was not treated as product behavior.

### E5 — HubSpot developer-test live suite

The opt-in M9D live suite passed 3 tests in 27.80 seconds against developer
portal 149461984 (DEVELOPER_TEST), using isolated OpsFlow test database
opsflow_m9d_m9f_20261004. It exercised synthetic upsert/recovery, identity
search, Deal-stage race behavior, and association checks. The suite's
successful cleanup archived its synthetic Company and Deals. An initial
runner attempt included literal quote characters from the dotenv file; that
attempt failed during cleanup search before a valid live run and before any
business writes. The corrected runner used dotenv parsing and produced the
passing result. No credentials are recorded here.
The opt-in invocation was OPSFLOW_RUN_HUBSPOT_M9D_LIVE=1 uv run pytest
tests/hubspot_live/test_phase9_hubspot_api.py -q --no-cov, with the approved
portal settings and isolated database injected through the test process.

### E6 — Literal clean-clone scheduled E2E

The full-history clone at the candidate SHA ran fresh OpsFlow PostgreSQL/API,
n8n 2.40.5, and the disposable Odoo Community server. n8n was configured with
one five-minute schedule, one execute-next HTTP call, and a UI-stored bearer
credential; no provider or orchestration secret appeared in the n8n
container's environment or workflow export. The workflow remained active
after an n8n restart and returned no_work on replay.

The valid synthetic path included pre-approval no-write checks, separate
reviewer/approver credentials, approval, scheduled execution, and a
COMPLETED order. Independent Odoo JSON-2 lookup returned one confirmed
sale.order for the OpsFlow UUID. Independent HubSpot searches found one
Company by opsflow_customer_reference_v2 and one Deal by OpsFlow order UUID.
The Deal retained amount 10, currency USD, the default pipeline, and the
initial appointmentscheduled stage. The independent association read
returned the intended Company edge with type 341. Replay created no second
logical record.

The order ID prefix for the controlled outage case was d30212d8. The
independent Odoo read returned exactly one confirmed sale order; the HubSpot
search returned exactly one Deal and the expected association to the one
synthetic Company. The temporary Odoo sale-order tax total was 10.60 while
the HubSpot amount was 10. This matches the documented design: Odoo applies
its own tax configuration while HubSpot reflects the approved pre-tax OpsFlow
order total.

### E7 — Inventory and provider outage scenarios

The separate zero-stock synthetic order reached FAILED_RETRYABLE with
INVENTORY_INSUFFICIENT and attempt_count zero. Independent Odoo and HubSpot
queries found no sale order, Deal, or association. The stock adjustment was
restored. No manual Retry was issued, preserving the no-write observation.

For the outage case, a synthetic order was explicitly approved while Odoo was
healthy. Only the disposable Odoo application container was stopped; its
database and the OpsFlow/n8n services remained available. The scheduled
execute-next call at 2026-10-04 19:10:26 UTC recorded attempt 1,
ODOO_LOOKUP, PROVIDER_UNAVAILABLE, and no provider receipts. Odoo was
restored. The next due scheduled call at 19:15:28 UTC completed the order.
The final durable row had attempt_count 1, no failure or in-flight step, and
all four provider receipts present. Independent reads found one Odoo order,
one HubSpot Deal, and one intended association. This proves scheduled
recovery without an n8n retry loop or duplicate logical records.

Other n8n branch checks reached a missing-provider 503 before claim, an
unauthorized API 401, a transport-error branch while the API container was
stopped, and HTTP 200 no_work outcomes. Each execution terminated after one
call. Success execution payload retention remained disabled.

### E8 — Clean-clone Odoo fixture permission deviation

On the literal clone, the M9C guide's fixture staging command copied a
mode-0600 host JSON fixture as a root-owned container file. The Odoo shell
process could not read it. The documented helper reported a permission
error. The run proceeded after changing the staged synthetic file's
readability in the disposable container. That unlisted manual action is why
the clean-clone acceptance row is FAIL even though the end-to-end workflow
subsequently completed.

### E9 — Migration, security, documentation, cost, and dependency hygiene

The isolated OpsFlow database upgraded to Alembic head
0006_phase9_order_syncs; /ready returned HTTP 200. The audit reviewed ignored
environment files, tracked files, workflow export, local runtime variable
names, and synthetic-only evidence. The final pinned Gitleaks scans and
relative-link checks are recorded in Fresh repository verification below.

The required local demonstration path has no mandatory paid infrastructure:
local Docker Compose, self-hosted n8n Community Edition, Odoo Community, and
the HubSpot developer-test portal. No paid AI request was used for the
acceptance path. Optional paid alternatives do not change the minimum path.
See the [n8n pricing page](https://n8n.io/pricing/), [Odoo Community
overview](https://www.odoo.com/page/community), and [HubSpot developer
platform overview](https://developers.hubspot.com/developer-platform-basics).

The unchanged web dependency tree contains one high npm advisory for
brace-expansion 5.0.9, transitive through minimatch/ESLint and limited to
development dependencies. The production-only audit reported zero
vulnerabilities and the frontend bundle does not include the package. This
is unrelated to Phase 9 and was not upgraded during the audit.

## Fresh repository verification

This section records verification performed at the frozen implementation
candidate. Documentation-only audit changes do not change runtime behavior.

| Check | Result |
| --- | --- |
| Exact candidate SHA, designated branch, ancestry, full-history clone, clean audit-start worktree | PASS; evidence recorded above |
| Fresh isolated Alembic upgrade/current | PASS; head 0006_phase9_order_syncs |
| Focused Phase 9 unit/workflow suites | PASS; 202 passed |
| PostgreSQL-backed Phase 9 adapter/API suites | PASS; 50 passed |
| make test-integration | PASS after initializing the fresh isolated database; 297 passed |
| make check | PASS; 1,622 passed, 6 skipped, 90.52% coverage; lint, types, package checks, web tests/build passed |
| Odoo opt-in JSON-2 live suite | PASS; 5 passed in 0.58 seconds |
| Odoo-native bridge addon suite | PASS; 13 tests, 0 failures, 0 errors |
| HubSpot opt-in live suite | PASS; 3 passed in 27.80 seconds |
| n8n workflow contract and live restart check | PASS |
| Full-history pinned Gitleaks v8.28.0 | PASS; 213 commits and about 4.44 MB scanned, no leaks |
| Pinned Gitleaks scan of docs | PASS; about 1.39 MB scanned, no leaks |
| Relative Markdown links | PASS; 162 relative links across 41 docs files |
| Docker Compose configuration and workflow JSON parse | PASS |
| Status consistency and git diff --check | PASS |
| npm audit and production dependency/bundle exposure review | Full audit exits 1 for one unrelated dev-only high advisory; production-only audit exits 0 with zero advisories; package name absent from web/dist |

The exact hygiene commands and results were:

- docker run --rm --volume "$PWD:/repo:ro" zricethezav/gitleaks:v8.28.0 git --redact --no-banner --verbose --log-opts="--all --full-history" /repo — exit 0, no leaks.
- docker run --rm --volume "$PWD:/repo:ro" zricethezav/gitleaks:v8.28.0 dir --redact --no-banner /repo/docs — exit 0, no leaks.
- Relative Markdown link checker from the M9F plan — exit 0, all 162 local targets exist across 41 docs files.
- docker compose config --quiet — exit 0.
- python3 -m json.tool workflows/n8n/opsflow-order-sync.json — exit 0.
- git diff --check — exit 0 for tracked documentation changes; the audit report itself was also included in the final staged whitespace check.
- npm --prefix web audit --json — exit 1, one high advisory for indirect brace-expansion 5.0.9; npm --prefix web audit --omit=dev --json — exit 0, zero vulnerabilities.
- npm --prefix web explain brace-expansion showed a development-only dependency path through minimatch and ESLint; rg found no brace-expansion reference in web/dist.
- git check-ignore -v .env integrations/odoo/.env.m9c-sandbox confirmed both local configuration files are ignored. Tracked environment files are examples only.

## Initial Closeout Decision (historical at the immutable baseline)

The valid distinct-token approval path, provider adapters, n8n scheduling,
live Odoo/HubSpot write path, replay, inventory failure, and scheduled outage
recovery passed the stated checks. Phase 9 does not qualify for closeout:

1. M9F-01 is an unresolved HIGH role-boundary defect that lets an overlapping
   orchestration bearer resolve as an APPROVER.
2. M9F-02 is an unresolved MEDIUM clean-clone setup defect.
3. Clean-clone reproducibility is FAIL, so the whole-phase gate is not met.

Keep Phase 9 and M9F IN PROGRESS. Report the findings for human review and
obtain authorization before implementing production or guide remediation.
After approved remediation, restart the affected audit evidence at the new
candidate SHA. Do not mark either status COMPLETE from this report.

Final verdict: FAIL — Phase 9 requires remediation

---

## Historical Targeted Remediation Status — Awaiting Independent Re-review at Candidate `b96364d11da37b61fd6c8bc75c651918cf596ac7`

This section records the interim state after implementation evidence was committed and before the independent targeted re-review. Its pending-review statements are historical and are superseded by the final disposition below.

The findings and FAIL verdict above are the original M9F result and remain
unchanged. The targeted remediation candidates below have implementation and
verification evidence. Both findings remain pending independent targeted
re-review. M9A–M9E remain `COMPLETE`; M9F and Phase 9 remain `IN PROGRESS`.

### M9F-01 — candidate `38b11fc000e461ff4d9dd5d7d40b26c37613c963`

Settings now rejects orchestration-token equality with each configured
`REVIEWER`, `APPROVER`, and `ELEVATED_APPROVER` token in
`review_dev_operators`. It compares parsed secret bytes with
`hmac.compare_digest`; validation errors identify the conflicting settings
without including values. No human-human uniqueness rule or role was added.

The pre-fix regression run failed to raise for all three role collisions. The
sanitized baseline probe showed settings acceptance, resolved the shared
bearer as `APPROVER`, and passed `require_approval`. Post-fix settings and
auth tests passed (89); the Phase 6/9 API authorization set passed (129).
The distinct orchestration bearer completed execute-next and received 401 on
review detail and approval routes.

**Review status:** Pending independent targeted re-review.

### M9F-02 — candidate `e06246c903b3eebe5f9e56daf7ce082ccb1d9877`

In a literal clone at the audit SHA, the documented fixture was host mode
`0600` under `umask 077`; Compose staged `/tmp/m9c-fixture.json` as UID:GID
`501:0`, mode `0600`. The Odoo shell ran as UID:GID `100:101`, and
`prepare_m9c_sandbox.py` failed at `fixture_path.read_text()` with
`PermissionError`. Running
`docker compose ... exec -T --user root odoo chmod 644 /tmp/m9c-fixture.json`
allowed the helper to complete. The synthetic fixture contains no credential.

The guide now sets mode `0644` in the fixture creation snippet. The generated
API key and result remain mode `0600`. In a separate literal clone at this
candidate SHA, Odoo 19.0-20260926 started, `sale_stock` and
`opsflow_sale_bridge` loaded, and the documented helper completed under
`umask 077` without a manual container permission command. The dedicated bot
had Salesperson, Stock User, and bridge access, with no manager, Settings,
Admin, or API-doc group. The Odoo-native suite passed 13 tests and the
disposable JSON-2 suite passed 5 tests.

**Review status:** Pending independent targeted re-review.

---

## Final Remediation and Independent Targeted Re-review Disposition

**Final re-review result:** PASS — M9F remediation closes the final Phase 9 audit findings.

The independent targeted re-review was performed against remediation evidence/status SHA `b96364d11da37b61fd6c8bc75c651918cf596ac7`. It found no Critical, High, Medium, or Low findings in remediation scope. The human-approved technical candidate is this same SHA. The historical initial FAIL verdict and its evidence above remain preserved as the original M9F result.

### Original findings and remediation

| Finding | Original severity and description | Remediation candidate | Re-review disposition |
| --- | --- | --- | --- |
| M9F-01 | HIGH — orchestration credential could overlap with a human approval credential | `38b11fc000e461ff4d9dd5d7d40b26c37613c963` | PASS — orchestration token cannot equal REVIEWER, APPROVER, or ELEVATED_APPROVER; dangerous overlap fails before application composition; distinct-token human and machine authorization remains intact. |
| M9F-02 | MEDIUM — Odoo clean-clone fixture required an undocumented permission change | `e06246c903b3eebe5f9e56daf7ce082ccb1d9877` | PASS — literal clean clone works under restrictive `umask 077`; the synthetic fixture has sufficient non-sensitive permissions, generated API-key/result files remain restrictive, and least-privilege bot access remains intact. |

### Verified closure summary

- M9F-01 rejects machine-token equality with each configured human review/approval credential before application composition. A distinct orchestration bearer can execute-next but cannot review or approve; REVIEWER review/revalidation and APPROVER approval remain intact.
- M9F-02 was verified from a literal clean checkout at the remediation evidence SHA under `umask 077`. The Odoo 19 disposable environment starts, the addon loads, and the documented fixture/helper runs without an undocumented permission command. The synthetic fixture is non-sensitive and uses the sufficient `0644` mode; generated API-key and result files remain `0600`. Odoo-native addon and disposable JSON-2/live checks passed, and the least-privilege bot setup remains intact.
- Focused and full verification recorded at the remediation evidence SHA passed. The re-review found no regression in the orchestration, reviewer, approver, Odoo, or Phase 9 path checks.

The repository-health note remains unchanged: one High advisory in transitive development-only `brace-expansion@5.0.9`, reached through frontend lint/tooling, absent from the production-only audit and production bundle, unchanged by Phase 9, and not a Phase 9 blocker.

### Final Phase 9 acceptance matrix

All required criteria are PASS after remediation and independent targeted re-review. The initial matrices above remain historical records of the original assessment; no required FAIL or PENDING status remains after this final disposition.

| # | Required criterion | Final status | Evidence / closure |
| --- | --- | --- | --- |
| 1 | M9A–M9E traceability, ownership, implementation, automated/live evidence, and limitations | PASS | E1–E7; original evidence map retained. |
| 2 | Approval intent, atomicity, eligibility, and no writes before approval | PASS | E2, E3, E6; approval gate evidence retained. |
| 3 | One durable sync lifecycle with no competing queues or receipts | PASS | E1; M9B coordinator and composition review retained. |
| 4 | Claims, fencing, lease recovery, and provider I/O outside database transactions | PASS | E1, E2; PostgreSQL concurrency and stale-claim evidence retained. |
| 5 | Failure taxonomy, retry limits, generation ownership, human Retry, and clean yield | PASS | E1, E2, E7; bounded retry and recovery evidence retained. |
| 6 | Aggregate deadline, receipt reserve, provider timeout, lease, and schedule | PASS | E1, E2, E6; implementation and observed cadence evidence retained. |
| 7 | Ordered receipts, resume from first missing receipt, and stale-claim rejection | PASS | E2, E5, E6; partial recovery and durable receipt evidence retained. |
| 8 | Odoo stable identity, races, lost response, confirmation, ACL, and trusted data | PASS | E4, E6, E7; native and JSON-2 evidence retained. |
| 9 | Exclusive HubSpot v2 customer identity | PASS | E1, E5, E6; adapter and independent identity evidence retained. |
| 10 | Deal updates preserve human-progressed stage | PASS | E1, E5; stage-race evidence retained. |
| 11 | Lost-response recovery for Odoo, Company, Deal, and association | PASS | E2, E4–E6; stable-identity replay evidence retained. |
| 12 | Strict provider response, item-error, trace, cardinality, and association validation | PASS | E1, E2, E5; provider contract evidence retained. |
| 13 | HubSpot portal/account guard before writes | PASS | E1, E2, E5; identity and pre-write guard evidence retained. |
| 14 | Provider credentials and orchestration bearer remain in intended stores | PASS | E6, E9; secret isolation evidence retained. |
| 15 | Thin n8n with one scheduled call, bounded branches, and success-data privacy | PASS | E1, E2, E6; workflow and runtime evidence retained. |
| 16 | Literal Odoo clean-clone reconstruction at the remediation candidate | PASS | M9F-02 re-review at `b96364d11da37b61fd6c8bc75c651918cf596ac7`: clean checkout, restrictive umask, addon/helper, Odoo-native tests, and disposable JSON-2/live checks verified. |
| 17 | Approved n8n → OpsFlow → Odoo → HubSpot success path | PASS | E6; synthetic end-to-end evidence retained. |
| 18 | Replay preserves one logical order, Company, Deal, association, and durable state | PASS | E5, E6; stable-identity replay evidence retained. |
| 19 | Unavailable inventory creates no external order or downstream CRM records | PASS | E2, E7; synthetic inventory-failure evidence retained. |
| 20 | Outage recovery follows M9B ownership without duplicate logical records | PASS | E7; scheduled recovery evidence retained. |
| 21 | REVIEWER, APPROVER, ELEVATED_APPROVER, and orchestration role separation | PASS | M9F-01 re-review at `b96364d11da37b61fd6c8bc75c651918cf596ac7`: overlap rejected before composition; distinct-token authorization intact. |
| 22 | Missing/partial/malformed configuration, wrong portal, invalid credential, and preclaim behavior | PASS | E2, E6; configuration and boundary evidence retained. |
| 23 | Minimal authenticated execute-next API without ID or step override | PASS | E1, E2; route and API evidence retained. |
| 24 | Durable approval, claim, failure, receipt, completion, Retry, and bounded diagnostics | PASS | E1, E2, E6, E7; persistence and audit evidence retained. |
| 25 | Migration/schema justification and fresh database upgrade | PASS | E1, E2, E9; isolated migration evidence retained. |
| 26 | Provider-free default tests and explicit live opt-ins | PASS | E2, E4, E5; automated and guarded live-suite evidence retained. |
| 27 | Full-history and changed-content secret hygiene | PASS | E9; pinned scan and repository hygiene evidence retained. |
| 28 | Unchanged development-only `brace-expansion@5.0.9` advisory and production exposure | PASS | E9; advisory is dev-only, absent from production audit/bundle, unchanged, and not a Phase 9 blocker. |
| 29 | `$0` mandatory local infrastructure cost | PASS | E9; local infrastructure and optional-service evidence retained. |
| 30 | Durable documentation agrees on status, roles, cadence, retry, and cost | PASS | Final status documents updated at this closeout; report preserves initial history and final disposition. |
| 31 | No unsupported speculative Phase 9 complexity | PASS | E1; scope review evidence retained. |
| 32 | Focused/full verification, migration, workflow, Compose, docs, and security checks | PASS | E2, E4, E5, E9 and targeted re-review verification at the approved technical candidate. |
| 33 | Complete final matrix and eligibility for Phase 9 closeout | PASS | All rows in this final matrix PASS; independent targeted re-review reports no Critical, High, Medium, or Low findings in remediation scope; human approval recorded at `b96364d11da37b61fd6c8bc75c651918cf596ac7`. |

### Final audit disposition

**Final Phase 9 verdict:** PASS — Phase 9 complete after remediation and independent targeted re-review

M9A, M9B, M9C, M9D, M9E, and M9F are `COMPLETE`. Phase 9 is `COMPLETE`. M9F and Phase 9 technical approval is recorded against `b96364d11da37b61fd6c8bc75c651918cf596ac7`. The original audit baseline and original FAIL remain historical; this is the final disposition after remediation and independent targeted re-review.
