# Phase 9 n8n order-sync demo and clean-clone guide

This guide runs the already-built M9B coordinator through the portable n8n
workflow in [`workflows/n8n/opsflow-order-sync.json`](../../workflows/n8n/opsflow-order-sync.json).
n8n makes one authenticated call to OpsFlow per five-minute scheduled
execution. Python remains responsible for approval, provider calls, retries,
claims, receipts, deadlines, and recovery. n8n does not call Odoo or HubSpot.
The local mandatory infrastructure cost is `$0`: Docker, Odoo Community,
n8n Community, and the HubSpot developer-test portal.

For provider account setup, use the [Odoo M9C sandbox guide](odoo-m9c-sandbox.md)
and [HubSpot M9D sandbox guide](hubspot-m9d-sandbox.md). This document covers
only the local orchestration and the synthetic cross-provider proof.

The current M12B implementation now creates `ORDER_SYNC_COMPLETED` notification
intents atomically with the completed order and audit event after all required
receipts are durable. Slack is independent of Gmail delivery; a Gmail reply is
created only when persisted Gmail-source provenance and its original message
ID are present. Both intents use the existing n8n notification dispatcher and
authenticated outcome contract. The historical M9E runs described below
predate this behavior and do not count as evidence of post-sync notifications.
The owner-approved M12C-3 sandbox transaction and its limited-scope evidence
disposition are recorded at the end of this runbook. Twelve supplied raw
post-run screenshots and separate sanitized derivatives are privately
prepared for review; they are not contemporaneous transaction footage. The
M12B implementation
itself made no live provider calls. The M12C-3 transaction did make the
separately authorized synthetic sandbox operations described in its record;
it remains factually PARTIAL because the first Gmail Trigger intake POST
returned HTTP 401 and the same original source required owner-assisted
recovery. Automated Gmail Trigger-to-OpsFlow intake is NOT DEMONSTRATED.

## Prerequisites and isolation

Use Git, Docker with Compose, Python 3.12, `uv`, and Node/npm only when using
the review UI. Use synthetic records and a dedicated disposable Odoo database
and HubSpot developer-test portal. Never point this workflow at a shared or
customer system.

The Compose project name prefixes its network and named volumes. Use a fresh,
unique project name for every rehearsal (examples below use
`opsflow-m9e-demo`). The tracked Compose file binds local PostgreSQL, API, and
n8n ports to loopback. Ensure ports 5432, 8000, and 5678 are free; if needed,
stop existing containers with `docker compose stop` only. Do not use `down -v`
on another project and do not remove its volumes.

From a checkout of the implementation candidate, create ignored local config:

```sh
if [ ! -e .env ] && [ ! -L .env ]; then
  cp .env.example .env
else
  printf '%s\n' 'Existing .env path found; leaving it unchanged.'
fi
```

Set a unique random `OPSFLOW_ORCHESTRATION_TOKEN` locally. Set all six Odoo
values from the dedicated disposable M9C setup and all five HubSpot values
from the synthetic M9D portal. Set an `OPSFLOW_REVIEW_DEV_OPERATORS` JSON
array with two distinct local operators, for example:

```dotenv
OPSFLOW_REVIEW_DEV_OPERATORS='[{"token":"<local-random-reviewer-token>","actor":"m9e-reviewer","role":"REVIEWER"},{"token":"<different-local-random-approver-token>","actor":"m9e-approver","role":"APPROVER"}]'
```

Replace both placeholders locally with different unique random values. Keep
every credential only in ignored `.env` or the local credential UI; never
commit or share a value. The `REVIEWER` credential is for review, revalidation,
and correcting stale sample/order values. The separate `APPROVER` credential
is for the approval action after review is complete. They remain distinct
application roles even when one person operates both during the demo. The
orchestration token is only for n8n-to-API execution. None of these credentials
is an Odoo or HubSpot credential.

An incomplete or absent optional provider configuration does not make the API
unready. `/ready` checks API/database readiness only. In this configuration,
Compose still starts n8n and the authenticated execute-next request returns
bounded HTTP 503 before claiming work. For a no-write smoke test, leave one or
more provider settings blank in a fresh project; confirm `/ready` is 200 and
execute-next is 503. Restore the complete synthetic provider configuration
before the live E2E.

Start and migrate a fresh Compose project:

```sh
uv sync --frozen --dev
docker compose -p opsflow-m9e-demo up --wait postgres
# Run the read-only effective database-target check in README.md before migration.
make migrate
uv run alembic current
docker compose -p opsflow-m9e-demo up -d --build --wait api n8n
curl --fail http://127.0.0.1:8000/ready
```

This sequence is for a later authorized local run; it was not executed during
the M12C preflight. The `--wait` command waits for PostgreSQL's configured
health check before migration. Immediately before `make migrate`, run the
read-only effective-database-target check documented in the README's
[local-development section](../../README.md#local-development). It parses the
same settings URL Alembic uses, prints no credential, and must confirm
`postgresql+asyncpg` at `localhost:5432`, database `opsflow`, user `opsflow`.
The project name must be new and owned by this disposable run; if port 5432 is
occupied or project/volume ownership is unclear, stop. Compose configures the
API's container-side database URL to `postgres:5432`. The API healthcheck gates
n8n on `/ready`; a provider-incomplete API can stay healthy while execute-next
returns the documented preclaim 503.

The API service alone receives the Odoo and HubSpot settings through explicit
Compose variable mappings. The n8n service has no `.env_file`, receives no
`OPSFLOW_ODOO_*`, `OPSFLOW_HUBSPOT_*`, or
`OPSFLOW_ORCHESTRATION_TOKEN` process variable, and stores only its local
OpsFlow bearer credential in n8n's credential store. Check variable names
without printing values:

```sh
docker compose -p opsflow-m9e-demo exec -T n8n node -e '
const names = Object.keys(process.env).filter((name) =>
  name.startsWith("OPSFLOW_ODOO_") ||
  name.startsWith("OPSFLOW_HUBSPOT_") ||
  name === "OPSFLOW_ORCHESTRATION_TOKEN"
);
if (names.length) {
  process.stderr.write(`Unexpected OpsFlow variables in n8n: ${names.join(", ")}\n`);
  process.exit(1);
}
process.stdout.write("No OpsFlow provider or orchestration-token variables in n8n.\n");
'
```

n8n is pinned to `n8nio/n8n:2.40.5`. Its `n8n-data` project volume mounts
at `/home/node/.n8n`; the runtime generates the instance encryption key in
`.n8n/config` on first launch and the volume preserves it through normal
container restarts. Leave the optional `N8N_ENCRYPTION_KEY` blank unless the
operator already uses a stable value for that volume. A fresh project gets a
fresh n8n volume and key. Removing that project's volume also removes its
local credential store; do so only after the demo is finished.

## Import, credential binding, and schedule

Open `http://localhost:5678`. In the local n8n credential manager, create a
credential of type **Bearer Auth** (`httpBearerAuth`) named exactly
`OpsFlow Orchestration`. Enter the raw local OpsFlow orchestration token in
the credential's **Bearer Token** field; n8n adds the `Authorization: Bearer`
scheme. Do not put `Bearer ` in the token field. This credential is the only
OpsFlow credential n8n needs. Do not add Odoo or HubSpot credentials.

Import `workflows/n8n/opsflow-order-sync.json` from file. Confirm it is
inactive. Open **Execute Next Sync**, select the local `OpsFlow Orchestration`
credential, and save. The exported artifact contains a portable credential
name reference but no developer-machine credential ID or secret. Manual
rebinding is part of every clean import.

The pinned HTTP Request 4.5 node contract is:

- POST to `http://api:8000/v1/orchestration/order-sync/execute-next` with no
  request body;
- **Include Response Headers and Status** enabled;
- **Never Error** enabled, so bounded 401/503 status and response body reach
  observational routing;
- timeout `240000` ms;
- **Retry On Fail** disabled and no batching retry.

The five-minute Schedule Trigger makes exactly one request per execution and
therefore handles at most one eligible order per tick. The 240-second n8n
timeout leaves 30 seconds after M9B's unchanged 210-second total execution
budget and another 60 seconds before the next normal 300-second tick. M9B's
claim/fencing remains safe if a manual or delayed invocation overlaps; no n8n
lock is needed. A later schedule tick is the only normal retry opportunity.
n8n does not loop, wait, retry, calculate a retry time, or choose a provider
step.

Successful execution-data retention remains disabled to avoid storing the raw
HTTP response. In n8n `2.40.5`, a completed execution whose success data is
discarded can leave a soft-deleted database row with stale `running`/unfinished
columns. A row marked deleted and absent from n8n's execution list is not an
active run; do not use that raw database row as the workflow outcome. Use the
sanitized terminal branch result when running manually and the durable OpsFlow
order-sync state/receipts for completion evidence. Do not enable full success
data retention just to preserve an execution-history row: the HTTP node output
contains response headers and body.

Use **Test Workflow** while inactive, first with no eligible order. It should
finish with a bounded `no_work` result. If provider settings are intentionally
incomplete in the isolated project, the workflow should instead report HTTP
503 without crashing. Confirm the output contains only bounded outcome/status
and safe result/order/state fields. Then publish/activate the workflow and
observe one Schedule Trigger execution. Deactivate it after the rehearsal.

The outcome branches are observational:

| Observed response | Expected n8n result |
| --- | --- |
| HTTP 200 `completed`, `worked`, `yielded`, `no_work`, `retry_wait`, or `needs_review` | Report the bounded result and stop. |
| HTTP 401 | Report a fixed OpsFlow authentication diagnostic and stop. |
| HTTP 503 | Report the bounded unavailable result and stop. |
| Connection/timeout | Report a fixed sanitized transport outcome and stop. |
| Unknown bounded response | Report an unknown outcome and stop. |

Only a future scheduled invocation may call execute-next again. A returned
`retry_wait` before its due time is merely observed; M9B decides eligibility.

## Prepare synthetic Odoo, HubSpot, and review data

Follow the M9C guide's **Recreate the local Community service from a clean
checkout** procedure for a disposable Odoo 19 Community instance, addon,
dedicated least-privilege integration bot, company/warehouse/pricelist, and
synthetic customer/product/inventory. That procedure uses the tracked
`integrations/odoo/docker-compose.sandbox.yml` and
`integrations/odoo/prepare_m9c_sandbox.py` from the candidate checkout; do not
copy an addon directory or seed script from another developer environment.
Follow the M9D guide for the dedicated
HubSpot developer portal, Service Key scopes, portal identity, properties,
pipeline/stage, and test-record cleanup. Use only synthetic customer and
product references. For a separate Odoo Compose deployment, attach its
container to the isolated OpsFlow network under a private alias, then set the
API's local `OPSFLOW_ODOO_BASE_URL` to that alias (for example
`http://opsflow-odoo:8069`). Verify connectivity from the API container before
allowing business writes. Do not join a shared/customer Odoo network.

