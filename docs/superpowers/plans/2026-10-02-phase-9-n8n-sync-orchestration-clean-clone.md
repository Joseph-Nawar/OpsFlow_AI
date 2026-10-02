# Phase 9 — M9E n8n Sync Orchestration + Full Sandbox/Clean-Clone E2E

**Status:** Human-approved implementation in progress; M9E remains IN PROGRESS pending independent review.

**Planning baseline:** `phase/9-erp-crm-integrations` at
`9f319e9baeb8f6d39fccd578cfa85bda3fcb480f`. M9D is human-approved COMPLETE
at that SHA. Phase 9 remains IN PROGRESS; M9E is IN PROGRESS and M9F remains NOT STARTED.

**Goal:** Add one reproducible scheduled n8n workflow for the existing OpsFlow
order-sync API and prove, from a literal clean repository checkout, that a
synthetic approved order reaches confirmed Odoo and HubSpot records with all
receipts durable and the order COMPLETED.

**Authoritative sources:**

- [Phase 9 design](../specs/2026-09-29-phase-9-erp-crm-integrations-design.md)
- [M9B durable sync plan](2026-09-30-phase-9-durable-sync-state-claiming-recovery.md)
- [M9C Odoo sandbox](../../development/odoo-m9c-sandbox.md)
- [M9D HubSpot plan](2026-10-01-phase-9-hubspot-crm-adapter.md)
- [M9D HubSpot sandbox](../../development/hubspot-m9d-sandbox.md)
- [Development guide](../../development/development-guide.md)
- [System overview](../../architecture/system-overview.md)
- [Phase 7 workflow conventions](../../superpowers/plans/2026-09-22-phase-7-n8n-workflow-orchestration.md)
- [Existing n8n workflow guide](../../../workflows/n8n/README.md)

## Architecture

M9E adds no provider adapter, persistence, lifecycle state, retry policy,
approval logic, or execution endpoint. The existing authenticated
`POST /v1/orchestration/order-sync/execute-next` remains the sole execution
seam. It accepts no body or order ID: M9B selects and claims at most one due,
approved sync row, fences the claimant, executes the first missing provider
step through the configured `Phase9OrderSyncExecutor`, checkpoints each
confirmed receipt, and returns a bounded result.

The new `opsflow-order-sync` workflow has one five-minute Schedule Trigger,
one authenticated HTTP Request to that endpoint, a small Switch for the
returned status/result, and Set nodes that produce a concise outcome. It makes
exactly one execute-next call per scheduled execution and therefore processes
at most one eligible order per tick. Throughput optimization or draining
multiple orders in one workflow execution is outside M9E. Routing is
observational only: no branch calls a provider, mutates sync state, calculates
retry timing, sleeps, approves/rejects, chooses a provider step, or loops back
to execute-next. There is no immediate retry, Wait loop, provider node,
business payload, or state mutation in n8n. A later Schedule Trigger
invocation is the only normal retry opportunity; Python decides whether work
is due.

### Repository facts frozen for this plan

- The execute-next response is HTTP 200 with only `result`, `order_id`, and
  `state`. Results currently include `completed`, `worked`, `yielded`,
  `no_work`, `retry_wait`, and `needs_review`. The workflow must preserve a
  safe fallback for an unknown future result.
- `no_work` has null order ID and state. It covers an empty queue and work not
  currently eligible, including a retry whose backend-owned due time has not
  arrived. The API does not expose next-attempt time, and n8n must not infer it.
- `yielded` means M9B released a claim at its execution-budget boundary
  without consuming a retry event; the next schedule tick may continue the
  first missing step.
- `retry_wait` means the backend recorded a bounded failure and scheduled or
  retained recovery. After automatic retry generations are exhausted, the
  backend returns `needs_review` and requires the existing human Retry action
  when allowed. n8n does not invoke Retry or create its own failure counter.
- `needs_review` identifies an order requiring operator attention, including
  bounded terminal or operator-retry outcomes. The workflow reports the
  returned state and order ID only.
- Missing executor/configuration returns HTTP 503 with the bounded
  `ORDER_SYNC_UNAVAILABLE` response before claim or mutation. Invalid/missing
  service authentication returns HTTP 401. Neither is an order-sync retry
  event. A later schedule execution may call the endpoint again after an
  operator resolves the configuration.
- The endpoint does not return provider error bodies, provider credentials,
  durable receipt IDs, or provider payloads. Evidence for receipts is obtained
  from the existing read-only OpsFlow order/sync data and the two sandbox
  systems; no status/receipt endpoint is added.
- M9B currently owns a 210-second absolute execution budget, a five-second
  receipt-persistence reserve, per-call limits of 20 seconds for each Odoo step
  and 15 seconds for each HubSpot step, and a five-minute claim lease. The
  endpoint handles timeouts/yields and persists a successful receipt before
  returning.
- `/ready` checks database readiness only and returns 200 when the database
  is available, regardless of whether optional Odoo/HubSpot configuration is
  complete. The existing `/health` route is process liveness only. Compose can
  therefore gate n8n on `/ready` without making the documented partial-provider
  configuration or execute-next preclaim 503 unreachable; no provider-health
  endpoint or application readiness change is needed.
- Compose already pins `n8nio/n8n:2.40.5`, exposes the local n8n editor, and
  persists its local workflow/credential database in the named `n8n-data`
  volume. The API container currently receives the OpsFlow database,
  orchestration token, and review settings, but **does not receive the Odoo or
  HubSpot settings already present in `.env.example`**. M9E must close this
  deployment-wiring gap for a containerized API to build its existing
  production executor.
