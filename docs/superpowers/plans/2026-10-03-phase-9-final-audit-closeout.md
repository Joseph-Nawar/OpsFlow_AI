# Phase 9 Final Independent Audit and Closeout Plan

> **For the future audit owner:** Perform the audit sequentially in a fresh review context. This plan authorizes inspection and verification only; production changes require a concrete finding and human-approved remediation.

**Goal:** Independently determine whether the implemented Phase 9 path satisfies its approved ERP/CRM design end to end, safely and reproducibly, then record evidence and close Phase 9 only if every required gate passes.

**Architecture:** Audit the implemented chain from human approval through the single durable M9B coordinator, M9C Odoo adapter, M9D HubSpot adapter, and M9E scheduled n8n workflow. Python remains the authority for business correctness, provider adapters make bounded external calls, and n8n schedules and routes one execute-next result per tick. M9F adds evidence and closeout, not product behavior.

**Tech Stack:** Python 3.12, pytest, PostgreSQL 16, SQLAlchemy/Alembic, FastAPI, Docker Compose, Odoo 19 Community, HubSpot developer-test portal, n8n 2.40.5, Node.js 24/npm, Git, and pinned Gitleaks v8.28.0.

**Spec:** [Approved Phase 9 design](../specs/2026-09-29-phase-9-erp-crm-integrations-design.md), especially Sections 8–20; the M9B, M9C, M9D, and M9E plans and their sandbox guides are evidence to verify, not substitutes for inspection.

## Global Constraints

- M9F scope is independent validation, adversarial audit, release-quality evidence, and phase closeout; it does not authorize new feature scope or unapproved architecture changes.
- n8n schedules; Python owns correctness; M9B owns durable state, retry accounting, claims, fencing, receipts, and completion; adapters own bounded provider calls.
- No external write is permitted unless OpsFlow has durably approved the order and created its sync intent.
- Provider calls remain at-least-once. Verify at-most-one logical Odoo order, Company per trusted customer reference, Deal per OpsFlow order, and intended association.
- Use only synthetic records and the documented disposable Odoo Community instance and HubSpot developer-test portal. Never use shared or customer systems.
- Keep provider credentials in ignored local configuration consumed by the API; the orchestration bearer belongs only in n8n's credential store. Never print or commit secret values.
- Normal tests must remain provider-free. Live suites require their existing explicit opt-in flags and isolated test accounts.
- Keep required local infrastructure at `$0`; do not add paid services, infrastructure, dependencies, queues, retries, or generalized frameworks to the audit.
- Inspect first and keep any remediation out of the audit until a concrete finding has been reported and the user has approved a focused change.
- Preserve n8n successful-execution privacy behavior: `saveDataSuccessExecution="none"` can leave soft-deleted rows with stale status columns; those rows are inactive and omitted from ordinary history. Do not enable success-data retention to reinterpret them.
- Preserve local role separation: REVIEWER corrects and revalidates; APPROVER approves. The n8n orchestration credential can do neither.

## Review Focus

1. Repeated or overlapping execute-next calls before approval must not claim or write an unapproved order; verify with PostgreSQL-backed approval, atomicity, and concurrency tests.
2. A stale worker or a late provider response must not persist a receipt after fencing changes; verify stale-token rejection and one-owner claim behavior under PostgreSQL concurrency.
3. A provider mutation with a lost response must resume by stable identity and the first missing durable receipt, never blind-create an additional logical record; inspect Odoo and HubSpot replay tests and live evidence.
4. A human-progressed HubSpot Deal must not have its stage overwritten during existing-Deal update or create-race recovery; inspect the final adapter path and exercise provider-free race cases.
5. A clean clone must not rely on local environment files, provider/n8n volumes, untracked helpers, or caches; perform the final rehearsal at the recorded immutable candidate SHA.

---

## Status and Scope Baseline

- Phase 9 is `IN PROGRESS`.
- M9A, M9B, M9C, M9D, and M9E are `COMPLETE`; M9E has human-approved completion at `8b1f6941f2070017724346c4acb93d1d16cfa492`.
- M9F is `NOT STARTED`. Creating this plan does not begin the audit.
- M9F's canonical scope is **Independent Whole-Phase-9 Audit**: independently audit contracts, code, migrations, tests, external sandbox evidence, privacy, cost, and documentation; close findings with evidence; pass required scenarios and clean-clone acceptance; report the audited commit and tree state.
- The Phase 9 design and roadmap agree on that scope. No scope conflict was found.

The audit treats milestone closeouts as claims. Record an evidence source for every conclusion, and distinguish current code inspection, automated tests, prior live evidence, and any new M9F live run.

## Files and Responsibilities