### Match the no-Gemini Phase 7 fixture to Odoo

With Gemini unconfigured, the existing Phase 7 deterministic extractor emits
the synthetic pair `CUST-001` / `SKU-001` at USD 10. The M9C seed helper also
creates its own separately named random-reference customer and product for
M9C live tests; those records do not satisfy the Phase 7 order's exact Odoo
lookup. Keep the M9C records and provision this additional fixture in the
fresh M9E disposable Odoo database before creating an OpsFlow order. Run the
following Odoo shell setup as the disposable database administrator after
the M9C helper has created the company, USD currency, and warehouse. The
database-name guard prevents running it against a shared database. If either
reference already belongs to a different record, the command stops rather
than changing it.

```sh
set -a
. integrations/odoo/.env.m9c-sandbox
set +a
M9E_ODOO_DATABASE=opsflow_m9e_clean_clone
M9E_ODOO_PROJECT=opsflow-m9e-clean
docker compose --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml -p "$M9E_ODOO_PROJECT" \
  exec -T -e PGHOST=db -e "PGUSER=$M9C_POSTGRES_USER" \
  -e "PGPASSWORD=$M9C_POSTGRES_PASSWORD" \
  -e "OPSFLOW_M9E_DATABASE=$M9E_ODOO_DATABASE" odoo \
  odoo shell -c /etc/odoo/odoo.conf -d "$M9E_ODOO_DATABASE" --no-http <<'PY'
import os, re

database = os.environ.get("OPSFLOW_M9E_DATABASE", "")
if env.cr.dbname != database or not re.fullmatch(r"opsflow_m9e_[a-z0-9_]+", database):
    raise RuntimeError("M9E fixture setup requires its named disposable Odoo database")
company = env.company.sudo()
usd = env.ref("base.USD").sudo()
warehouse = env["stock.warehouse"].sudo().search(
    [("company_id", "=", company.id)], limit=1
)
if company.currency_id != usd or not warehouse:
    raise RuntimeError("M9E fixture requires the configured USD company and warehouse")

partners = env["res.partner"].sudo().search([("ref", "=", "CUST-001")], limit=2)
if len(partners) > 1:
    raise RuntimeError("CUST-001 is duplicated in the disposable database")
partner = partners[:1]
if partner:
    if (partner.name != "Acme Industries" or partner.company_id != company
            or not partner.active or not partner.is_company or partner.customer_rank < 1):
        raise RuntimeError("CUST-001 is occupied by an unexpected customer")
else:
    partner = env["res.partner"].sudo().create({
        "name": "Acme Industries", "ref": "CUST-001", "is_company": True,
        "customer_rank": 1, "company_id": company.id, "active": True,
    })

products = env["product.product"].sudo().search([("default_code", "=", "SKU-001")], limit=2)
if len(products) > 1:
    raise RuntimeError("SKU-001 is duplicated in the disposable database")
product = products[:1]
if product:
    if (product.name != "Widget" or product.company_id != company
            or not product.active or not product.sale_ok or not product.is_storable
            or round(product.lst_price, 2) != 10.00):
        raise RuntimeError("SKU-001 is occupied by an unexpected product")
else:
    template = env["product.template"].sudo().create({
        "name": "Widget", "type": "consu", "is_storable": True,
        "sale_ok": True, "list_price": 10.0, "company_id": company.id,
    })
    product = template.product_variant_id.sudo()
    product.write({"default_code": "SKU-001"})
location = warehouse.lot_stock_id
available = product.with_context(location=location.id).qty_available
delta = 100.0 - available
if delta:
    env["stock.quant"].sudo()._update_available_quantity(product, location, delta)
env.cr.commit()
print("M9E synthetic fixture ready: CUST-001 / SKU-001 / USD 10 / 100 units")
PY
```

The fixture matches the existing fake extraction payload; it does not alter
the n8n Phase 9 workflow, OpsFlow validation policy, or live M9C adapter.

Use the existing review contract to correct its sample's out-of-date order
and requested-delivery dates before approval, if current date validation
routes that deterministic sample to review.