- The n8n container and API are already on the same Compose network; the
  workflow can use the fixed internal URL `http://api:8000`. Odoo remains the
  separate disposable Community deployment described in M9C. The clean-clone
  guide must attach that synthetic Odoo container to the isolated OpsFlow
  Compose network under a local alias (or use an equivalently private,
  verified path) and configure the API with that internal Odoo URL. It must
  not route through a shared/customer Odoo instance.
- The current M9B claim tests include
  `tests/integration/test_phase9_order_sync_claims.py::test_concurrent_claims_have_one_owner`;
  use that provider-free evidence and the execute-next API/coordinator tests to
  show concurrent calls cannot double-claim one row. If those tests do not
  assert provider invocation and durable receipt counts through simultaneous
  endpoint calls, add only that focused regression; do not add an n8n lock.
- The existing service credential is a fixed-identity bearer token resolved by
  `get_orchestration_actor` to `orchestration:n8n`. The token variable is
  `OPSFLOW_ORCHESTRATION_TOKEN`; it is not a human operator credential.
- Existing n8n artifact/export conventions use the pinned 2.40.5 runtime,
  credential references without local credential IDs, inactive sanitized
  JSON, and execution-data saving disabled. The existing API bearer credential
  is named `OpsFlow Orchestration`.
- Compose mounts the named `n8n-data` volume at `/home/node/.n8n`; n8n 2.40.5
  generates its instance encryption key on first launch and saves it in the
  `.n8n/config` file. The volume therefore preserves that key across normal
  container restarts. `N8N_ENCRYPTION_KEY` is already an optional Compose/.env
  setting and defaults to empty; M9E does not need to add or require another
  key. Leave it empty for the local demo unless an operator already uses a
  stable explicit key with that volume. A fresh clean-clone volume generates
  its own key; deleting that volume also deletes its local credential store.
  The pinned implementation evidence is the
  [n8n 2.40.5 instance-settings source](https://github.com/n8n-io/n8n/blob/n8n%402.40.5/packages/core/src/instance-settings/instance-settings.ts#L299-L344).

## Fixed workflow contract

### Request

- Method: `POST`
- URL on the local Compose network:
  `http://api:8000/v1/orchestration/order-sync/execute-next`
- Body: none
- Authentication: the existing HTTP Bearer credential named
  `OpsFlow Orchestration`
- One request per scheduled run; no caller-supplied order ID, provider fields,
  CRM/ERP payload, or lifecycle destination.
- Include Response Headers and Status: **enabled**.
- Never Error: **enabled**, so non-2xx responses such as 401 and preclaim 503
  reach the workflow for bounded observational routing instead of terminating
  the HTTP node.
- Request timeout: **240000 ms**. This gives M9B's 210-second total execution
  budget 30 seconds to finish response/receipt handling before the HTTP node's
  timeout, and leaves another 60 seconds before the next nominal 300-second
  schedule tick. The M9B five-second receipt reserve remains inside its
  existing budget. Do not change M9B's deadline, receipt reserve, provider
  limits, or lease to accommodate n8n.
- The exact serialized option fields must be discovered by configuring and
  exporting the HTTP Request node in pinned n8n `2.40.5`; do not guess JSON
  property names from another version. The imported node must show full
  response headers/status and Never Error enabled in that version.

### Schedule and concurrency

Run once every **five minutes (300 seconds)**. The HTTP Request timeout is
240 seconds; M9B's absolute executor budget remains 210 seconds, including its
existing receipt-persistence reserve. This leaves 30 seconds between the
backend execution allowance and request timeout, then 60 seconds between that
timeout and the next nominal tick. Scheduled executions should therefore
finish before the next tick; if process scheduling, a manual run, or unusual
shutdown timing causes overlap, M9B's database claim and fencing remain the
correctness mechanism. They prevent two valid owners for the same order. A
concurrent request may claim a different due order, as allowed by the existing
one-row-per-invocation contract. No n8n lock or concurrency service is added.

A five-minute cadence is adequate for the local portfolio demo and allows the
existing backend retry delays to become due before the next scheduled
opportunity. If a `retry_wait` arrives before its due time, n8n only records
that result; it does not calculate the due time or sleep. An empty/not-yet-due
run is a normal no-op. No queue, singleton lock, global n8n concurrency
setting, or worker is added.

### Response routing

The workflow routes only on HTTP status and the bounded OpsFlow response body.
All branches are observational: they emit a concise outcome and stop. In
particular, `retry_wait` is recorded as returned; a later five-minute Schedule
Trigger call is the only normal retry opportunity. The workflow never makes a
second call in the same execution.

| API response | n8n outcome | n8n action |
| --- | --- | --- |
| HTTP 200, `result=completed` | Completed | Show order ID and state; end. |
| HTTP 200, `result=no_work` | No due work | Show a quiet no-work result; end. |
| HTTP 200, `result=yielded` | Yielded | Show that M9B released the claim for a later scheduled call; end. |
| HTTP 200, `result=retry_wait` | Backend retry scheduled | Show the backend result/state; end. No Wait or retry call. |
| HTTP 200, `result=needs_review` | Operator attention | Show returned state/order ID; direct the operator to the existing OpsFlow review UI where appropriate. Never invoke human Retry. |
| HTTP 200, `result=worked` or unknown result | Bounded unexpected outcome | Show the value as an unexpected contract result without making another request. |
| HTTP 401 | OpsFlow auth configuration error | Show a fixed authentication diagnostic; no retry. |
| HTTP 503 | Sync unavailable | Show the bounded unavailable result; next scheduled invocation may check again after operator configuration work. |
| Connection/timeout or other HTTP failure | Request unavailable | Show a fixed, sanitized transport diagnostic; do not retry inside this workflow. |

HTTP 200 provider failures are application outcomes, not transport failures.
The n8n Switch must not branch on provider names, sync-step names, or internal
failure codes that the endpoint does not return. It must not treat a 200
`retry_wait` as a request to sleep.

## Security and runtime boundary

The API container receives the existing Odoo runtime settings and five
HubSpot settings from the ignored local environment. Compose interpolation
passes these values only to the API service:

- `OPSFLOW_ODOO_BASE_URL`
- `OPSFLOW_ODOO_DATABASE`
- `OPSFLOW_ODOO_API_KEY`
- `OPSFLOW_ODOO_COMPANY_ID`
- `OPSFLOW_ODOO_WAREHOUSE_ID`
- `OPSFLOW_ODOO_PRICELIST_ID`
- `OPSFLOW_HUBSPOT_SERVICE_KEY`
- `OPSFLOW_HUBSPOT_PIPELINE_ID`
- `OPSFLOW_HUBSPOT_INITIAL_STAGE_ID`
- `OPSFLOW_HUBSPOT_PORTAL_CURRENCY`
- `OPSFLOW_HUBSPOT_EXPECTED_PORTAL_ID`

The API also receives `OPSFLOW_ORCHESTRATION_TOKEN`. The n8n service receives
none of the Odoo/HubSpot provider variables and no
`OPSFLOW_ORCHESTRATION_TOKEN` as a process environment variable. It must not
use a broad `env_file` that injects the developer's complete `.env`. A static
Compose contract test and a runtime check of variable names/presence only must
prove that `OPSFLOW_ODOO_*` and `OPSFLOW_HUBSPOT_*` variables are absent from
the n8n container; never print their values. The API alone receives the
provider configuration. An operator creates the local n8n credential from
the same OpsFlow orchestration token supplied to the API.

In pinned n8n `2.40.5`, use the generic HTTP Request **Bearer Auth** credential
type (`httpBearerAuth`). Name it exactly `OpsFlow Orchestration`, enter the
local OpsFlow orchestration token in its Bearer Token field, and bind it to the
imported HTTP Request node after import. The verified exported node reference
is a portable credential name only. Do not put the credential ID or token in
the workflow JSON. The artifact is imported without a local credential ID,
then manually rebound by the clean-clone operator. No Odoo/HubSpot credential
enters n8n.

n8n encrypts local credentials with its instance key. The existing
`n8n-data:/home/node/.n8n` volume preserves the generated key file across
ordinary container restarts, so M9E does not require a new secret. Leave the
existing optional `N8N_ENCRYPTION_KEY` empty for this demo unless the operator
already pins one for that volume; if explicitly set, preserve the same value
for that volume. A fresh clean clone uses a new n8n volume and its own generated
key. Dispose of that volume only after the demo credential is no longer
needed.

Use synthetic Odoo and HubSpot data only. Keep the existing M9C integration
bot and M9D Service Key least-privilege rules, setup gates, and rotation
procedures. The API must start with a complete valid Odoo+HubSpot composition
for the live demo; missing/partial provider configuration preserves the
existing preclaim 503. Do not invent defaults.

The workflow is imported inactive. Its settings disable saved successful,
failed, and manual execution data, following existing n8n artifacts. It emits
only an allowlisted outcome, HTTP status, order ID, and order state. It does
not copy raw errors or payloads into logs or run history. Keep `.env`
ignored, use only non-secret placeholders in `.env.example`, and scan the
exported JSON and full changed history with pinned Gitleaks.

## Implementation plan

### Task 1 — Wire the existing local Compose API to the approved providers

**Expected files:** `docker-compose.yml`;
`tests/unit/workflows/test_phase9_order_sync_compose_contract.py`; and targeted
assertions in `tests/integration/test_phase9_order_sync_api.py` if needed. Do
not modify application settings, adapter code, API semantics, or database
schema.

1. Add Compose environment pass-through for the Odoo and HubSpot settings
   listed above to the **api** service only. Keep the values sourced from the
   developer's ignored `.env`; do not add secret defaults or literals.
2. Preserve n8n 2.40.5 and `n8n-data`. Keep n8n on the existing private
   Compose network and use the fixed internal API hostname.
3. First verify the current `/ready` contract: it checks the database only,
   returning healthy even when optional Phase 9 provider settings are absent
   or partial. Use that route for the API healthcheck and make n8n depend on
   API health so a new schedule does not race database/API startup. Add a
   Compose contract test plus a provider-free partial-config API test proving
   this dependency does not make execute-next's bounded preclaim 503
   unreachable and does not claim/mutate an order. Do not change `/ready` or
   application semantics. If `/ready` ever intentionally becomes provider-aware
   and fails for partial configuration, use the existing process-only `/health`
   signal instead; do not add a provider-health endpoint.
4. Keep the n8n editor, API, and local database access local-development
   surfaces only. Avoid publishing provider ports or introducing external
   infrastructure.
5. In static Compose checks, assert there is no broad `env_file` on n8n and
   provider variables are passed only to API. In the running environment,
   inspect n8n environment variable names/presence only and assert no
   `OPSFLOW_ODOO_*`, `OPSFLOW_HUBSPOT_*`, or orchestration-token process
   variable is present. Never print variable values or expanded secret-bearing
   Compose config.

**Acceptance:** `docker compose config --quiet` passes; Postgres/API/n8n start
in dependency order; `/ready` becomes healthy with complete or partial
optional provider settings when the database is available; the API constructs
the existing fixed router only with complete Odoo and HubSpot settings; the
partial-config execute-next request still returns bounded preclaim 503 without
claim/mutation; safe runtime inspection proves n8n has no provider variables;
no migration or production application code changes.

### Task 2 — Write the workflow contract test first

**Expected file:** `tests/unit/workflows/test_phase9_order_sync_contract.py`.
Reuse the existing static n8n graph-contract test style. Tests do not start
n8n, contact OpsFlow, or call providers.

Write assertions for the approved graph before creating the workflow artifact:

- exact workflow name, trigger, node types, connections, 300-second cadence,
  and one HTTP Request;
- exact POST URL and no request body;
- portable bearer credential reference is named `OpsFlow Orchestration` and
  contains no token or local credential ID;
- timeout exactly 240000 ms;
- Include Response Headers and Status enabled and Never Error enabled, so
  non-2xx responses are routed as normal node output with status and bounded
  response body;
- HTTP Request Retry on Fail disabled and no batching retry, Wait, or loop;
- explicit bounded result/status branches cover completed, no work, yielded,
  retry wait, needs review, 401, 503, transport error, and unknown outcome;
- branches retain only allowlisted result/status/order ID/state fields;
- artifact is inactive and n8n execution-data retention is disabled;
- no credential ID/token, provider hostname, provider credential name,
  provider payload field, or secret-like value appears in the workflow artifact.

Run the focused test and confirm the expected RED is that the planned workflow
artifact is absent. Do not weaken the contract to make the first run pass.

**Acceptance:** the red test captures only the fixed, approved workflow
contract and remains provider-free.

### Task 3 — Add the scheduled order-sync workflow artifact

**Expected file:** `workflows/n8n/opsflow-order-sync.json`.

1. Author/export the workflow with n8n `2.40.5`. It has one five-minute
   Schedule Trigger, one HTTP Request, a bounded HTTP-status/result Switch,
   and minimal Set nodes for readable outcome branches.
2. The HTTP Request uses the fixed endpoint, POST, empty body, existing
   `OpsFlow Orchestration` generic Bearer Auth (`httpBearerAuth`) credential reference, JSON
   response parsing, Include Response Headers and Status enabled, Never Error
   enabled, and a 240000 ms timeout. Verify the option names/serialized fields
   in the pinned `2.40.5` UI/import test. Non-2xx HTTP responses (including
   401/503) must continue to workflow routing with status and bounded body;
   connection failures use a separate error output and fixed safe diagnostic.
   Disable Retry on Fail and do not enable batching retries.
3. Route only on `statusCode` and `body.result`; use `body.order_id` and
   `body.state` as optional display evidence. For errors, emit fixed
   descriptions and safe HTTP status only. Never forward the raw response or
   exception object into the final outcome.
4. Do not add a webhook, manual business trigger, order identifier input,
   credential node for a provider, Code/Function node, Wait, retry loop,
   provider call, arbitrary execution payload, or error persistence.
5. Keep workflow inactive in the exported artifact; remove runtime credential
   IDs, execution data, and any generated account identifiers. Disable saved
   successful, failed, and manual execution data in workflow settings.
6. Export through the existing 2.40.5 workflow-export procedure and review the
   normalized JSON diff. Preserve only stable node IDs and metadata needed for
   reproducible imports.
7. Rerun Task 2's test and verify GREEN, then perform a clean-volume import
   smoke check without activating a live provider write. Link the local
   OpsFlow credential and invoke once against an isolated API configured with
   partial/missing provider settings; Never Error must route its bounded
   preclaim 503/status/body normally, with no claim or provider write.

**Acceptance:** the graph test passes; a clean n8n volume imports the artifact
inactive; after the local credential is linked and the workflow is published,
one tick makes exactly one authenticated OpsFlow request and visibly ends in
one bounded outcome.

### Task 4 — Document local import, operation, and clean reconstruction

**Expected files:** `workflows/n8n/README.md`;
`docs/development/phase9-n8n-sync-e2e.md`; optionally one short README link
to the new guide. Do not duplicate M9C/M9D provider setup instructions; link to
their sandbox guides.

Document:

- prerequisites and an isolated Compose project name so fresh PostgreSQL and
  n8n volumes cannot reuse another developer's state;
- creation of ignored `.env` from `.env.example`, generation of a local
  orchestration token, and which service receives each value. Explain that
  n8n 2.40.5 auto-generates its instance encryption key into the mounted
  `/home/node/.n8n/config` on first launch; the `n8n-data` volume preserves it
  across ordinary restarts. Leave optional `N8N_ENCRYPTION_KEY` blank by
  default; do not require another secret. An explicitly configured key must
  remain identical for that volume;
- the exact API/n8n/Odoo container-network route and how to give the disposable
  Odoo container a private alias on the isolated Compose network;
- the Odoo 19 setup, addon installation, bot/API key and synthetic records
  from the M9C guide;
- HubSpot test portal, Service Key, portal ID, unique property, pipeline,
  currency, and synthetic record requirements from the M9D guide;
- starting with a fresh n8n volume; importing the workflow inactive; creating
  the generic HTTP Request Bearer Auth credential (`httpBearerAuth`) named `OpsFlow Orchestration`
  with the existing OpsFlow bearer token; binding it manually to the imported
  HTTP Request node; testing the workflow against a synthetic unapproved/order
  with no side effects; then activating/publishing it and validating the
  Schedule Trigger. Include the credential type verified in n8n `2.40.5`;
- how to run existing Phase 7 intake with the synthetic fixture when no
  Gemini key is configured, inspect the resulting state, and have an authorized
  human approve through the existing review UI/approval API;
- expected outcome table, read-only receipt inspection, synthetic cleanup,
  workflow deactivation, and troubleshooting;
- credential replacement/revocation and volume disposal only for the named
  disposable project. Never tell developers to remove the primary development
  database volume.

The sandbox must not require hidden n8n UI state, copied primary credentials,
prior provider records, a paid Odoo/HubSpot plan, or an untracked workflow
export.

**Acceptance:** the documentation is sufficient for a second developer to
recreate the workflow from tracked files. Final clean-clone acceptance is
separately gated by Task 7's literal committed checkout at its recorded SHA;
a second Compose project using the original working directory is intermediate
isolation only.

### Task 5 — Exercise bounded response and scheduling behavior

**Expected files:** reuse `tests/integration/test_phase9_order_sync_api.py`
and workflow graph tests; modify only if a contract needed by the workflow is
not already asserted.

Provider-free PostgreSQL/API cases must establish:

1. A missing executor returns bounded 503 before claim or mutation.
2. A valid service token can invoke one endpoint call; missing/wrong tokens
   return bounded 401 and make no claim.
3. Empty/no-due work returns `no_work` with null order ID/state.
4. A successful one-order progression returns `completed` and all receipts
   persist; repeating execute-next after completion does not call a provider.
5. A clean budget yield returns `yielded` without spending a retry event.
6. A transient bounded provider failure returns `retry_wait`; the due retry
   resumes at the first missing receipt, and the response stays bounded.
7. Automatic retry exhaustion/operator action returns `needs_review`; n8n
   never invokes the review Retry API.
8. A not-approved order has no sync intent and cannot be selected; approval
   creates intent only through the current review approval contract.
9. Concurrent endpoint calls rely on M9B claim/fencing, not an n8n lock.
   Reuse `tests/integration/test_phase9_order_sync_claims.py` and the API
   coordinator suite; if current API-level tests do not prove that simultaneous
   execute-next requests yield at most one provider owner/receipt for one due
   row, add that provider-free focused regression.

Existing M9B/M9D tests already cover several cases. The implementation task
must first map each item to current test evidence and add only genuine gaps.

**Acceptance:** workflow-dependent API behavior is verified through the real
M9B coordinator and PostgreSQL with fake executors; no ordinary test requires
Odoo, HubSpot, n8n, or live credentials.

### Task 6 — Run local n8n, live synthetic E2E, and recovery rehearsal

This task uses a disposable OpsFlow database, the M9C local Odoo Community
sandbox, the M9D synthetic HubSpot developer account, and the exported workflow.
No production/customer data or paid integration is permitted.

#### Intermediate isolated sandbox rehearsal

This Task 6 run may use a separate Compose project and fresh local data while
working from the implementation checkout. It validates the end-to-end flow
before closeout but does **not** satisfy the final clean-clone acceptance gate.
Task 7 must repeat the documented procedure from a literal clean checkout of
the committed M9E candidate SHA.

#### Isolated rehearsal setup order

1. Use an isolated Compose project (for example `opsflow-m9e-rehearsal`) and
   fresh disposable data volumes. Install Python 3.12/uv, Docker Desktop with
   Compose, Node/npm if using the review UI, and the repository's documented
   local tools. This is an intermediate rehearsal, not the final clean clone.
2. Copy `.env.example` to ignored `.env`. Use the isolated Compose project
   `opsflow-m9e-rehearsal` for PostgreSQL and n8n named
   volumes. Set a unique local `OPSFLOW_ORCHESTRATION_TOKEN`; leave optional
   `N8N_ENCRYPTION_KEY` empty by default because the fresh `n8n-data` volume
   stores the first-launch generated key in `.n8n/config`. Put Odoo and HubSpot
   credentials only in local environment values consumed by API.
3. Start the documented disposable Odoo 19 Community instance with a separate
   Odoo database/PostgreSQL volume. Attach only that synthetic Odoo container
   to the isolated OpsFlow Compose network under a private alias and verify
   the API container can reach its fixed JSON-2 base URL. Do not attach a
   shared Odoo network/database.
4. Install the approved M9C bridge addon and create one synthetic company,
   warehouse, currency/pricelist, customer with exact reference `CUST-001`,
   and storable `SKU-001` with effective `lst_price=10 USD`, base Sales
   UoM, and enough scoped stock for the fixture. Follow the M9C guide for the
   dedicated bot, roles, database routing and credentials; do not commit keys.
5. Configure the dedicated HubSpot developer-test portal according to the
   M9D guide: expected portal ID, four verified runtime scopes, unique
   Company identity property `opsflow_customer_reference_v2`, unique Deal
   property `opsflow_order_id`, `opsflow_currency`, `opsflow_po_number`,
   USD, pipeline `default`, and initial stage
   `appointmentscheduled`. Keep schema/setup permissions separate from the
   runtime Service Key.
6. Start/migrate the isolated OpsFlow API and local n8n service. Verify
   `/ready`, the API's complete provider configuration and portal guard, and
   service-to-service reachability before publishing the schedule. Confirm
   partial provider configuration still leaves `/ready` healthy and
   execute-next returns its preclaim 503. No provider business write is
   permitted until the M9C and M9D live gates pass.
7. Start from the fresh n8n volume, import
   `workflows/n8n/opsflow-order-sync.json` and verify it is inactive. Create
   the `OpsFlow Orchestration` generic Bearer Auth (`httpBearerAuth`) credential locally with the
   OpsFlow bearer token, bind it to the imported HTTP Request node, and record
   the exact credential type verified in n8n `2.40.5`. Manually test the
   workflow first against no eligible order, then activate/publish and wait
   for a schedule tick. Keep provider keys out of the n8n credential store and
   process environment.
8. Use the existing Phase 7 synthetic intake workflow and
   `fixtures/phase7/synthetic-order.txt`. With Gemini unconfigured, the
   existing deterministic fake extractor supplies the synthetic draft; the
   configured Odoo provider validates trusted customer/product/price/stock.
   Confirm the order reaches `READY_FOR_APPROVAL` in OpsFlow, inspect it in
   the existing review UI, and approve it through the normal authorized
   application contract. Do not seed an approved state with direct SQL or let
   n8n approve.
9. The primary M9E success proof uses the real disposable Odoo Community
   instance, real HubSpot developer-test portal, real M9B coordinator, real
   M9C Odoo adapter, real M9D HubSpot adapter, real OpsFlow API/auth, and the
   real imported n8n workflow. Deterministic fake extraction or seeded
   synthetic application input upstream is acceptable; no fake ERP/CRM adapter
   may participate in this live success proof. Wait for the scheduled sync
   workflow. Each execution makes one execute-next request and can process at
   most one due order. If M9B returns `yielded`, the next ordinary scheduled
   tick resumes; do not add a loop.
10. Capture sanitized evidence:
   - n8n execution name/time and bounded outcome only;
   - OpsFlow order ID/state and audit events through existing read contracts;
   - a read-only query of the isolated `order_syncs` row showing non-null
     Odoo ID/name, HubSpot Company ID, Deal ID, association confirmation time,
     and no claim/in-flight step;
   - Odoo search by the stable OpsFlow UUID showing exactly one confirmed
     order and matching sequence name;
   - HubSpot lookup/count by `opsflow_customer_reference_v2` showing one
     Company, lookup/count by `opsflow_order_id` showing one Deal, and the
     exact Deal-to-Company default/unlabeled association (type 341).
   No credential, provider response body, or real customer value is captured.
11. Invoke the same scheduled workflow again. It should return `no_work`;
    independently confirm Odoo/HubSpot record counts and IDs did not change.
    A completed order must not be claimed or sent to either provider again.

#### Recovery demonstrations

- **Scheduled transient retry:** use only an infrastructure-level failure on
  the disposable Odoo service, such as temporarily stopping/disconnecting its
  application container immediately before a scheduled n8n tick. Do not
  corrupt credentials or alter retry settings. Prove in order: (1) n8n calls
  execute-next once; (2) Python classifies the provider transport failure;
  (3) M9B persists its normal retry state; (4) n8n reports the bounded result
  and ends; (5) Odoo is restored; (6) a later scheduled invocation calls the
  same endpoint; (7) M9B decides whether work is due; (8) when eligible,
  Python resumes from durable state; (9) n8n stores no recovery state. If the
  next tick is early, it may report `no_work`; wait for the next ordinary tick.
  Use an existing supported retry-delay test/demo setting only if one is
  already documented and does not change retry ownership. Otherwise accept the
  documented wait. Use a separate synthetic order from the baseline E2E.
- **Durable partial receipt:** provider-free PostgreSQL/M9B tests and the
  existing M9D live coordinator fault-injection suite remain the evidence for
  failure after Company and after Deal. They already show that receipt
  persistence selects the first missing CRM step and prevents earlier provider
  repeats. M9E does not add production fault injection or an n8n recovery
  state machine. Its static workflow test proves one call and no retry loop;
  the live scheduled retry above proves a later invocation is safe.

#### Approval and unavailable-product scenarios

- **Approval boundary:** before approving a separate READY_FOR_APPROVAL order,
  run one sync tick. It returns `no_work`; verify no order_sync intent,
  provider call, or Odoo/HubSpot record exists for that order. Approve through
  the existing review contract; only then can the atomically created sync
  intent become eligible. This is a real human/app approval, not an n8n
  branch.
- **Unavailable product/stock:** validate and approve a fresh synthetic order
  while the Odoo product is eligible and stock is sufficient. Before its first
  sync tick, reduce only that synthetic product's configured-warehouse
  `free_qty` below order quantity (or archive only that synthetic product if
  the chosen UI operation is safer). The M9C preflight must return its bounded
  existing failure and no sale order. n8n displays the returned
  `needs_review` outcome/state. Verify there is no Odoo UUID-tagged order and
  no Company/Deal/association receipt for that order. If the customer Company
  already exists from the primary success scenario, its ID/count and managed
  fields must remain unchanged; no new Company is created. The order's
  `opsflow_order_id` must have no Deal or association. Restore/discard the
  synthetic stock change. If demonstrating recovery, use the existing human
  Retry process and let the next scheduled invocation resume.

#### E2E pass/fail

Pass only when the application-derived approval, the n8n-authenticated call,
all provider confirmations, durable receipts, and final COMPLETED state agree.
A 200 from n8n or an accepted provider request alone is not success. Any
wrong portal, invalid credential, missing model/addon, configuration 503,
missing Odoo trusted data, insufficient stock, provider rejection, or receipt
mismatch stops the write run; capture the bounded failure and repair only the
documented synthetic setup before a new run.

**Acceptance:** this intermediate rehearsal performs the approved synthetic
flow, proves uniqueness on replay, preserves the approval gate, observes an
unavailable-stock rejection without downstream writes, and demonstrates a
later scheduled retry without workflow-side retry logic. Final clean-clone
acceptance is granted only by Task 7's literal committed checkout.

### Task 7 — Literal clean-clone rehearsal, documentation and closeout

After the candidate implementation has been committed, make a literal second
`git clone` and check out the exact committed M9E candidate SHA. Record that
SHA in the clean-clone evidence. An archive or second Compose project using the
original working directory does not satisfy this final gate. The final
checkout must not inherit the original
`.env`, untracked files, local n8n/OpsFlow/Odoo volumes, cached Python/frontend
state, ad-hoc scripts, undocumented addon copies, or hidden machine settings.
Use a distinct recorded Compose project name for this clone and fresh n8n,
OpsFlow database, and disposable Odoo volumes so Docker cannot resolve any
named volume or network from the original project; supply external sandbox
credentials manually as the guide says.
Create fresh temporary Python and frontend package-cache directories for this
rehearsal rather than reusing machine-global caches; remove them after the
run. Do not copy `.venv`, `node_modules`, package caches, Docker bind-mounted
state, or helper scripts from the original working directory.
Use the M9C addon from this exact checkout. Follow only the new M9E guide and
linked existing M9C/M9D guides. Record sanitized setup evidence including the
candidate SHA, Odoo version/image digest, n8n tag, HubSpot portal type/ID (not
Service Key), scope names, selected pipeline/stage, provider record IDs,
results, and cleanup.

From this literal checkout, repeat the complete cross-provider success flow,
approval boundary, repeated invocation, unavailable-stock path, and scheduled
retry. For n8n specifically prove: it starts from documented Compose state;
the workflow imports successfully and is initially inactive; the local
OpsFlow credential is created and rebound manually; a manual test works with
synthetic data; the workflow can then be activated; and the Schedule Trigger
runs as documented. Do not reuse the original developer's n8n volume.

**Expected verification:**

- `docker compose config --quiet`
- focused n8n workflow-contract tests
- existing Phase 9 API/coordinator/PostgreSQL tests
- affected M9B claim, fencing, approval, retry and deadline regressions
- M9C Odoo provider-free regressions and opt-in disposable Odoo JSON-2 suite
- M9D HubSpot provider-free regressions and opt-in synthetic live suite
- `make check`
- `make test-integration`
- isolated `uv run alembic upgrade head` and `uv run alembic current`
- `git diff --check`
- pinned Gitleaks full-history and changed-content scan

Use a freshly named OpsFlow database for destructive migration integration
tests. Do not reset/downgrade the developer database. Normal automated tests
must not contact Odoo or HubSpot; live tests remain explicitly opt-in and
synthetic.

**Acceptance:** final clean-clone evidence comes from a literal checkout at the
recorded committed candidate SHA with fresh n8n/OpsFlow/Odoo state, no inherited
developer files or caches, and the complete E2E/recovery proof. A second
Compose project in the original checkout is intermediate evidence only. The
implementation commit contains no runtime secrets or local n8n credential ID;
all required tests pass and the M9E acceptance matrix is reviewable. M9E
remains IN PROGRESS until independent audit/human approval; implementation
verification alone does not close it.

## Expected file boundary

### Status/planning files

- `README.md` — current status paragraph.
- `docs/roadmap/project-roadmap.md` — canonical M9D closeout status.
- `docs/superpowers/specs/2026-09-29-phase-9-erp-crm-integrations-design.md` — Phase 9 milestone status.
- `docs/development/development-guide.md` — consistent current status.
- `docs/superpowers/plans/2026-10-01-phase-9-hubspot-crm-adapter.md` — current M9D approval metadata only; no implementation-plan redesign.
- This plan.

### M9E implementation files

- `docker-compose.yml` — API-only provider settings pass-through, API
  readiness check, and n8n readiness dependency. Keep existing PostgreSQL 16,
  pinned n8n 2.40.5 and persistent n8n data volume.
- `workflows/n8n/opsflow-order-sync.json` — sanitized scheduled execution
  workflow.
- `tests/unit/workflows/test_phase9_order_sync_contract.py` — provider-free
  exported-graph assertions.
- `workflows/n8n/README.md` — import/publish reference and link to the
  Phase 9 end-to-end guide.
- `docs/development/phase9-n8n-sync-e2e.md` — local setup, networking,
  credentials, synthetic scenarios, evidence, cleanup and clean-clone steps.
- `tests/integration/test_phase9_order_sync_api.py` — only if Task 5's
  evidence mapping identifies an uncovered existing API/coordinator contract.
- `.env.example` — no new secret or provider variable is expected; the current
  example already names all Odoo, HubSpot, OpsFlow token, and n8n encryption
  settings. Edit only if inspection during implementation finds a required
  non-secret setting missing.

No Python production source, API schema/route, Alembic migration, Odoo addon,
HubSpot adapter, M9B contract, or M9C/M9D provider behavior is expected to
change.

## M9E acceptance matrix

| Criterion | Owning task | Provider-free evidence | Local/live evidence |
| --- | --- | --- | --- |
| One reproducible sanitized scheduled `opsflow-order-sync` workflow exists | 2–4 | Workflow graph-contract test; clean import validation | Fresh n8n volume imports inactive, credential relinked, published |
| Workflow calls only the existing authenticated execute-next API | 2–3 | Static URL/method/body/auth assertions; no provider hosts/nodes | One n8n execution observed at the API boundary |
| Imported workflow artifact contains no bearer token, provider credential, or local n8n credential ID | 2–4 | Static artifact allowlist/secret assertions | Fresh-volume import, manual credential binding succeeds |
| Credential can be manually rebound from documentation under `OpsFlow Orchestration` | 3–4, 7 | Workflow artifact uses a portable credential reference; docs name the verified 2.40.5 generic Bearer Auth (`httpBearerAuth`) type and steps | Clean clone creates the OpsFlow-only credential and binds the imported HTTP Request node |
| n8n runtime environment contains no Odoo/HubSpot credential variables or OpsFlow token | 1, 7 | Compose test rejects broad `env_file` and provider pass-through on n8n | Inspect running n8n variable names/presence only; assert absent without printing values |
| HTTP Request exposes response status/headers and bounded body; Never Error is enabled | 2–3 | Static workflow contract checks the verified 2.40.5 serialized options | Isolated partial-config API returns preclaim 503 and n8n routes it normally |
| HTTP Request timeout is exactly 240000 ms | 2–3 | Static workflow-contract assertion | Imported n8n 2.40.5 node shows 240000 ms |
| HTTP Request Retry on Fail and batching retries are disabled | 2–3 | Static workflow-contract assertion; no Wait/loop nodes | Imported node configuration and one-call execution confirm no immediate retry |
| Preclaim 503 is observable without crashing the workflow | 1–3, 5 | Partial-config API test proves bounded 503 before claim/mutation | n8n receives/routes 503 with Never Error; no business write occurs |
| Five-minute Schedule Trigger makes one execute-next call and handles at most one order per tick | 2–3, 5 | Graph test asserts 300-second cadence/one HTTP Request; M9B one-row contract test | Schedule execution evidence shows one endpoint call; throughput batching remains out of scope |
| Schedule, timeout, lease and M9B retry semantics are compatible | 1–3, 5 | Existing M9B budget/deadline/concurrency tests and simultaneous-claim evidence | 300-second cadence, 240-second request timeout, 210-second M9B budget/reserve; M9B fencing protects any overlap |
| `/ready`/Compose dependency preserves partial-provider preclaim 503 behavior | 1, 5 | Compose static test plus API/PostgreSQL partial-config test; `/ready` remains database-only | API healthy with partial providers; n8n starts and observes bounded preclaim 503 |
| M9D status recorded as COMPLETE at approved SHA; M9E planning does not claim implementation | Status | Status-source consistency check | Branch/review record retains approval SHA |
| Approved order is the only sync-eligible work | 5–6 | M9B approval/intent/claim tests | Before approval: no work/provider write; after human approval: eligible sync completes |
| Odoo trusted lookup/price/inventory and confirmation rules are honored | 6–7 | Existing M9C provider-free and isolated-addon/JSON-2 tests | Real M9C adapter against disposable Odoo shows exact confirmed order; insufficient stock creates none |
| HubSpot Company, Deal and association converge with receipts | 6–7 | Existing M9D fake/PostgreSQL adapter tests | Real M9D adapter against developer-test portal shows one Company, one Deal, one type-341 association, matching receipt IDs |
| Repeated scheduled execution creates no logical duplicates | 6 | Existing completed-order and same-identity coordinator tests | Repeat returns no work and remote counts/IDs remain unchanged |
| Retry/resume remains in Python/M9B | 5–6 | PostgreSQL test: retry_wait then due invocation resumes first missing step | Stop/restart disposable Odoo; later n8n schedule resumes and completes |
| Receipts persist before later steps and survive downstream failure | 5–6 | Existing M9B/M9D partial-receipt tests and M9D live wrapper evidence | Existing synthetic partial-recovery evidence linked from M9D guide |
| Literal clean checkout at a recorded committed candidate SHA reconstructs and demonstrates the flow | 7 | Tracked-doc/link checks; candidate SHA recorded | Second `git clone` at exact M9E candidate SHA with no inherited `.env`, untracked files, volumes, caches or scripts reaches COMPLETED |
| Final clean clone uses a fresh n8n volume/key and imports inactive before credential binding | 3–4, 7 | Static artifact inactivity and credential-ID exclusion checks | Fresh n8n volume imports inactive, OpsFlow credential is manually rebound, manual test succeeds, then activation/schedule succeeds |
| Secrets, private data, and execution payloads remain contained | 1–4, 7 | Gitleaks and workflow allowlist tests | Credential store/API/provider boundary inspection; synthetic data only |
| Standard repository and migration verification passes | 7 | `make check`, `make test-integration`, isolated Alembic | Odoo/HubSpot opt-in suites pass against their own sandboxes |
| M9F remains untouched | 1–7 | Diff/scope audit | No M9F audit or closure claim |

## Complexity, cost, risks and rollback

The only new production artifact is one exported n8n workflow. The existing
`Phase9OrderSyncExecutor`, M9B coordinator, adapters, authenticated route,
Compose services, and local n8n volume are reused. The Compose wiring is
necessary because the current API container is not passed the already-approved
provider configuration. The workflow needs no Python helper, second executor,
API endpoint, database state, queue, polling worker, or provider abstraction.

Mandatory development cost remains $0: Docker Desktop/local PostgreSQL,
Odoo Community, local n8n Community Edition, the existing free HubSpot
developer-test account, and the deterministic fake extractor. No paid hosting,
HubSpot subscription, or Gemini key is required.

The principal operational risks are an incorrectly routed Odoo container, a
wrong HubSpot portal/key, stale local volumes, and accidental approval bypass.
The guide verifies database/provider identities before writes, uses a unique
Compose project and disposable Odoo database, imports n8n inactive, requires
manual OpsFlow approval, and records remote/local receipt IDs before replay.
If a gate fails, deactivate the workflow and stop before synthetic writes.
Rollback consists of deactivating the workflow and stopping only the isolated
Compose project; preserve evidence first. Remove only the named disposable
synthetic volumes and provider records after verification. Never use a broad
`docker compose down -v` against a developer's normal project.

## Explicit non-goals

M9E does not implement M9F, new provider behavior, Odoo/HubSpot calls from
n8n, CRM/ERP payload construction, contacts, Gmail identity, approval or Retry
actions in n8n, another API endpoint, another sync-state/persistence model,
workers, queues, automatic provider retries, dynamic provider routing,
production cloud deployment, Kubernetes, dashboards, generalized workflow or
provider frameworks, or schema/migration changes.

## Git boundary and completion rule

The planning/status update is documentation-only and remains uncommitted for
human review. After plan approval, M9E implementation should begin from the
then-approved branch HEAD, preserve the M9D commit history, and make one
coherent implementation commit for Compose/workflow/tests plus a focused docs
commit only if repository convention or review size warrants it. Do not mark
M9E COMPLETE from implementer verification alone. M9F remains NOT STARTED until
M9E is independently reviewed and human-approved.