| Path | M9F responsibility |
| --- | --- |
| `docs/superpowers/plans/2026-10-03-phase-9-final-audit-closeout.md` | This execution-ready audit plan; created before M9F starts. |
| `docs/audits/phase-9-audit.md` | Create only during M9F to record the requirement/evidence map, findings, complete acceptance matrix, sanitized live/clone evidence, verification commands, cost/security notes, and closeout decision. |
| `docs/roadmap/project-roadmap.md` | Canonical phase/milestone status; update to Phase 9 and M9F `COMPLETE` only after all closeout gates pass and human approval is recorded. |
| `docs/superpowers/specs/2026-09-29-phase-9-erp-crm-integrations-design.md` | Approved Phase 9 contract and milestone status; update the status summary only at successful closeout. |
| `docs/development/development-guide.md` | Consistent current phase/milestone status and repository verification conventions. |
| `docs/superpowers/plans/2026-10-02-phase-9-n8n-sync-orchestration-clean-clone.md` | M9E implementation evidence and approval metadata; do not redesign M9E. |
| `docs/development/phase9-n8n-sync-e2e.md`, `docs/development/odoo-m9c-sandbox.md`, `docs/development/hubspot-m9d-sandbox.md` | Follow committed procedures; modify only if a concrete reproducibility defect or newly verified fact requires a focused correction. |
| `src/opsflow/`, `integrations/odoo/`, `alembic/versions/`, `tests/`, `workflows/n8n/`, `docker-compose.yml`, `web/` | Read-only audit targets. No production behavior change is part of the planned audit work. |

## Audit Tasks

### Task 1: Freeze the candidate and build the requirement-to-evidence map

**Files:** Read the Phase 9 design, M9B–M9E plans, roadmap, development guide, sandbox guides, code, migrations, tests, workflow export, and existing closeout evidence. Create the traceability table in `docs/audits/phase-9-audit.md` only when the audit runs.

- [ ] Record branch, full candidate SHA, commit ancestry, `git status --short --branch`, and whether the clone has full history. Audit one immutable SHA; restart the baseline if audited code changes.
- [ ] Map each design requirement to its owner milestone, production code, provider-free automated evidence, applicable live evidence, and limitation/finding. Include M9A's approved contract and independently recheck M9B–M9E implementation evidence rather than using their status labels as proof.
- [ ] Separate prior M9C/M9D/M9E sandbox evidence from new M9F runs. Record the date and exact candidate SHA for new evidence, and identify the specific disposable Odoo database and developer-test portal without recording credentials.
- [ ] Confirm M9E completion provenance is the user-approved SHA `8b1f6941f2070017724346c4acb93d1d16cfa492`; record the audit candidate SHA separately from any later audit-report/closeout commit.

**Check:** Every Phase 9 design and acceptance requirement has an owner, code location, evidence location, and explicit limitation or `PENDING` status. No inference from a milestone label alone.

### Task 2: Inspect architecture, API boundaries, provider identity, security, and documentation

**Files:** Read `src/opsflow/application/order_sync.py`, `src/opsflow/order_sync/`, `src/opsflow/orchestration/`, `src/opsflow/api/orchestration.py`, `src/opsflow/odoo.py`, `src/opsflow/hubspot.py`, `src/opsflow/main.py`, `src/opsflow/settings.py`, `src/opsflow/persistence/`, `alembic/versions/0006_phase9_order_syncs.py`, `workflows/n8n/opsflow-order-sync.json`, `docker-compose.yml`, and the linked Phase 9 docs.