For importing and triggering the separate upstream Phase 7 intake workflow,
follow the [n8n workflow guide](../../workflows/n8n/README.md#opsflow-sandbox-intake-workflow)
and reuse the same local `OpsFlow Orchestration` credential. This intake
workflow is only synthetic input setup; the M9E order-sync workflow remains
the sole Phase 9 execution path.

If creating orders through the review UI, start the frontend from this
checkout:

```sh
npm --prefix web ci
npm --prefix web run dev -- --host 127.0.0.1
```

Use the Phase 7 sandbox-intake workflow with the local `OpsFlow Orchestration`
credential to submit the existing synthetic intake fixture and
[`fixtures/phase7/synthetic-order.txt`](../../fixtures/phase7/synthetic-order.txt).
Use a fresh event ID. Open `http://127.0.0.1:5173` and authenticate the review
UI with the local development `REVIEWER` credential. Inspect the resulting
order and correct any stale order/requested-delivery dates, then use **Save &
revalidate**. Confirm the order reaches `READY_FOR_APPROVAL`. Sign out or
switch credentials, authenticate the UI with the distinct `APPROVER`
credential, and perform the existing approval action. These remain separate
application roles even if one person operates both. No direct database seeding
of an approved order is permitted. n8n cannot approve or synchronize an order
with no approved sync intent.

## End-to-end acceptance runs

Use the real M9B coordinator, M9C Odoo adapter, M9D HubSpot adapter, OpsFlow
API, and imported n8n workflow. The primary success path must use real
disposable Odoo Community and the real HubSpot developer-test portal. Fake
ERP/CRM adapters are not acceptable for that proof; deterministic extraction
or synthetic input upstream is acceptable.

### Approval boundary

Create a separate unapproved `READY_FOR_APPROVAL` synthetic order. Invoke the
order-sync workflow once. It should return `no_work`; confirm no sync intent,
Odoo order, HubSpot Deal, or association exists for that order. Then approve
with the separate `APPROVER` credential through the existing authorized
OpsFlow review contract. Only OpsFlow creates the durable sync intent. Invoke
the same thin workflow again; n8n supplies no order ID and cannot override
approval.

### Successful order

Approve a synthetic order with a trusted Odoo customer and available product
stock, then wait for the scheduled workflow (or use one manual test execution
while inactive). Capture sanitized evidence from each existing system:

1. n8n: execution time and bounded outcome only.
2. OpsFlow: order UUID, `COMPLETED`, and presence of Odoo, Company, Deal, and
   association receipts through existing read/audit contracts.
3. Odoo: exactly one confirmed sale order tagged with the OpsFlow UUID and its
   order reference.
4. HubSpot: exactly one Company by `opsflow_customer_reference_v2`, exactly
   one Deal by `opsflow_order_id`, and the confirmed Deal-to-Company default
   relationship with type `341`.

Invoke the workflow again. It should report `no_work`; record that provider
IDs/counts did not change. One call per workflow execution is intentional;
M9E does not drain a queue in a loop.

### Unavailable stock

Prepare and approve a second synthetic order while its Odoo data is eligible,
then before its first sync tick lower only that synthetic product's scoped
`free_qty` below the requested quantity (or archive the synthetic product if
that is safer). The existing M9C validation should return the bounded
business result. Verify no Odoo sale order, HubSpot Deal, or association was
created for that order. The shared Company may already exist for the customer;
that is allowed by the approved contract and must not be deleted. Restore or
discard only the synthetic stock change after collecting evidence. n8n
reports what OpsFlow returned and applies no inventory rule itself.

### Scheduled Odoo recovery

Use a separate approved synthetic order. Immediately before one scheduled
execution, stop only the disposable Odoo application service; do not alter
credentials or M9B retry configuration. Verify n8n makes one call, Python
classifies the provider failure, M9B stores its existing bounded retry state,
and the workflow exits with the bounded outcome. Restore Odoo. The next
scheduled run calls the same endpoint; if M9B says the retry is not yet due,
n8n records `no_work` and exits. Wait for a later normal tick until M9B claims
the due work and resumes it. Inspect durable state to show n8n stored no
recovery state. Do not add a loop, immediate retry, or demo-only retry policy.

M9B/PostgreSQL tests and M9D's coordinator tests separately prove recovery
from durable partial Company/Deal receipts. M9E does not add production fault
injection. A later scheduled invocation always re-enters the same API and
M9B selects the first missing durable step.

## Literal clean-clone acceptance

The final rehearsal must use a literal second Git clone of the committed M9E
candidate, not another Compose project pointed at the original working tree.
Record the exact candidate SHA and clone path. From the source repository,
after the M9E candidate has been committed and pushed:

```sh
git clone https://github.com/Joseph-Nawar/OpsFlow_AI.git OpsFlow_AI_m9e_clean
git -C OpsFlow_AI_m9e_clean checkout <exact-m9e-candidate-sha>
git -C OpsFlow_AI_m9e_clean status --short
git -C OpsFlow_AI_m9e_clean rev-parse HEAD
```

The status must be empty before setup and HEAD must equal the recorded
candidate SHA. Do not copy `.env`, ignored/untracked files, scripts, local
volumes, Odoo addons, n8n state, Python/frontend caches, or other runtime data
from the first checkout. Supply only required external sandbox credentials
manually in the new clone's ignored `.env`; use fresh project name
`opsflow-m9e-clean-<short-sha>` so Compose creates new OpsFlow/PostgreSQL and
n8n volumes/network. Create a fresh disposable Odoo database/container and
network alias as well. Use fresh temporary Python and npm cache directories
for the rehearsal. The old n8n volume must not be mounted. Ensure fixed local
ports are free; stopping prior Compose services without removing volumes is
safe if necessary.

Follow only this guide and the linked M9C/M9D sandbox guides. From this clean
checkout, demonstrate that a new developer can create `.env`, start and
migrate the stack, set up the two provider sandboxes, start fresh n8n, import
the workflow inactive, create/bind `OpsFlow Orchestration`, manually test,
publish it, observe its Schedule Trigger, prepare/approve a synthetic order,
and complete the cross-provider flow. Repeat approval-boundary, no-stock,
idempotency, and scheduled-recovery checks. If any step relies on hidden state,
ad-hoc files, or undocumented local setup, fix the documentation before
acceptance and rerun at a new committed candidate SHA.

## Cleanup and troubleshooting

Deactivate the workflow first. Archive/delete only the synthetic Odoo and
HubSpot records according to their provider guides. Stop/remove only the
named disposable Compose project and its volumes after the evidence is
captured; never remove a developer's primary database volume. Revoke or rotate
temporary credentials according to the provider guides. Do not include
credentials, raw provider bodies, private payloads, or execution data in the
evidence report.

- **`/ready` is unavailable:** check only the API process and its isolated
  PostgreSQL dependency. Optional provider configuration is not part of
  readiness.
- **Execute-next returns 401:** confirm the local `OpsFlow Orchestration`
  credential is bound to the HTTP node and corresponds to the API's local
  orchestration token. Do not put that token in workflow JSON or process env
  for n8n.
- **Execute-next returns 503:** inspect API provider composition/configuration
  and the documented Odoo/HubSpot gates. This is a bounded preclaim response;
  n8n should finish normally and make no provider call.
- **No n8n HTTP response:** check API reachability at `http://api:8000` from
  the Compose network, then inspect sanitized API/n8n logs. Do not enable
  node retries.
- **No eligible order:** inspect approval and durable M9B state through the
  existing review/read contracts. The workflow does not select a specific
  order.

M9E does not add a new endpoint, workflow engine, queue, worker, provider
logic in n8n, throughput loop, cloud deployment, or dashboard. M9F remains
outside scope.

## M12C-1 STATIC PREFLIGHT — ACCEPTED; NO PROVIDER RUN

This subsection records M12C-1 static inspection and its proposed operator plan.
The inspected source baseline was the M12B documentation closeout at
`93bef43c175c534b94537f40632188118bf0daee`; at that time the plan was to freeze
the later, human-reviewed M12C-1 documentation commit before either future
clone. M12C-1 was accepted at `7cf04966b7193d69ab1b04b91348c9e82ef33636`.
During M12C-1 no services were started, databases or provider accounts were
read or changed, credentials were inspected, workflows activated, provider
calls made, or media captured. M12C's approved end-to-end acceptance remains
unchanged. The separately authorized M12C-2 execution is recorded below. As
of this 2026-10-14 M12C-1 preflight, M12C-3 still needed its own authorization
and had not started; the later run is recorded below.

### Executable path and evidence map

| Stage | Existing entry point and prerequisites | Success evidence and observation | External effects, retry, or ambiguity |
| --- | --- | --- | --- |
| Gmail intake | Inactive [`opsflow-gmail-intake.json`](../../workflows/n8n/opsflow-gmail-intake.json): Gmail Trigger polls `label:OpsFlow/Intake` every minute, downloads attachments, and selects one supported PDF/XLSX/CSV; absent one, it converts visible email body text to `EMAIL_BODY`. It preserves Gmail message ID, `source_system=GMAIL`, and `gmail:<message_id>` idempotency key, then posts multipart data to authenticated `POST /v1/orchestration/intakes`. | Persisted source-document SHA-256, Gmail provenance/message ID, order and idempotency record; bounded API response; audit history. Use a dedicated empty intake label and one controlled synthetic message. | Gmail reads occur in the trigger; export does not establish the trigger's exact Gmail API request/retry count. Each workflow event can submit the same source through up to three API POSTs (initial plus two 503/transport retries), then one additional delayed backend-recovery POST when the response supplies a recovery hint: up to four POSTs per workflow execution. A poll restart or later re-emission is also possible. Do not count API idempotency as an at-most-one provider-call guarantee. |
| Document processing and extraction | `create_orchestration_intake_endpoint` → `execute_orchestration_intake` → `process_document` → `OrderExtractor.extract`. Supported canonical formats are EMAIL_BODY, PDF, XLSX, and CSV. Provider selection is in `build_orchestration_runtime`: no Gemini key selects a fixed `FakeProvider`; a configured key/model/timeout selects `GeminiProvider`; a configured-provider error does not fall back to FakeProvider. | Source hash/type, canonical processing result, persisted extraction snapshot, audit events, and visible provider-mode label in the run record. | The initial idempotency/order record and intake ownership claim precede extraction. An invocation can repeat after eligible human Retry or expired-lease recovery. A timeout can leave the provider outcome ambiguous. See the one-call decision below. |
| Deterministic validation | `validate_order` uses the configured trusted-data provider, policy, and current date. With Odoo unconfigured the local runtime uses the existing synthetic provider; with Odoo configured it reads trusted customer/product data from Odoo. | Persisted deterministic issues, validation snapshot, resulting NEEDS_REVIEW or READY_FOR_APPROVAL state, and audit/notification intent. | Odoo trusted-data reads are real provider reads when configured. They are separate from later sync reads. No LLM output authorizes validation or an external write. |
| Human review and approval | Review UI/API: reviewer reads the order, edits and Save & Revalidates; a separate APPROVER role issues `POST /v1/review/orders/{order_id}/approve`. Configure distinct local reviewer/approver credentials and the n8n-to-API orchestration token. | Review revision, fresh validation result, state transition, audit event, and approval-time Slack/Gmail notification intents. | Approval is an explicit human action. At approval the backend creates `ORDER_APPROVED` notifications; Gmail is eligible only with persisted Gmail provenance. Provider delivery is a separate outbox operation. |
| Odoo synchronization | Inactive [`opsflow-order-sync.json`](../../workflows/n8n/opsflow-order-sync.json) schedules one authenticated `POST /v1/orchestration/order-sync/execute-next` every five minutes. Python's `Phase9OrderSyncExecutor` runs Odoo lookup and the idempotent sale-order bridge. API credentials/configuration are supplied only to the API. | Durable Odoo sale-order receipt on the OpsFlow sync row, plus matching synthetic order in the dedicated disposable Odoo database. | Validation and sync include Odoo reads; bridge creates/reconciles one logical sale order. The adapter uses bounded HTTP requests without a configured HTTPX retry transport. M9B allows at most three automatic failed sync attempts per retry generation, with delays; human Retry resets a generation and is not included in this proposal. A lost write acknowledgement can cause a later idempotent reconciliation call. |
| HubSpot synchronization and completion | The same Python executor calls the HubSpot Company, Deal, and association steps only after preceding receipts. The HubSpot adapter checks the configured portal identity, upserts Company by trusted customer reference, creates/reconciles Deal by OpsFlow order UUID, then writes and verifies the association. | Durable Company, Deal, and association receipts; provider records checked against the same synthetic identity; `COMPLETED` state and one persisted `ORDER_SYNC_COMPLETED` audit event. | One happy path is one Company upsert, one Deal identity search plus create (or a reconciliation update/read), and one association write/read, with portal checks. These are bounded code paths, but M9B retries can repeat a failed step. Uncertain writes must be reconciled before any fresh authorization. |
| Post-sync notifications | The atomic completion transaction creates independent Slack and eligible Gmail `ORDER_SYNC_COMPLETED` intents referencing that same audit event. Inactive [`opsflow-notification-dispatch.json`](../../workflows/n8n/opsflow-notification-dispatch.json) claims one intent per minute, uses channel-specific Gmail/Slack nodes, and reports outcome through the authenticated API. | Outbox intent/audit-event identity, durable attempt/outcome record, actual provider acknowledgement and timestamp. Both completion channels are mandatory for full-demo PASS; their delivery order is not a correctness condition. | Existing approval-time notification intents remain separate. Each intent permits up to three durable delivery attempts; lost acknowledgements can produce a duplicate external send (at-least-once). Node-level retry-on-fail is disabled in the export, but the provider node libraries' wire-level internal retry details were not verified here. |
| Exact-source replay | After successful completion only, resubmit the privately retained exact submitted document bytes directly to the authenticated intake API with the original Gmail message ID, source_system, and Idempotency-Key. Do not use Gmail Trigger or fetch the source again. | `idempotent_replay=true`, same order identity and COMPLETED state, unchanged receipt/event/intent counts, and no new provider operation. Retain the submitted-byte SHA-256 for comparison. | A completed terminal order stands down from extraction. Replaying before completion, after a retryable failure, or with changed bytes can enter recovery or conflict; stop instead of replaying in those states. |

The current notification contract is implemented: approval-time notifications
are distinct from post-sync completion intents, and the latter are created only
after all required durable Odoo/HubSpot receipts. Historical Phase 8/9 test
results are supporting code evidence only; they are not a newly observed live
run. The frozen Phase 11 provider-free corpus 3.0.0 result (36/36 cases and all
five gates passing, zero Gemini calls, extraction quality NOT_APPLICABLE) is
correctness/safety evidence only. It is not Gemini accuracy or live-provider
evidence. The post-M12B compatibility evaluation is separate audit evidence,
not a replacement for the frozen reference. `NO_OPTIMIZATION` remains
unchanged.

### Gemini one-call feasibility

**Decision: NOT YET SAFE for an at-most-one actual Gemini invocation.** One
`GeminiProvider.generate_structured()` call issues one Interactions request and
the pinned SDK retry count is set to zero. That limits retries inside that one
invocation; it does not fence repeated application invocations for one source.
The application persists the order/idempotency identity and processing claim
before extraction, but an eligible human Retry can resume processing or
extraction, and a stale processing/extracted lease can be recovered after its
210-second ownership lease. The HTTP intake operation also has bounded
same-key resubmission/recovery paths. A provider timeout or lost acknowledgement
does not prove that the request was not accepted. A repeated extraction after
one of those paths can therefore make a second actual request. The existing
idempotency key is a logical source/order identity, not a Gemini provider
idempotency key.

There is no automatic Gemini-to-Fake fallback on a configured Gemini failure,
but leaving the Gemini key absent intentionally selects the fixed FakeProvider.
Before any separately authorized Gemini run, the operator would need to verify
the mode without printing the secret and fail closed if credentials/model are
unavailable. On timeout or ambiguous result: stop intake, deactivate the
workflow, treat the authorized call budget as consumed, and do not fall back,
retry, recover, replay, or make another call without fresh explicit approval.

The smallest additional control for a one-call promise is a durable,
source-generation-specific single-use invocation reservation/fence committed
before dispatch, with an ambiguous/dispatched reservation never reopened by
HTTP redelivery, lease recovery, or human Retry. This requires a separately
approved implementation and review; it is not part of this preflight. Until
then, use the scripted provider and label it exactly as scripted rehearsal, or
leave the Gemini demonstration out. If a later one-call path is authorized, it
must specify the model, maximum one provider invocation, and a human-approved
currency spend ceiling. The 36-case live Gemini evaluation remains
unauthorized; Gemini quality, aggregate latency, authoritative token totals,
and measured model cost remain unavailable.

### Proposed synthetic purchase order

Use a controlled synthetic sender and a dedicated intake mailbox. Set the
subject to `[OpsFlow Demo] Synthetic purchase order` and send one plain-text
email with no attachment, so the workflow constructs an `EMAIL_BODY` document
from the body and avoids ambiguous attachment selection. Generate the two date
values for the execution day; retain the exact UTF-8 document bytes that n8n
submits and their SHA-256 outside Git.

```text
SYNTHETIC TRAINING ORDER — no real customer, payment, shipment, or fulfillment.
Customer: Acme Industries
Customer reference: CUST-001
Purchase order: PO-SYNTHETIC
Order date: <demo execution date, YYYY-MM-DD>
Requested delivery date: <seven days after order date, YYYY-MM-DD>
Currency: USD
Line 1: SKU-001 — Widget
Quantity: 1
Unit price: USD 10.00
Line total: USD 10.00
Order total: USD 10.00
```

This matches the fixed local FakeProvider's customer, PO, SKU, quantity, and
price fields and the existing synthetic Odoo seed recipe; the FakeProvider
ignores the submitted text and emits its fixed 2025 dates. With the current
date those dates deterministically produce `DELIVERY_DATE_IN_PAST`; a reviewer
can correct both dates from the synthetic email and Save & Revalidate before a
separate approval. Explicitly disclose that this is a scripted payload, not
extraction accuracy. If Gemini is separately authorized, its output and
validation route are not predictable; still require human review/approval and
do not depend on a warning being generated. The Odoo `CUST-001` / `SKU-001`
records and the HubSpot Company identity must be positively checked in the
selected disposable sandboxes later; this document does not assert they exist.
If those identities conflict, stop rather than changing business policy or
overwriting an unrelated record.

### Provider-operation authorization matrix

All ceilings below are proposals for a later, separate authorization; current
authorized live operations are **zero**. Provider identities/credentials were
not read or verified during M12C-1. Exact low-level calls may depend on provider
node libraries, so the stated n8n node-attempt limits are not proof of a
wire-level retry bound.

| Provider and target to verify later | Expected operation categories and normal-path count | Maximum possible attempts from inspected controls | Cost/authorization ceiling proposal | Evidence and stop/reconcile rule |
| --- | --- | --- | --- | --- |
| Gmail: dedicated intake mailbox plus a controlled synthetic sender; both identities must be verified later | Read one labeled synthetic message. Send two logical replies in the scripted path: one existing approval-time reply and one post-sync completion reply, both to original sender/thread. No cleanup/delete by default. | Gmail Trigger polls every minute; its export does not establish exact API request/retry counts, so provider-read maximum is presently unknown. Each Gmail notification intent has at most three durable dispatcher attempts: 2 intents × 3 = 6 Gmail node executions. Ambiguous acknowledgement can duplicate a reply; node library wire retries are not established. | Later authorization should cap one synthetic intake message and at most 6 logical Gmail send-node executions, contingent on resolving the trigger/node retry bound. No charge is assumed; quota/plan use is possible. Cleanup is zero unless separately authorized for exact message IDs. | Persisted Gmail source provenance, message/thread routing, separate approval and completion intents, actual acknowledgements/timestamps. On extra labeled mail, unknown retry, unexpected recipient, or ambiguous send: deactivate relevant workflow and reconcile before a new authorization. |
| Gemini: one named model and app configuration | Optional single structured-extraction request; not required by the baseline full-demo contract if mode is truthfully identified. No account reads or writes. | `GeminiProvider` makes one request per invocation with SDK retries disabled, but repeat application invocations via lease recovery/Retry/redelivery mean no finite at-most-one provider-call ceiling exists today. **Not authorizable as one-call under current controls.** | Current ceiling 0. If the source-generation fence is separately implemented/reviewed, propose at most 1 invocation, with the model and explicit owner-set maximum spend in currency supplied before any call. No live 36-case evaluation. | Qualitative-only sample response with provider mode identified. Ambiguous timeout consumes any approved budget; no fallback or second call. |
| Slack: dedicated test workspace and one synthetic destination channel | Send four logical events in the scripted review path: REVIEW_REQUIRED, APPROVAL_READY after correction, ORDER_APPROVED, ORDER_SYNC_COMPLETED. No account reads or cleanup by default. | At most 3 durable attempts per intent = 12 Slack send-node executions. Provider-client internal wire retries are not established; lost acknowledgement can lead to a duplicate on later retry. | Later authorization should cap the four named event kinds / 12 send-node executions. No per-message fee is assumed; workspace quota/plan exposure remains possible. No channel/account identifiers in Git. | Intent/event identity, backend outcome, provider acknowledgement reference/time; completion must reference completed sync audit. Stop and reconcile on missing/ambiguous outcome before manually resending. |
| Odoo: dedicated disposable Community database, company/warehouse/pricelist and synthetic records; exact target not yet supplied/verified | Happy path with one customer and one SKU: two validation/revalidation lookups, sync preflight, bridge identity lookup + fresh lookup + create-or-get, and trusted-customer lookup during HubSpot Company upsert. This is 36 Odoo JSON-2 requests (35 reads, one bridge operation) and one logical sale order. Missing synthetic trusted-record setup writes require separate authorization. | M9B allows at most three automatic failed sync attempts per retry generation; the failing checkpoint can repeat its multi-request group. HTTPX has no retry transport configured. Intake validation reads can also repeat after recovery or human Retry, outside the sync counter; do not manually retry. A human sync Retry starts another generation and is excluded from this ceiling. The idempotent bridge can be called again after uncertain acknowledgement. | Later authorization should name the exact disposable database and permit only the required read operations plus one stable-UUID sale-order create/reconcile path, with no setup/cleanup writes unless separately approved. Cap one automatic sync generation at three attempts. No paid service is assumed; quotas/hosting costs may apply. | Read target identity first after authorization; verify company/SKU/stock and expected stable identity. Require durable Odoo receipt and exact record. On any unknown target, conflict, or ambiguous create, stop and reconcile by stable order UUID. |
| HubSpot: dedicated developer-test portal with expected portal identity, pipeline/stage and approved properties | Happy path is eight API requests: one portal check + Company upsert; one portal check + Deal identity search + create; one portal check + association write + association read. This creates/reconciles one Company, one Deal, and their association. No schema setup or cleanup in demo transaction. | One Company step includes portal check + upsert. Deal includes portal check + search + create/reconcile. Association includes portal check + write + read. M9B allows at most three automatic failed sync attempts per retry generation; no HTTPX retry transport is configured. | Later authorization should name the developer-test portal and allow only the synthetic Company identity, one order-UUID Deal, and their association, up to one three-attempt sync generation. Schema/setup, archive/delete, and key revocation require separate explicit authorization. Quota/plan limits may apply. | Durable Company/Deal/association receipts and read-back of expected synthetic identity. Stop on portal mismatch, existing conflicting identity, unclear association, or ambiguous write until reconciled read-only under authorization. |
| n8n/provider workflows: one newly named local project/volume and only the three tracked workflows | Local control/API calls are not external provider operations. Gmail intake, order-sync, and notification-dispatch exports are all inactive. Order-sync makes one API call per five-minute tick; notification dispatch claims one intent per minute; Gmail intake polls once per minute when activated. | Intake can submit one source through up to three explicit HTTP attempts plus one backend-recovery POST, at most four API POSTs per workflow event; order-sync n8n HTTP node has retry disabled while Python owns at most three automatic sync failures per generation; dispatch claims one notification and has node retry disabled while the outbox allows at most three attempts. Provider trigger/node internal retries are unresolved as noted above. | No additional live operations beyond individually authorized rows. Import workflows inactive; do not activate any unrelated schedule. Use a fresh n8n volume so old credentials/executions cannot run. | Before dispatch, require a fresh DB and an exact expected notification roster; any unrelated/pending intent or active unknown workflow means stop. Deactivate the relevant workflow after the one-order run and preserve only sanitized evidence. |

Setup writes, cleanup/deletion, archive operations, and credential revocation are
**zero-authorized by default**. Each later operation needs its own target,
purpose, count/retry bound, and explicit human authorization. Do not perform
provider reads to verify any identity before that authorization.

### Proposed M12C execution sequence

This sequence was drafted during M12C-1. M12C-2 used the accepted candidate SHA
`7cf04966b7193d69ab1b04b91348c9e82ef33636`; M12C-3 requires its own fresh,
approved candidate and separate authorization. Any later code/config change
requires review before live activity. A second clone provides no additional
external-operation or provider-call budget.

**M12C-2 — planned local reproducibility and provider-free rehearsal (recorded
before execution; actual result follows below):**

1. Make a literal clean clone of the frozen SHA. Choose a unique local
   Compose project name and set it as the local `PROJECT` variable. Proposed
   read-only checks for pre-existing containers/volumes are:

   ```sh
   docker compose -p "$PROJECT" ps --all
   docker volume ls --filter "label=com.docker.compose.project=$PROJECT"
   ```

   Use fresh PostgreSQL/n8n volumes; do not reuse another project's volume
   or local `.env`. Use the guarded `.env` creation above. Start only PostgreSQL with the documented
   `docker compose -p ... up --wait postgres` command, verify that project owns
   the healthy service/volume and loopback port, then run the README's
   read-only migration-target verifier. Apply migrations only after those
   checks pass; verify Alembic head `0008_phase12_completion_notifications`
   and local `/ready`. Follow the pinned Python/Node/Compose prerequisites in
   the README.
2. Configure a random local orchestration token and distinct local reviewer
   and approver credentials. Do not configure provider credentials. Import
   the tracked n8n workflows inactive, bind only the local OpsFlow bearer
   credential, run the existing `npm --prefix web ci` and
   `npm --prefix web run dev` commands for the review UI, and verify execution
   data retention remains disabled.
3. A proposed provider-free rehearsal may post the synthetic body directly to
   the local intake API with a unique local idempotency key and no Gmail
   `source_system`; this does not exercise Gmail or prove a live Gmail source.
   Use FakeProvider, inspect the review warning, correct dates, Save &
   Revalidate, then approve under the separate local role. Keep the Gmail,
   Slack, order-sync, and notification provider workflows inactive. Local
   intents can be inspected, but not sent.
4. With Odoo/HubSpot unconfigured, execute-next is expected to return a bounded
   preclaim 503. This current runtime has no full provider-free business-sync
   demo mode, so M12C-2 cannot prove COMPLETED, live notifications, or the full
   cross-provider flow. Do not substitute provider-free tests or historical
   M9E evidence for M12C-3.
5. Stop only this project's services while preserving its named volume unless
   later cleanup authorization explicitly identifies that exact project and
   volume. Do not call `down -v` on an unknown or shared project.

### M12C-2 execution record — 2026-10-14

**Result: provider-free local rehearsal executed; independent review pending.**
Phase 12 remains IN PROGRESS. M12C-3 and all live-provider operations remain
NOT STARTED and unauthorized. The run used candidate SHA
`7cf04966b7193d69ab1b04b91348c9e82ef33636` in a literal clone at
`/tmp/opsflow-m12c2.BtXcjT19/repo`; the clone was detached at that SHA, had a
clean tracked tree, and had no copied `.env`. Private local observations and the
exact synthetic source are retained outside Git under
`/tmp/opsflow-m12c2.BtXcjT19/evidence/`; credentials and raw runtime data are
not part of this repository.

The observed toolchain was Python 3.12.15, uv 0.12.22, Node 24.21.0, npm
11.19.0, Docker 29.7.2, Compose 5.4.0, PostgreSQL image 16, and n8n 2.40.5.
The unique Compose project was `opsflow-m12c2-20261014-90ec21`; its new named
volumes were `opsflow-m12c2-20261014-90ec21_postgres-data` and
`opsflow-m12c2-20261014-90ec21_n8n-data`. Before startup, no container or
volume carried that project label and loopback ports 5432, 8000, 5173, and 5678
were free. No unrelated container was running. The two volumes remain
preserved; no `down -v` or volume deletion was used.

Commands executed in the clone included:

```sh
git clone --no-local --no-checkout https://github.com/Joseph-Nawar/OpsFlow_AI.git /tmp/opsflow-m12c2.BtXcjT19/repo
git -C /tmp/opsflow-m12c2.BtXcjT19/repo checkout --detach 7cf04966b7193d69ab1b04b91348c9e82ef33636
uv sync --frozen --dev
npm --prefix web ci
docker compose -p opsflow-m12c2-20261014-90ec21 config --quiet
docker compose -p opsflow-m12c2-20261014-90ec21 up --wait postgres
make migrate
uv run alembic current
docker compose -p opsflow-m12c2-20261014-90ec21 up --wait api n8n
npm --prefix web run dev -- --host 127.0.0.1
```

The three workflow imports used the tracked exports and the n8n CLI's default
inactive behavior:

```sh
docker compose -p opsflow-m12c2-20261014-90ec21 cp workflows/n8n/opsflow-gmail-intake.json n8n:/tmp/opsflow-gmail-intake.json
docker compose -p opsflow-m12c2-20261014-90ec21 cp workflows/n8n/opsflow-order-sync.json n8n:/tmp/opsflow-order-sync.json
docker compose -p opsflow-m12c2-20261014-90ec21 cp workflows/n8n/opsflow-notification-dispatch.json n8n:/tmp/opsflow-notification-dispatch.json
docker compose -p opsflow-m12c2-20261014-90ec21 exec -T n8n n8n import:workflow --input=/tmp/opsflow-gmail-intake.json
docker compose -p opsflow-m12c2-20261014-90ec21 exec -T n8n n8n import:workflow --input=/tmp/opsflow-order-sync.json
docker compose -p opsflow-m12c2-20261014-90ec21 exec -T n8n n8n import:workflow --input=/tmp/opsflow-notification-dispatch.json
```

The local app operations were authenticated API calls: multipart `POST
/v1/orchestration/intakes` with `document_type=EMAIL_BODY`; reviewer `GET
/v1/review/orders/{order_id}` and `GET
/v1/review/orders/{order_id}/reference-data`; reviewer `PUT
/v1/review/orders/{order_id}/draft` with its current strong `If-Match`; a
separate approver `GET` and `POST /v1/review/orders/{order_id}/approve` with
the approver's strong `If-Match`; and `GET /v1/orders/{order_id}/audit`. The
order-sync preclaim used authenticated `POST
/v1/orchestration/order-sync/execute-next`. Replay repeated the intake POST
with the same local key and exact bytes. Tokens were read from the ignored
local `.env` only by the private client script and are not recorded here. The
intake request was sent directly by that local client; although the persisted
audit actor is `orchestration:n8n` under the existing auth contract, this was
not an n8n workflow execution.

The fresh `.env` was created only after confirming no file or symlink existed,
using `.env.example` as its basis. New random orchestration, reviewer, approver,
and n8n local values were generated in the clone; the file was mode 0600 and
`git check-ignore` confirmed it is ignored. Its effective host migration target
was verified without printing a password as
`postgresql+asyncpg / localhost / 5432 / opsflow / opsflow`. A connection through
the host-published loopback port returned database `opsflow`, user `opsflow`,
server port 5432, and zero public tables before migration. Compose labels
confirmed that the healthy container and new volume belong to the unique
project. `make migrate` succeeded and `uv run alembic current` returned
`0008_phase12_completion_notifications (head)`. The API container connects to
its same-project PostgreSQL service over the isolated Compose network.

Runtime checks established that Gemini was disabled and the fixed
`FakeProvider` was selected; Odoo and HubSpot settings and adapters were absent,
and `order_sync_step_executor` was `None`. Reviewer and approver had distinct
generated local credentials and actors. The API `/ready`, Vite root, and n8n
`/healthz` returned HTTP 200. The three tracked Gmail intake, order-sync, and
notification-dispatch workflows imported through n8n's CLI with its default
inactive import behavior. Export-back verified `active=false` and disabled
successful, error, and manual execution-data retention for each. Their named
credential references remained unbound; n8n's credential export reported
“No credentials found.” No workflow was activated or executed. The local API
bearer was used directly for local API requests, not installed as an n8n
credential.

One 392-byte synthetic `EMAIL_BODY` was submitted directly to the local
authenticated intake API with idempotency key prefix `m12c2-local:`. The API's
source contract accepts `GMAIL` or an omitted `source_system`; it does not
accept a fabricated `LOCAL` provider value. Accordingly, this request omitted
both `source_system` and `message_id`; it has no Gmail provenance. The retained
synthetic source SHA-256 is
`9e8e213f0c44fe71046ab20b5f0cf6962305ffac032a30188df8b90d93078fcc`.
This was direct local API intake, not Gmail receipt or n8n intake.

The local API returned `NEEDS_REVIEW`. The persisted draft came from the fixed
FakeProvider, which ignores source content and emitted its scripted
`2025-01-01` / `2025-01-08` dates; those values are not extraction-accuracy
evidence. The actual deterministic validator reported
`DELIVERY_DATE_IN_PAST` against the rehearsal date, 2026-10-14. The reviewer
`local-m12c2-reviewer` read the detail/reference-data API and used Save &
Revalidate to correct the dates to 2026-10-14 / 2026-10-21. The trusted local
catalog returned active Acme Industries / `CUST-001` and active Widget /
`SKU-001`, USD 10.00, available quantity 100. Revalidation returned
`READY_FOR_APPROVAL` with zero validation issues. A separate authenticated
`APPROVER`, `local-m12c2-approver`, then approved the order through the normal
approval API. Persisted audit history has ten events through `ORDER_APPROVED`;
one order, one source document, one extraction snapshot, and one idempotency
record remained.

The order has three pending Slack approval/review notification intents
(`REVIEW_REQUIRED`, `APPROVAL_READY`, and `ORDER_APPROVED`), each at attempt
count zero. It has no Gmail intent because it has no Gmail source provenance,
and no completion intent because no ERP/CRM synchronization occurred. No
notification was claimed or delivered. With both external adapters absent,
the authenticated order-sync endpoint returned its safe preclaim HTTP 503; the
order remained `APPROVED` and no receipts or completion event were created.

The same retained bytes and local idempotency key were replayed after approval.
The local API returned HTTP 200, `idempotent_replay=true`, the same order ID,
and state `APPROVED`. Before/after observations were identical: one order,
source, extraction snapshot, and idempotency record; ten audit events; three
pending notification intents with zero attempts. This confirms local
idempotency and no repeated extraction for this approved non-Gmail source. It
is not the required post-completion exact Gmail-source replay and does not
prove Gmail, Gemini, Slack, Odoo, or HubSpot behavior.

| M12C-2 local acceptance check | Result |
| --- | --- |
| Literal clean clone, fresh isolated Compose project/volumes, safe DB target, migration head | PASS |
| API/frontend readiness and inactive workflow import/retention configuration | PASS |
| Fixed FakeProvider, local source processing, deterministic review, separate correction and approval | PASS |
| Persisted audit, source, snapshot, idempotency, and pending notification intent evidence | PASS |
| Adapter-free order-sync preclaim and exact local-source replay without duplicate extraction | PASS |
| Gmail receipt, live Gemini extraction, Slack delivery, Odoo/HubSpot sync, post-sync sends, Gmail-source replay | NOT EXERCISED; requires separately authorized M12C-3 |
| Screenshots/video | NOT CAPTURED; reserved for the authorized full run and M12E |

The rehearsal used no live-provider credentials or calls, sent no message,
mutated no provider account, and captured no media. No application tests were
run. `npm ci` reported two high-severity frontend dependency-tree advisories
and an `fsevents` install-script warning; this install did not modify tracked
dependencies. The live Gemini single-invocation bound remains NOT YET SAFE under
the existing retry/recovery paths. M12C-3 still requires separately supplied
and verified sandbox targets, credentials, operation/retry ceilings, and
authorization; it must not be replaced by this local rehearsal or run in this
clone without fresh approval.

**Historical M12C-3 proposal — written before authorization and execution:**

1. Obtain separate explicit authorization for provider, exact target by type,
   operation categories, maximum attempts, and spend ceiling where applicable.
   Only then verify account identity and synthetic-record conflicts. No target
   or credential is verified in this preflight. If Gmail's trigger read bound
   or Gemini's single-invocation requirement remains unresolved, do not enable
   that operation.
2. Use a separate fresh clean clone at the same frozen SHA and new named
   Compose volumes; do not repeat the run in M12C-2's clone. Verify DB identity
   and migration head. Configure local operator roles. Keep only the three
   required workflows imported and inactive. Store Gmail/Slack credentials in
   n8n and Odoo/HubSpot/Gemini configuration only in the API runtime; never in
   Git. Verify no unrelated pending outbox intents exist.
3. Ensure only the controlled source message has the intake label; activate
   Gmail intake for one bounded poll window and deactivate it immediately
   after the one synthetic source is accepted. Record the actual source ID
   privately and the exact submitted document bytes/hash. Show provider mode.
   If any unexpected source appears, stop.
4. Review and revalidate as a REVIEWER, then separately approve as APPROVER.
   Observe the approval audit/intents and actual approval-time notification
   outcomes under the approved Gmail/Slack ceilings. Confirm the outbox contains
   only the expected intents for this synthetic run; unrelated work blocks the
   dispatcher. Do not delay or gate order sync on approval-notification
   delivery; record actual outcomes independently.
5. Activate the order-sync workflow for this one eligible order. Observe
   Odoo, HubSpot and durable receipts, then the shared completion audit event
   and `COMPLETED` state. Deactivate the order-sync workflow after completion.
   If an adapter result is failed, stale, or ambiguous, stop and reconcile; do
   not invoke human Retry without new authorization.
6. Verify exactly the eligible post-sync Gmail and Slack completion intents
   reference the completion event, then enable the notification dispatcher
   under its named ceiling. Record actual outcomes and timestamps for both;
   both must succeed for full-demo PASS. Their relative delivery order is not
   a correctness invariant. On any ambiguous acknowledgement, deactivate the
   dispatcher and reconcile before further attempts.
7. After completion and both notification outcomes, replay the exact retained
   submitted bytes directly to the same intake endpoint with the original
   Gmail message ID, `source_system=GMAIL`, and `gmail:<message_id>` key. Do
   not fetch Gmail, activate intake, run extraction again, or repeat external
   reads/writes/sends. Compare replay result, order count, stable ERP/CRM
   identities, receipts, audit identity, intent counts, and provider operation
   counts. Any change or unexpected provider call is a failed replay gate.
8. Deactivate all relevant workflows. Preserve provider records and credentials
   unless exact cleanup/archive/revocation actions and targets receive their
   own approval. Clean local named volumes only under separate explicit
   authorization after confirming project ownership.

No manual workaround may be described as automated end-to-end behavior.
Historical integration tests and provider-free rehearsal are not live-provider
evidence. Missing either actual completion delivery fails the roadmap's full
demo criterion; a failed or incomplete run remains a reported failure rather
than a staged success.

### Evidence and media checklist for the one future run

Capture only if the operator separately approves recording during M12C-3; this
preflight grants no capture permission. Coordinate M12C evidence with M12E so
the transaction is not repeated for footage. M12E's planned public deliverable
is a readable, edited 90–120 second overview with sanitized screenshots.

- Private run record: frozen candidate SHA; local runtime versions; fresh
  Compose project/volume names; migration head; provider mode; privately
  retained synthetic source bytes and SHA-256; local audit/order/receipt and
  outbox counts; actual provider operation counts, outcome codes, and times;
  replay response and before/after counts; stop/reconciliation/cleanup status.
- Capture the Gmail synthetic message and intake outcome without mailbox
  address, message/thread ID, account profile, unrelated inbox items, or full
  private headers. Show the normalized synthetic body and the explicit
  “synthetic” label.
- Capture canonical processing/extraction and deterministic validation with
  provider mode visibly labeled; show the review issue, reviewer correction
  and revalidation, and distinct approval action without exposing tokens.
- Capture Odoo sale-order evidence and HubSpot Company, Deal, association,
  and durable OpsFlow receipts using sanitized views. Then show COMPLETED,
  the completion audit/event linkage, and actual Gmail/Slack completion
  outcomes with timestamps but without provider account IDs or private URLs.
- Capture the exact-source replay response and unchanged logical order/receipt/
  intent counts; do not show credentials, private logs, raw execution data,
  sensitive URLs, real customer data, or unfiltered provider responses.
- Retain an unedited, inspectable run record privately where appropriate;
  public outputs must use only synthetic content and sanitized evidence. M12E
  must review source/asset licenses, captions, and storage/delivery choice.
  Do not put raw footage, credentials, or private run records in Git.

### Readiness blockers and authorization still required

- No provider target or credential has been read or verified; dedicated Gmail,
  Slack, disposable Odoo, and HubSpot test targets must be supplied/approved
  and verified only in a later authorized operation.
- The Gmail Trigger's provider-level read/retry ceiling is not established by
  its export. Confirm a bounded single-message polling procedure and node
  behavior before authorizing the read.
- At-most-one Gemini invocation is not enforceable with current intake
  recovery/retry controls. A separate design/implementation review is needed
  before any one-call promise; otherwise use and label scripted extraction.
- Historical synthetic sandbox guides do not prove that their accounts or
  records still exist or are safe targets.
- The existing HubSpot sandbox guide records a historical numeric portal
  identifier. It was not copied here or treated as a current target; M12E's
  public-privacy review should decide whether that existing identifier is
  suitable to retain. A current identity or conflicting
  `CUST-001`/`SKU-001` record is a hard stop, not a reason to overwrite it.
- At M12C-1 preflight closeout, M12C-2 runtime checks had not yet been
  performed. The separately authorized M12C-2 execution and its local-only
  results are recorded above. Provider-free rehearsal cannot prove completion
  because the app intentionally preclaim-blocks sync without both adapters.
- Actual post-sync Gmail and Slack delivery, Odoo/HubSpot mutations, case-study
  evidence, screenshots, and video remain unobserved. Any setup writes,
  cleanup, deletion/archive, or key revocation require separate exact-target
  authorization. The Phase 11 provider-free reference and `NO_OPTIMIZATION`
  are outside this M12C preflight and remain unchanged.

The M12C-1 preflight itself was not authority to start services, change local
databases/accounts, send a message, create a provider record, call Gemini,
capture media, or perform cleanup. M12C-2 was separately authorized and is
recorded above. This runbook does not authorize M12C-3 provider operations,
media capture, or cleanup; those still require separate human approval.

### Independent M12C-2 review and disposition — 2026-10-14

**Verdict: PASS — the local M12C-2 acceptance criteria are supported and are
eligible for human acceptance.** This does not mark M12C complete or authorize
M12C-3. M12C remains IN PROGRESS; M12C-3 and M12D–M12F remain NOT STARTED.

The independent review covered the full M12C-2 documentation change at
`14392b1b15ddb5e163eb20949bd04df388ea6eb5`, the preflight candidate
`7cf04966b7193d69ab1b04b91348c9e82ef33636`, the approved Phase 12 criteria,
and the relevant orchestration, provider-selection, review-authorization,
order-sync, Compose, and n8n workflow contracts. The committed M12C-2 change is
limited to this runbook and the roadmap. The original M12C-1 preflight remains
distinct from the later execution record above.

The temporary clone is detached at the candidate SHA with a clean tracked
tree. Its ignored `.env` exists with owner-only permissions and is not tracked;
credential values were not emitted. The retained UTF-8 synthetic source is
owner-only, and its SHA-256 and byte length match the private JSON run record.
The record itself was inspected only for selected sanitized fields; it was not
copied into Git. Read-only Docker metadata confirms the rehearsal project's
three containers are stopped and its two named volumes remain labeled to that
project. Their creation times align with the run. The execution report states
that the loopback migration target had zero public tables before migration;
the recorded target and Alembic head are
`0008_phase12_completion_notifications`. This review did not reconnect to
the stopped database. The Compose definition uses project-scoped PostgreSQL
and n8n volumes and loopback-published service ports.

The effective API configuration evidence shows Gemini, Odoo, and HubSpot
settings absent or empty. Source composition selects the fixed `FakeProvider`
when no Gemini key is configured; the order-sync executor is absent unless the
required adapters are configured, and the authenticated endpoint returns 503
before executing sync when that executor is absent. The private record reports
three imported workflows inactive, zero stored or bound provider credentials,
zero workflow executions, zero provider-operation counters, and zero
notification deliveries. These observations support that the application's
provider paths were disabled; no packet capture was made, so this is not a
claim about every possible outbound network request.

The retained evidence supports direct authenticated local API intake of one
synthetic `EMAIL_BODY`, with no Gmail source identity or message ID. The source
hash matches the persisted source. The initial state and
`DELIVERY_DATE_IN_PAST` issue, reviewer correction and revalidation to
`READY_FOR_APPROVAL`, and a separate approver's `APPROVED` transition agree
with the persisted audit summary. The scripted extraction is FakeProvider
output and supplies no AI-accuracy evidence. The order-sync preclaim returned
503 without receipts or completion. Exact-source replay returned an
idempotent response for the same order; the recorded state remains
`APPROVED`, with one source, one extraction snapshot, ten audit events, one
idempotency record, and three pending Slack intents at zero attempts. The
application claim path stands down for an approved order before document
processing. These local observations do not prove Gmail intake, provider
delivery, ERP/CRM completion, or the required post-completion Gmail-source
replay.

| Review finding | Severity and disposition |
| --- | --- |
| `README.md` line 13 still says “M12C–M12F have not started,” although the roadmap records M12C IN PROGRESS and M12C-1/M12C-2 progress. | **Low, non-blocking.** Correct the current-status wording during a separately authorized documentation update; README was outside this review's change scope. |
| The private JSON run record has a database-target `password` field. Its value was not emitted or copied; the file is outside Git with mode `0600`. | **Low, non-blocking.** Keep the evidence private and redact credential fields before any transfer. No credential value was found in the tracked M12C-2 diff. |

The following M12C-3 readiness blockers remain as recorded above: no verified
live sandbox targets; Gmail Trigger read/retry ceilings are unresolved;
provider notification wire-level retry behavior is not fully established;
the at-most-one Gemini invocation bound is not yet safe; no live
cross-provider transaction, completion delivery, or full-demo replay exists;
and no media has been captured. These do not retroactively block M12C-2.

Review checks were read-only. The 51 relative Markdown links and anchors in
the changed runbook and roadmap resolve; `git diff --check` passes. GitHub CI
run `38566991165` for this exact execution-record SHA completed successfully,
including its pinned Gitleaks v8.28.0 secret-scan job. No application tests,
services, migrations, database connections, local provider operations, or
media capture were performed for this review. The rehearsal's recorded
two-high-severity frontend development-tree advisories remain disclosed and
are not treated as production dependency findings.

This disposition is independent-review evidence only. Human acceptance of
M12C-2 remains pending; no M12C-3 activity is authorized by this review.

### M12C-2 human acceptance and M12C-3 static readiness decision — 2026-10-14

**M12C-2 is human-accepted.** M12C-1 static preflight was accepted at
`7cf04966b7193d69ab1b04b91348c9e82ef33636`. M12C-2 ran against that candidate;
its execution record is commit `14392b1b15ddb5e163eb20949bd04df388ea6eb5` and
its independent PASS review is commit
`4bb388fc2db930aa6810a78340f046b7b41292cb`. This section records the owner's
acceptance. M12A and M12B remain COMPLETE; Phase 12 and M12C remain IN PROGRESS;
M12C-3 and M12D–M12F remain NOT STARTED. This acceptance does not authorize
provider operations, another rehearsal, or media capture.

The two Low-severity review findings remain in the historical review table
above. The stale README status is corrected in this documentation closeout.
The M12C-2 private JSON run record contains a database-target field named
`password`; its value was not inspected here. Keep the record outside Git and
redact credential fields before any transfer. Do not publish the private run
record. The frozen [Phase 11 provider-free reference](../evaluation/reference/phase-11-provider-free-baseline.md)
and the separate post-M12B compatibility evaluation remain distinct and
unchanged; neither establishes live Gemini quality or replaces the Phase 11
reference.

#### Gemini one-invocation decision

**Recommendation: Option A, no live Gemini call for the M12C-3 run.** The
approved full-demo criterion requires the real application extraction stage
and truthful provider-mode evidence; it does not require Gemini accuracy
evidence. Use the fixed provider only if it is selected and labeled as scripted
FakeProvider output. This preserves a faithful full Gmail/ERP/CRM/notification
demonstration without a model charge or a change to normal retry behavior.

| Option | Correctness and failure handling | Persistence, retry impact, tests, and scope |
| --- | --- | --- |
| **A — No live Gemini** | No paid or ambiguous model request. Show the real application stage with the actual mode identified; scripted output is not extraction-accuracy evidence. | No schema or code change; normal human Retry and stale-lease recovery stay unchanged. Verify the local mode label and zero Gemini calls in the rehearsal. The full external sandbox transaction can still be demonstrated. |
| **B — Durable single-use reservation** | Add a unique, durable reservation for the explicitly authorized source-document ID and byte hash. Commit it only after verifying the current intake ownership claim and immediately before the provider call. Make the call outside the database transaction. Once reserved, HTTP redelivery, lease recovery, human Retry, and exact-source replay must stand down. Timeout, crash, malformed response, or lost acknowledgement consumes the reservation; never fall back or call again. A crash after reservation but before sending means zero calls and a consumed reservation. This bounds one application-initiated request, not what Gemini may have processed after an ambiguous acknowledgement. | Requires a forward migration and an opt-in, source-scoped orchestration guard; do not apply it to ordinary orders or weaken their retry policy. Test PostgreSQL atomic reservation, competing workers, crash points, expired leases, HTTP retries, Human Retry, replay, and timeout/ambiguous response. Reconfirm the pinned SDK/transport path. It remains a separately authorized implementation and review. |
| **C — Existing controls only** | No existing control proves the bound. `google-genai` is pinned to 2.24.0 and the adapter configures zero SDK retries, but application re-entry can invoke the provider again. Intake idempotency identifies the order/source; it is not a provider invocation reservation. | No database change, but inadequate acceptance evidence. A characterization test could demonstrate re-entry through lease recovery or human Retry; it cannot establish the required bound. Disabling SDK or n8n retries alone does not address these paths. |

The existing seams are `create_order_with_disposition()` and
`claim_intake_execution()` in `src/opsflow/application/orchestration.py` /
`src/opsflow/orchestration/claims.py`, followed by the external
`OrderExtractor.extract()` call in `src/opsflow/application/orchestration.py`.
The source and claim are durable before that call, while extraction itself is
outside a transaction. An eligible human Retry or expired 210-second intake
lease can claim the same source again; a request timeout can be ambiguous.
The existing idempotency key and 180-second request budget therefore do not
prove one provider invocation. No Option B implementation is authorized here.
The 36-case live Gemini evaluation remains unauthorized; live quality,
aggregate latency, authoritative token totals, and model cost remain
unmeasured.

#### Pinned n8n execution and retry findings

The tracked workflows pin n8n `2.40.5`. Static comparison with the [pinned Gmail Trigger source](https://github.com/n8n-io/n8n/blob/n8n%402.40.5/packages/nodes-base/nodes/Google/Gmail/GmailTrigger.node.ts),
[Gmail request helper](https://github.com/n8n-io/n8n/blob/n8n%402.40.5/packages/nodes-base/nodes/Google/Gmail/GenericFunctions.ts),
[Gmail v2 node](https://github.com/n8n-io/n8n/blob/n8n%402.40.5/packages/nodes-base/nodes/Google/Gmail/v2/GmailV2.node.ts),
[Slack v2 node](https://github.com/n8n-io/n8n/blob/n8n%402.40.5/packages/nodes-base/nodes/Slack/V2/SlackV2.node.ts),
and [n8n authentication request helper](https://github.com/n8n-io/n8n/blob/n8n%402.40.5/packages/core/src/execution-engine/node-execution-context/utils/request-helpers/authentication.ts)
supports these boundaries:

- `opsflow-gmail-intake.json` polls every minute with
  `label:OpsFlow/Intake`, Gmail Trigger v1.4, and `simple=false`. It does not
  set `maxResults`; the pinned node defaults its per-poll delivery budget to
  10 messages. It paginates message listings, tracks cursor/boundary IDs, and
  can retry a failed message fetch on later polls up to ten times before
  dropping that fetch. Cursor and duplicate tracking reduce ordinary
  re-emission but do not create an at-most-once provider-call guarantee. One
  poll is not one Gmail request or necessarily one source. The exported node
  does not set `retryOnFail`; the workflow also has up to four same-source API
  submissions through its explicit retry/recovery branches. Those are local
  API POSTs; intake idempotency does not fence repeated extraction.
- The notification workflow runs every minute, claims one globally eligible
  outbox row, then uses Gmail 2.2 Reply or Slack 2.7 Message/Post. The tracked
  claim, send, and outcome nodes set `retryOnFail=false`. The pinned nodes call
  provider request helpers, however, and the exact physical resend ceiling
  through OAuth refresh and the underlying outbound transport was not proved
  from the tracked node flags. **Gmail and Slack wire-level retry ceiling:
  UNRESOLVED.** A backend intent can be claimed up to three times; an expired
  five-minute claim or a lost provider/outcome acknowledgement can lead to an
  at-least-once duplicate. A manual n8n execution retry could repeat a send
  and is not part of the authorized procedure.
- `opsflow-order-sync.json` schedules one backend `execute-next` API call every
  five minutes; M9B, not n8n, owns synchronization retries. The notification
  dispatcher is global rather than demo-order scoped. If any unrelated due
  intent exists, it may be claimed. A fresh isolated DB and a positively
  checked expected intent roster are required before enabling dispatch.

For a future controlled poll, an imported local instance may set
`maxResults=1`, use a dedicated mailbox/empty intake label with one controlled
synthetic message, and be deactivated immediately after acceptance. This
reduces message fanout but does **not** establish a strict physical Gmail read
ceiling: the list/fetch sequence, failed-fetch retry, OAuth refresh, poll
timing, and lower transport behavior still need a defensible bound. The
physical retry limits for Gmail replies and Slack sends are likewise
UNRESOLVED. Do not authorize those sends until the effective physical-attempt
ceiling or a separately reviewed bound is supplied.

#### Future operation authorization checklist

The earlier [provider-operation authorization matrix](#provider-operation-authorization-matrix)
remains the source for proposed targets, logical operation counts, and success
evidence. This static review refines the attempt limits; a normal-path count is
not a physical retry ceiling. No provider identity, credential, price, or
account quota was checked. Each read—including target identity and
existing-record conflict checks—requires explicit authorization before access.

| Provider / workflow | Current limit finding | Readiness |
| --- | --- | --- |
| **n8n and Gmail intake** | The pinned Gmail Trigger defaults to at most 10 message items per poll, can retry a failed fetch over later polls, and does not provide a one-source physical-request bound. One workflow item can also submit up to four local API POSTs. | **BLOCKED** until the operator has a dedicated one-source window and a defensible provider-request ceiling. API idempotency does not limit extraction invocations. |
| **Gmail replies** | The approval-time and completion intents allow up to six backend send-node executions total (three each); provider HTTP retries/ambiguous delivery remain unresolved. | **BLOCKED** until the physical attempt ceiling and exact mailbox/thread are approved. Reconcile an ambiguous send before any separately authorized retry. |
| **Gemini** | Option A proposes zero calls. Current lease recovery and Human Retry can invoke the provider again; no spend ceiling is established. | **BLOCKED / zero calls authorized.** Option B requires a durable source fence, verified one-request transport bound, and explicit owner-set spend ceiling. No live evaluation. |
| **Slack** | Four approval/review/completion intents allow up to twelve backend send-node executions; node retry is disabled, but physical transport retry and quota are unresolved. | **BLOCKED** pending physical attempt bound, exact workspace/channel approval, and any required spend ceiling. Reconcile an ambiguous acknowledgement before separately authorized retry. |
| **Odoo and HubSpot** | Happy-path estimates are 36 Odoo and 8 HubSpot requests. Each sync generation permits up to three automatic failed attempts; manual retry can start another generation, so the total physical maximum is not established. | **BLOCKED** pending exact disposable targets and numeric ceilings. On an ambiguous create, stop and reconcile the stable external identity before retry. No price or account-limit claim is made. |

All provider operations remain unauthorized. Before execution, the owner must
separately approve (1) provider identity and exact target verification; (2)
read-only conflict checks; (3) any synthetic setup writes; (4) one business
transaction and its maximum automatic sync attempts; (5) approval-time
Slack/Gmail sends as well as post-sync completion sends; (6) exact-source
replay only after confirmed completion; and (7) cleanup, archive/delete, and
credential revocation individually. The replay must deactivate Gmail intake
first, then submit the exact retained source bytes with the original Gmail
message identity and idempotency key to the local authenticated API after
confirming COMPLETED and all receipts. It must not fetch Gmail again or invoke
Gemini, Gmail, Slack, Odoo, or HubSpot. Replay before completion is a stop
condition. A second clone grants no extra provider-operation budget.

### M12C-3 transaction record and owner-approved limited-scope disposition — 2026-10-18

**Status:** The owner approved a limited-scope acceptance amendment on
2026-10-18. Independent review returned PASS against that amended scope with
zero Critical, High, or Medium findings, and the owner accepted M12C and
authorized documentation closeout on 2026-10-20. M12C is **COMPLETE under the
approved limited-scope amendment**. The M12C-3 run itself remains factually
**PARTIAL**: automated Gmail Trigger-to-OpsFlow intake is **NOT DEMONSTRATED**.
See the [sanitized independent review and human acceptance disposition](../audits/phase-12-m12c-review.md).
No second live transaction is authorized or needed.

**Source intake and failure history:** One approved synthetic email was sent
once to the dedicated sandbox mailbox. The real Gmail Trigger detected it and
attempted `POST /v1/orchestration/intakes`; OpsFlow returned HTTP 401. The
original failure record is preserved. The owner downloaded the same original
MIME message and the recovery used the tracked Gmail normalization/intake
path, original Gmail API message identity, Gmail provenance, and its
`gmail:<message_id>` idempotency identity. One authenticated recovery POST
returned HTTP 201 and created the intended single order and source document.
The body bytes from the failed 401 request were not retained; byte-for-byte
equality to that failed request is not claimed. This was owner-assisted
recovery, not uninterrupted automated Gmail intake. The accepted scope
explicitly leaves automated Gmail Trigger-to-OpsFlow intake
**NOT DEMONSTRATED** for this Phase 12 run.

**Processing and downstream results:** The application used its FakeProvider
path and scripted extraction output, not live Gemini inference or an accuracy
measurement. Deterministic validation ran; a distinct reviewer corrected the
synthetic order date to `2026-10-18` and requested delivery date to `2026-10-25`,
then saved and revalidated; a distinct approver approved the order.
Persisted evidence records one order reaching COMPLETED, one Odoo sale order
receipt, HubSpot receipts for reuse/upsert of the existing synthetic Company,
one Deal, and their association. Four Slack and two Gmail notification
intents reached DELIVERED. The two post-sync completion intents refer to the
same persisted `ORDER_SYNC_COMPLETED` event and follow durable Odoo/HubSpot
receipts; their actual delivery timestamps differ and no ordering claim is
made. Delivery remains at-least-once. Exact-source replay used the original
Gmail API message ID and recovered canonical document bytes; the authenticated
request returned HTTP 200 with `idempotent_replay=true` and unchanged logical
counts. The replay did not create another order, source, extraction, sync
row, audit event, notification, or completion intent. Private evidence retains
the actual provider references and timestamps; public documentation omits
private account and provider IDs.

**Evidence boundary:** The protected run record, original HTTP 401 record,
owner-assisted recovery evidence, database cross-check, durable provider
receipts/outcomes, and replay record were reviewed read-only. The supplied
12-image capture set and its sanitized derivatives are recorded in a private
inventory for independent review; every derivative is labeled POST-RUN
INSPECTION. The earlier `post-run-inspection-20261018/capture-index.json`
remains an accurate zero-capture record as of its 2026-10-18T13:41:11Z
timestamp and was not rewritten. The supplied images are later inspections,
not contemporaneous footage. Historical
Phase 8 evidence is separate: [`workflows/n8n/README.md`](../../workflows/n8n/README.md)
records M8C Gmail sandbox cases A–I and M8E primary and clean-clone live
Gmail intake through review/approval with Slack and original-thread approval
replies; the [Phase 8 audit](../audits/phase-8-audit.md) says M8F reused those
records and made no live provider sends. Phase 8 predates Phase 9 sync and
M12B post-sync completion notifications. It may be cited only with that scope
and cannot be combined with M12C-3 to claim end-to-end automated Gmail intake.

#### Original owner capture checklist — requirements retained for audit

This checklist predates the supplied captures. The owner has now supplied 12
raw images in a private `manual-captures-20261019` directory and separate
sanitized derivatives in a private review directory. The inventory records
source application, filename timestamp, raw and derivative hashes, claim
coverage, and redactions. The derivatives are visibly labeled POST-RUN
INSPECTION; none is treated as transaction footage. The requirements below
are retained as the original capture criteria, not as remaining capture tasks.

1. Create a new timestamped directory below
   `~/.local/share/opsflow-ai/m12c3/evidence/` named
   `post-run-inspection-<UTC timestamp>`. Set the directory to mode `0700` and
   each raw capture/manifest to `0600`. Save directly to that protected path;
   do not leave raw images on Desktop, in Downloads, or in the repository.
2. Use a non-secret capture index to record capture timestamp, candidate SHA
   `fc70d37fd004847fab0a4c42499e75afe1d6198b`, screen/source, and the label
   **POST-RUN INSPECTION — 2026-10-18 transaction**. Record a hash for each
   retained raw image. Keep the raw captures private and unedited.
3. Capture the current OpsFlow order view showing `COMPLETED` and its persisted
   history/review evidence for the distinct reviewer and approver. Show the
   scripted FakeProvider mode only if the actual view exposes it; do not
   reconstruct the earlier warning or edit state.
4. In read-only mode, capture the already persisted Odoo synthetic sale order
   and the HubSpot synthetic Company, Deal, and association. Make clear in
   later captions that the Company was reused. Do not include portal, company,
   deal, or other private provider identifiers in any public derivative.
5. Capture the existing Gmail source thread with the two delivered replies
   and the existing Slack synthetic notifications. Crop/blur sandbox mailbox,
   account/workspace/channel identifiers, URLs, profile details, unrelated
   content, and message/provider IDs in sanitized derivatives. Keep enough
   synthetic subject/body and notification wording to identify the evidence.
6. If visual replay evidence is useful, capture an unaltered read-only view of
   the retained replay record and label it as a run-record excerpt; do not
   fabricate a product screen or replay result. Prefer the actual persisted
   UI/database evidence for counts and state.
7. Review each raw frame privately, then create sanitized derivatives for
   owner review. Add visible **POST-RUN INSPECTION** labels to any derivative
   that could otherwise be mistaken for contemporaneous footage. Do not put
   raw captures or sanitized media into Git yet. Retain the private evidence
   directory for audit; publication, hosting, and license decisions remain
   subject to their later approval gates.

**M12C closeout:** The amended documentation, protected run evidence, and
sanitized captures received independent PASS review and human acceptance.
M12C is COMPLETE under the limited-scope amendment; this does not change the
M12C-3 factual PARTIAL result or the explicit NOT DEMONSTRATED automated Gmail
intake limitation. M12D, M12E, and M12F remain NOT STARTED. The independent
review recorded two Low findings covering the private artifact and public-media handling: a private `.DS_Store`
artifact remains contained by directory permissions; redact the HubSpot
“Sales Hub Enterprise” label before public use; and explicitly caption
scripted FakeProvider extraction in any public media.

#### Historical M12C-3 pre-run readiness decision — 2026-10-14

This was the pre-authorization decision recorded before the 2026-10-18 run.
The later transaction and current evidence disposition above supersede it as
the current status; this section is retained as a historical decision record.

**Historical readiness decision: NOT READY for live execution.** No sandbox target had
been verified, no operation or spend ceiling is authorized, Gemini is not
safe for a one-call claim under current application recovery, and Gmail/Slack
physical request ceilings remain unresolved. At that pre-run point, no provider operation, cross-provider transaction,
actual completion delivery, post-completion replay, or media capture had been
demonstrated. These findings do not weaken the
accepted full-demo criterion: M12C-3 must still prove actual Gmail intake,
application extraction with provider mode truthfully identified,
deterministic validation and distinct human review/approval, actual Odoo and
HubSpot records with durable receipts, actual post-sync Gmail and Slack
delivery tied to successful synchronization, one logical order and unchanged
ERP/CRM object counts on exact-source replay, and sanitized inspectable
evidence. Both post-sync notifications remain required.

Recommended next task: owner chooses Option A (no live Gemini) or separately
authorizes a scoped Option B design/implementation review; then authorize a
focused static/runtime retry-ceiling review for the pinned Gmail/Slack paths
and approve exact sandbox target types. Only after those controls are
reviewed should the owner issue a separate operation-by-operation M12C-3
authorization. This section is a readiness design, not that authorization.