- [ ] Trace order approval intent, atomic insert, eligibility, execute-next auth, each provider mutation, and durable receipt persistence. Attempt no live write during this static pass.
- [ ] Search for competing sync lifecycle, queue, attempt counter, operation/receipt copy, or provider execution in n8n, adapters, API composition, and helper scripts. Verify `order_syncs` and the M9B coordinator are the only correctness-critical lifecycle.
- [ ] Inspect claim eligibility, fencing, lease expiry/recovery, transaction scopes, and absolute deadline call paths. Verify provider I/O is outside OpsFlow database transactions and repeated M9E calls cannot bypass fencing.
- [ ] Compare every failure code with M9B retry/operator semantics: `PROVIDER_UNAVAILABLE`, `PROVIDER_RATE_LIMIT`, `PROVIDER_PENDING`, `PROVIDER_REJECTED`, `PROVIDER_INVALID_RESPONSE`, `INTEGRATION_CONFIG`, `IDEMPOTENCY_CONFLICT`, `RECONCILIATION_REQUIRED`, and business outcomes including `INVENTORY_INSUFFICIENT`. Check maximum attempts, retry-generation reset, explicit human Retry, `Retry-After`, and clean yields.
- [ ] Reconstruct the deadline budget from code/config and verify the approved 210-second M9B aggregate cap, five-second receipt reserve, provider allowances, five-minute lease, 240-second n8n timeout, and five-minute schedule. Identify any hidden lower-level retry or incompatible timeout.
- [ ] Trace receipt order: Odoo lookup/trusted evidence where applicable, Odoo order, HubSpot Company, HubSpot Deal, association, then completion. Verify first missing receipt controls resume; later failure cannot repeat earlier durable work; a stale claim cannot save a receipt; and completion requires every required receipt.
- [ ] Audit Odoo's stable OpsFlow UUID bridge contract, unique constraint, create-race loser/replay, lost-response reconciliation, confirmation/rollback, no-sudo behavior, bot role, trusted price/inventory, and existing-order handling.
- [ ] Verify Company identity is only `opsflow_customer_reference_v2` in operational code/config/tests/workflow/examples. Search the entire tracked tree for the exact obsolete property token, excluding the `_v2` suffix (for example, `rg -n --pcre2 '(?<![A-Za-z0-9_])opsflow_customer_reference(?![A-Za-z0-9_])' .`). Permit only clearly historical, non-operational prose explaining the rejected name; never a fallback, migration source, runtime alternate, or repair path.
- [ ] Re-read the final HubSpot Deal create/update logic. New Deals are create-only with the initial stage; existing Deals are PATCHed by provider ID without `dealstage` or `pipeline`; post-update reconciliation follows the approved contract. Reassess human-progress and concurrent-create races against current code and tests.
- [ ] Trace uncertain Company, Deal-create, Odoo, and association writes from provider request through stable identity lookup/replay to durable receipt. No ambiguous response or HTTP acceptance alone may yield a receipt.
- [ ] Inspect HubSpot response validation for HTTP 200/207, omitted top-level errors, intended-item errors, wrong trace, zero/multiple results, `PENDING`, `PROCESSING`, `CANCELED`, malformed association result, and confirmed terminal success.
- [ ] Verify expected portal identity is checked before any business write. Review 401/403, wrong portal, transient identity endpoint failure, and rate-limit handling for a fail-closed path.
- [ ] Trace credential source and process environment end to end: Odoo and HubSpot secrets only reach Python/API; n8n has no provider secret or orchestration-token environment entry; only the n8n credential store holds the orchestration bearer; workflow JSON, tracked fixtures, and docs contain no secrets.
- [ ] Verify the n8n export has one five-minute trigger and one execute-next call, handles at most one order/tick, contains no loop/retry/wait/provider URL/business decision, and routes results observationally. Preserve disabled success-data retention and the documented soft-deleted stale-row interpretation.
- [ ] Verify REVIEWER can correct/revalidate, APPROVER can approve, and the orchestration identity can neither review, correct, nor approve. Check `POST /v1/orchestration/order-sync/execute-next` remains authenticated, bounded, has no order-ID override, and accepts no step-selection input.
- [ ] Review persisted audit fields for approval, claim, failure, retry, receipt, completion, and explicit Retry. Confirm diagnostics remain bounded and omit raw provider bodies and credentials.
- [ ] Compare migrations and ORM models: expected head, only justified durable state, constraints/uniqueness aligned with receipt identity, and no abandoned M9D operation-handle schema.
- [ ] Check committed guides agree on provider identity, Deal create/PATCH semantics, schedule, timeout, roles, clean clone, retry ownership, and `$0` mandatory infrastructure. Mark historical superseded prose so it cannot be read as current instructions.
- [ ] Search for unused or speculative Phase 9 abstractions/configuration/routes/state. Record only concrete dead or risky complexity; do not remove cosmetic declarations.

**Check:** The audit report cites paths and focused line/function references for each conclusion, and records all uncertainty as a finding or `PENDING` item.

### Task 3: Run provider-free adversarial and PostgreSQL verification

**Files:** Read existing tests under `tests/unit/order_sync/`, `tests/unit/orchestration/`, `tests/unit/odoo/`, `tests/unit/hubspot/`, `tests/unit/workflows/`, and the Phase 9 integration tests. Add no tests during the audit unless a human-approved concrete remediation requires them.

- [ ] Use a fresh isolated PostgreSQL database for integration, concurrency, and migration checks. Do not reset or downgrade a developer database.
- [ ] Run focused Phase 9 unit/workflow tests:

  ```bash
  uv run pytest tests/unit/order_sync tests/unit/orchestration tests/unit/odoo tests/unit/hubspot \
    tests/unit/workflows/test_phase9_order_sync_contract.py \
    tests/unit/workflows/test_phase9_order_sync_compose_contract.py -q --no-cov
  ```

- [ ] Run focused M9B–M9D PostgreSQL adapter tests:

  ```bash
  uv run pytest \
    tests/integration/test_phase9_order_sync_api.py \
    tests/integration/test_phase9_order_sync_atomicity.py \
    tests/integration/test_phase9_order_sync_claims.py \
    tests/integration/test_phase9_order_sync_hubspot.py \
    tests/integration/test_phase9_order_sync_migrations.py \
    tests/integration/test_phase9_order_sync_odoo.py \
    tests/integration/test_phase9_odoo_adapter.py -q --no-cov
  ```

- [ ] Review existing assertions for a repeated execute-next call before approval, atomic approval/intent, two concurrent claimants, stale fence, expired lease, budget yield, every failure code, max attempts, human Retry, generation reset, receipt preservation/resume, and no provider call inside an OpsFlow transaction. Require at least one forced stale-worker or overlap scenario.
- [ ] Exercise or verify provider-free adversarial response cases: lost Odoo/Company/Deal/association response; 200/207 item error and trace mismatch; zero/multiple results; nonterminal/canceled/malformed results; wrong portal; invalid credentials; partial/malformed provider configuration; human-progressed Deal race; and create race. Ambiguous evidence must not create a receipt.
- [ ] Confirm ordinary suites and `make check` do not perform provider writes. Then run explicit opt-in live suites only in Task 4, after their isolation gates pass.

**Pass condition:** All existing required assertions pass against fakes/fresh PostgreSQL and each failure outcome preserves the specified M9B state, attempt accounting, receipt ordering, and bounded diagnostics. Missing evidence is a finding; do not make an assertion weaker to obtain a pass.

### Task 4: Reproduce the E2E path from a literal clean clone

**Files:** Follow only committed `docs/development/phase9-n8n-sync-e2e.md`, `docs/development/odoo-m9c-sandbox.md`, and `docs/development/hubspot-m9d-sandbox.md`. Create the audit's sanitized run record in `docs/audits/phase-9-audit.md`.

- [ ] After the audited implementation candidate is immutable, make a literal fresh clone and check out its exact SHA. Use fresh OpsFlow/PostgreSQL, n8n, and disposable Odoo state. Do not copy `.env`, credentials, provider/n8n volumes, untracked helpers, `.superpowers` state, or caches from the developer checkout. Enter ignored credentials manually from the designated sandbox setup.
- [ ] Rebuild the Odoo Community bridge and synthetic company/warehouse/pricelist/customer/product/stock from the tracked guide. Use the documented HubSpot developer-test portal/setup and narrow Service Key. Confirm Odoo database identity, expected HubSpot portal ID, configured currency/stage, and authorization before writes; stop on any setup mismatch.
- [ ] Verify clean-clone setup, migrations, `/ready`, role credentials, workflow import inactive, one five-minute schedule, one authenticated execute-next call, timeout 240000 ms, no provider variables in n8n, and no secret in workflow export. Do not infer runtime credential values from variable names.
- [ ] Before approval, invoke execute-next and prove no claim, order-sync intent, Odoo order, Company/Deal, or association is created. Then REVIEWER performs correction/revalidation and the distinct APPROVER uses the normal approval contract. n8n cannot perform either action.
- [ ] Run one synthetic approved success through n8n → OpsFlow/M9B → Odoo/M9C → HubSpot/M9D. Record sanitized OpsFlow UUID, final state, Odoo order ID/reference, HubSpot Company ID, Deal ID, association type 341, durable receipts, and completion. Do not include secrets, raw provider bodies, real customer values, or unnecessary response payloads.
- [ ] Run the existing explicit live suites only after account and isolation gates pass, using ignored process environment values from the committed setup guides:

  ```bash
  OPSFLOW_ODOO_LIVE_TESTS=1 uv run pytest tests/odoo_live/test_phase9_bridge_json2.py -q --no-cov
  OPSFLOW_RUN_HUBSPOT_M9D_LIVE=1 uv run pytest tests/hubspot_live/test_phase9_hubspot_api.py -q --no-cov
  ```

  The Odoo suite requires complete disposable runtime settings, synthetic customer/SKU, and the test-only ordinary-user key. The HubSpot suite requires its documented test-only Service Key, pipeline, initial-stage, and currency settings. Never put values in the plan/report or command history; use the existing clean-clone procedure to enter them locally.
- [ ] Repeat the scheduled execution and independently count/search by stable identities. Prove one logical confirmed Odoo order, one Company for the trusted customer reference, one Deal for the order UUID, the intended association, and no durable state regression.
- [ ] Run a separate synthetic insufficient-stock scenario using the documented safe procedure. Prove authoritative `INVENTORY_INSUFFICIENT`/specified `FAILED_RETRYABLE` and explicit human Retry semantics, no Odoo order, no Deal/association, and no ordinary n8n automatic retry. Restore/discard only the synthetic stock change.
- [ ] Demonstrate one controlled transient provider outage with the documented disposable Odoo container stop/disconnect procedure and a separate synthetic order. Prove a single n8n call, bounded provider failure, M9B retry due-time ownership, no workflow retry state, and safe later scheduled recovery. If the normal five-minute cadence lands before the retry due time, record its bounded no-work result and wait for a due tick. Cross-check provider-independent HubSpot partial-receipt recovery against Task 3 and prior M9D live evidence.
- [ ] Verify n8n's HTTP 200 success/result, 401, provider-incomplete preclaim 503, and transport-error branches terminate after one call with bounded display data. Keep `saveDataSuccessExecution="none"`; treat soft-deleted rows with stale status as inactive, omitted from ordinary history, and not authoritative outcome evidence. Do not enable success retention.
- [ ] Record exact clone SHA, tool/provider versions, clean state provenance, bounded outcomes, independent provider counts/IDs, and deviations. If any prerequisite comes from outside committed docs, record it as a reproducibility finding.

**Safety boundary:** Only synthetic data, the designated disposable Odoo Community database, and the HubSpot developer-test account are allowed. No production/customer write is allowed. Never use destructive cleanup against any unowned Compose project or account data.

### Task 5: Run full fresh verification, migration, repository hygiene, and cost/dependency checks

**Files:** Run from the audited candidate checkout, with PostgreSQL available and a separate migration-test database. Capture command and result in the audit report.

- [ ] Run a fresh Alembic upgrade/current and migration suite against isolated databases:

  ```bash
  uv run alembic upgrade head
  uv run alembic current
  uv run pytest tests/integration/test_phase9_order_sync_migrations.py -q --no-cov
  ```

  Set `OPSFLOW_DATABASE_URL` and `OPSFLOW_MIGRATION_TEST_DATABASE_URL` to separate databases in a newly created audit-only PostgreSQL service before running tests. Do not reuse a developer database.

- [ ] Run full integration and project quality gates:

  ```bash
  make test-integration
  make check
  docker compose config --quiet
  git diff --check
  ```

- [ ] Run JSON parsing and exported-workflow contract tests for `workflows/n8n/opsflow-order-sync.json`; verify no ordinary suite activated the schedule or reached a provider. Record M9C native addon tests and explicit Odoo JSON-2/HubSpot live suites separately from fake-backed evidence.
- [ ] Run pinned Gitleaks v8.28.0 over full history using the command in `docs/development/development-guide.md`, plus this no-Git scan over planning/status/audit docs before closeout:

  ```bash
  docker run --rm --volume "$PWD:/repo:ro" \
    zricethezav/gitleaks:v8.28.0 \
    dir --redact --no-banner /repo/docs
  ```

  Inspect tracked files, `.env` ignore rules, workflow export, fixtures, and sanitized sandbox IDs for unintended private or secret material.
- [ ] Validate relative Markdown destinations across `docs/` without adding a tool dependency. This standard-library check ignores external/fragment-only links and fenced examples, and requires each local target to exist:

  ```bash
  python3 - <<'PY'
  from pathlib import Path
  import re
  from urllib.parse import unquote, urlsplit

  files = sorted(Path("docs").rglob("*.md"))
  link = re.compile(r"!?\[[^\]]*\]\(([^)]*)\)")
  broken = []
  checked = 0
  for path in files:
      in_fence = False
      for line_no, line in enumerate(path.read_text().splitlines(), 1):
          if line.lstrip().startswith(("```", "~~~")):
              in_fence = not in_fence
              continue
          if in_fence:
              continue
          for match in link.finditer(line):
              raw = match.group(1).strip().split(maxsplit=1)[0] if match.group(1).strip() else ""
              if raw.startswith("<") and raw.endswith(">"):
                  raw = raw[1:-1]
              parsed = urlsplit(raw)
              if not raw or parsed.scheme or raw.startswith("//") or raw.startswith("#") or not parsed.path:
                  continue
              checked += 1
              if not (path.parent / unquote(parsed.path)).resolve().exists():
                  broken.append((path, line_no, raw))
  for path, line_no, target in broken:
      print(f"BROKEN {path}:{line_no}: {target}")
  print(f"Checked {checked} relative Markdown targets across {len(files)} docs files.")
  if broken:
      raise SystemExit(1)
  print("All relative Markdown targets exist.")
  PY
  ```

  Check roadmap/design/development/M9E-plan statuses are consistent; historical statements remain contextual and operational guidance reflects current decisions.
- [ ] Re-run `npm --prefix web audit --json` and dependency-tree/bundle inspection on the audited lockfile. Classify the known high npm advisory in unchanged `brace-expansion@5.0.9` via ESLint/minimatch by confirming it is dev-only and absent from production runtime/bundle. If confirmed, record it as an unrelated repository-health issue; do not upgrade frontend dependencies in M9F without a demonstrated Phase 9/runtime security impact. Record the audit command's nonzero exit separately from Phase 9 gates.
- [ ] Verify the mandatory demo path still uses only local Docker, Odoo Community, local n8n, and HubSpot developer-test portal at `$0`. List optional paid products only as optional if existing docs mention them.

**Check:** Commands are freshly run against the exact audit candidate. A previously observed result is historical evidence, not a current pass. No test result is inferred from this plan.

### Task 6: Complete the matrix, report findings, and decide whether closeout is allowed

**Files:** Create `docs/audits/phase-9-audit.md`; link it from `docs/roadmap/project-roadmap.md` only after the audit has passed and human closeout approval is recorded.

- [ ] Populate every row of the Phase 9 acceptance matrix below with exactly `PASS`, `FAIL`, or `PENDING`, direct evidence, and any limitation. Do not mark a row PASS from a plan, mock-only behavior where live proof is required, or a milestone label.
- [ ] Log each finding with severity, affected requirement, evidence/path, concrete impact, bounded remediation recommendation, and status. Distinguish a Phase 9 blocker from unrelated repository health.
- [ ] If any required item is PENDING, any Critical/High/Medium finding remains unresolved, the literal clone depends on hidden state, or a required live scenario fails, report M9F `IN PROGRESS`, Phase 9 `IN PROGRESS`, and stop before closeout status changes.
- [ ] If all required rows PASS and no unresolved Critical/High/Medium finding remains, compile the report with evidence, verification command/output summaries, clean-clone and live setup, cost/security notes, limitations, exact audited candidate SHA, final audit-report commit SHA when available, branch, created commits, and final tree state.
- [ ] Request human approval of the concrete M9F report and audited SHA. This plan does not grant that approval.

### Task 7: Remediate only approved concrete findings, then re-review

- [ ] Report findings before changing production code or configuration. Do not self-authorize remediation as part of an audit finding.
- [ ] After human approval, implement only the smallest focused correction for an evidenced defect, with targeted tests and a coherent commit; no redesign or speculative cleanup.
- [ ] Restart the audit at the changed candidate SHA for affected requirements. Re-run targeted independent review plus any invalidated clean-clone, live-provider, security, or regression evidence. Preserve prior evidence only where its audited code and configuration remain identical.
- [ ] Return to Task 6 with updated evidence and status rows. Keep M9F and Phase 9 in progress until every required condition is met.

### Task 8: Close Phase 9 only after the human-approved clean gate

- [ ] After a clean matrix and human approval, update roadmap, Phase 9 design status, and development-guide status coherently: M9A–M9F `COMPLETE`, Phase 9 `COMPLETE`, and the exact audited candidate SHA recorded. Preserve the original M9E approval SHA as milestone provenance.
- [ ] Link the final audit report from the roadmap. Do not create another architecture document or mark completion from test success alone.
- [ ] Review the complete diff, confirm `git diff --check`, relative Markdown links, pinned Gitleaks, no secrets, and the exact branch/HEAD/commit/tree state. Commit the coherent closeout record; report the clean working tree and the implementation candidate SHA separately from the final report commit if they differ. The closeout commit's own SHA is reported after commit rather than embedded in itself.

## Requirement-to-Evidence Coverage

| # | Required audit dimension | Owning milestone / primary evidence to inspect | Planned task |
| --- | --- | --- | --- |
| 1 | M9A–M9E requirement traceability; owner, implementation, automated/live proof, limitation | Phase 9 design; M9B–M9E plans; `src/opsflow/`; `tests/`; sandbox guides | 1 |
| 2 | Approval intent, atomicity, eligibility, n8n, Odoo and HubSpot write gates; repeated preapproval calls | `application/order_sync.py`, approval/review commands, provider adapters, API, atomicity and claims tests | 2–3 |
| 3 | One durable lifecycle; no second retry/queue/hidden operation/duplicate receipt state | `order_sync/`, persistence models/repository, adapters, composition, workflow, helpers | 2 |
| 4 | Claiming, fencing, lease recovery, external I/O outside transactions, concurrent execute-next | M9B coordinator/repository and PostgreSQL claims tests; M9E call behavior | 2–3 |
| 5 | Full failure taxonomy, retries, operator action, generations, attempt caps, human Retry, clean yield | M9B failure/state code and tests; M9C/M9D adapters and tests | 2–3 |
| 6 | 210s aggregate deadline, five-second receipt reserve, provider allowances, five-minute lease, 240s request, five-minute schedule | M9B deadline code/config; provider timeout code; M9E workflow and guide | 2 |
| 7 | Receipt order, resume from first missing receipt, stale claim rejection, required receipt completion | M9B executor/persistence; M9C/M9D step code; PostgreSQL resume tests | 2–3 |
| 8 | Odoo stable UUID/idempotency, create race, lost response, confirm, ACL/no sudo, trusted price/stock, reconciliation | Odoo adapter/addon; M9C unit/integration/native/live tests and guide | 2–4 |
| 9 | Exclusive `opsflow_customer_reference_v2`; obsolete name not operational | `src/opsflow/hubspot.py`, tests, docs, workflow, tracked config | 2 |
| 10 | Deal create-only/initial stage; existing-ID PATCH omits stage/pipeline; post-update reconciliation and races | HubSpot adapter/tests; M9D live evidence and guide | 2–3 |
| 11 | Odoo, Company, Deal, association lost-response recovery by stable identity and receipts | Odoo bridge, HubSpot adapter, M9B receipts; provider-free and live evidence | 2–4 |
| 12 | Strict Odoo/HubSpot response validation incl. 200/207/item errors/traces/cardinality/nonterminal/canceled/association | `odoo.py`, `hubspot.py`, fake-backed contract tests, M9D live evidence | 2–3 |
| 13 | HubSpot portal guard before writes; 401/403/wrong portal/transient identity/rate limit | Settings/composition/HubSpot adapter, unit/integration tests, synthetic portal | 2–4 |
| 14 | Odoo/HubSpot API-only secrets; orchestration bearer only in n8n store; no secret env/export/docs | settings, Compose, n8n JSON, `.env.example`, tracked files, runtime name checks | 2, 4–5 |
| 15 | Thin n8n: one five-minute trigger/call, one order/tick, no retry/loop/wait/provider URL/business rule; 200/401/503/transport; privacy semantics | workflow export/test, E2E guide, local runtime evidence | 2, 4 |
| 16 | Literal clean clone at immutable candidate SHA with fresh OpsFlow/n8n/Odoo and manually entered ignored credentials | M9E guide and new M9F clean-clone record | 4 |
| 17 | Synthetic approved end-to-end n8n→OpsFlow→M9B→Odoo→HubSpot path and bounded IDs/receipts | Clean-clone run and independent provider lookups | 4 |
| 18 | Replay yields one logical order, Company, Deal, association and no durable regression | Clean-clone replay plus independent provider counts/identity lookups | 4 |
| 19 | Unavailable inventory; no Odoo order/Deal/association; business failure and explicit human Retry; no n8n retry | M9C/M9B tests and separate clean-clone synthetic scenario | 3–4 |
| 20 | One transient provider outage, due-time recovery, no n8n retry, no duplication | M9E documented Odoo-container interruption and M9B/M9D provider-independent recovery evidence | 3–4 |
| 21 | REVIEWER/APPROVER/orchestration roles; n8n cannot review/correct/approve | review auth/composition, E2E setup, auth tests and clean-clone behavior | 2–4 |
| 22 | Missing/partial/malformed provider config, wrong portal, invalid credential and preclaim behavior | Settings/composition/API tests and no-write runtime probes | 2–4 |
| 23 | Minimal authenticated execute-next seam; no ID override or step-selection input | orchestration route/schema/auth code and API tests | 2–3 |
| 24 | Persisted evidence for approval, claim, failure, retry, receipt, completion, explicit Retry; bounded diagnostics | domain/audit models and API read contracts; persistence tests | 2–3 |
| 25 | Migration/schema justification, expected head, constraints, no abandoned M9D operation schema, fresh DB upgrade | ORM, migrations `0001`–`0006`, migration tests, fresh Alembic DB | 2, 3, 5 |
| 26 | Provider-free default tests; explicit live opt-in; credible fakes; no developer-state dependency | pytest configuration, fixtures, live suite guards, CI and test tree | 3, 5 |
| 27 | Pinned full-history and changed-content Gitleaks; `.env` ignores; tracked files/workflow/evidence hygiene | CI, development-guide command, Git index, workflow and reports | 5 |
| 28 | Verify unchanged dev-only `brace-expansion@5.0.9` high advisory and no production bundle exposure; no unrelated upgrade | npm lock/tree/audit output and built frontend artifact | 5 |
| 29 | `$0` mandatory local infrastructure, with optional paid services identified separately | Phase 9 design and all three sandbox guides | 2, 4–5 |
| 30 | Durable-doc consistency for statuses, IDs, Deal behavior, cadence/timeout, roles, clone, retry and cost | roadmap, design, plans, development/provider guides, workflow README | 1–2, 6 |
| 31 | Concrete unused/speculative Phase 9 complexity only; avoid cosmetic cleanup | source/config/test/schema search and runtime wiring | 2, 6 |
| 32 | Focused suites, full integration/check, fresh Alembic upgrade/current, links, Gitleaks, diff check | `Makefile`, `pyproject.toml`, CI, migrations | 3, 5 |
| 33 | Final acceptance matrix; no unresolved C/H/M and no required PENDING before close | `docs/audits/phase-9-audit.md` and direct evidence links | 6, 8 |

## Phase 9 Final Acceptance Matrix

At M9F start, initialize each row as `PENDING`. Change it only when the stated direct evidence exists. A required row left `PENDING` prevents Phase 9 closeout.

| Criterion | Minimum evidence required | Status |
| --- | --- | --- |
| Approval gate | Preapproval execute-next and concurrent/repeated calls yield no claim or provider write; atomic approval and durable intent pass | PENDING |
| Exactly-once logical Odoo order | UUID bridge uniqueness, forced race/lost-response recovery, independent live count equals one | PENDING |
| Exactly-once logical HubSpot Company | v2 identity only; replay keeps one matching Company and receipt | PENDING |
| Exactly-once logical HubSpot Deal | order UUID identity, create-only and safe existing-ID update; replay count equals one | PENDING |
| Intended association | persisted Company/Deal IDs, confirmed default/type-341 association, no unintended association | PENDING |
| Durable partial recovery | first missing receipt resumes; earlier completed provider work does not repeat | PENDING |
| Fencing and concurrency | one eligible claim, stale worker rejected, concurrent execute-next cannot double-own or persist stale receipt | PENDING |
| Bounded retries | failure taxonomy, deadlines, lease, due times, attempts/generation, explicit human Retry and clean yield all match M9B | PENDING |
| Provider failure mapping | unavailable, rate-limited, pending, rejected, invalid, configuration, identity conflict, reconciliation, and inventory cases map safely | PENDING |
| Account guard | wrong portal/invalid credentials/transient identity failures stop before business writes | PENDING |
| Human Deal-stage preservation | current-stage race is rechecked; existing update omits `dealstage` and `pipeline`; progressed stage is not overwritten | PENDING |
| Thin n8n | one five-minute trigger/call, bounded observation only, no loops or retries/provider URLs/business decisions | PENDING |
| Clean-clone reproducibility | literal clean checkout at recorded immutable SHA reconstructs from committed instructions and fresh state | PENDING |
| Secret isolation | Gitleaks/history and changed-content scans clean; runtime names and artifacts show no secret crossing | PENDING |
| Live end-to-end success | synthetic approved order completes through n8n/OpsFlow/Odoo/HubSpot with all receipts and bounded IDs | PENDING |
| Idempotent replay | repeated schedule call leaves each provider identity/count and durable state unchanged | PENDING |
| Unavailable inventory | no Odoo sale order or downstream Deal/association; authoritative outcome and manual retry semantics verified | PENDING |
| Outage recovery | one synthetic provider outage is recorded; due scheduled call recovers under M9B ownership without duplicates | PENDING |
| `$0` mandatory infrastructure | committed setup requires no paid service; optional paid alternatives are called optional | PENDING |
| No unsupported claims | every report/roadmap statement links to evidence; fakes, prior runs, and live runs are labeled accurately | PENDING |
| Fresh verification | focused Phase 9 tests, `make test-integration`, `make check`, fresh Alembic upgrade/current, workflow/Compose/docs/security checks pass | PENDING |

### Closeout Rule

M9F and Phase 9 may be marked `COMPLETE` only when every required row is `PASS`, no required criterion is `PENDING`, no Critical/High/Medium finding remains unresolved, live and clean-clone evidence match the exact immutable candidate SHA, and the human approves the concrete audit report. If any gate fails or remains pending, M9F and Phase 9 remain `IN PROGRESS`; report the finding and wait for human-approved remediation before changing production behavior.

## Expected M9F Deliverables

- This audit plan (presently planning-only; it does not create audit evidence or start M9F).
- `docs/audits/phase-9-audit.md` with traceability, finding log, all 33 audit dimensions, completed PASS/FAIL/PENDING matrix, clean-clone and live evidence, fresh commands/results, known limitations, cost/security notes, and closeout decision.
- A coherent status/roadmap update only after M9F passes and the human approves closeout.

No new architecture document, test-only framework, provider abstraction, or production feature is planned. If remediation is authorized, its focused code/test changes and commits become additional audit evidence and require targeted independent re-review.
