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
cp .env.example .env
```

Set a unique random `OPSFLOW_ORCHESTRATION_TOKEN` locally. Set all six Odoo
values from the dedicated disposable M9C setup and all five HubSpot values
from the synthetic M9D portal. Set an `OPSFLOW_REVIEW_DEV_OPERATORS` JSON
array with a separate local review credential, for example:

```dotenv
OPSFLOW_REVIEW_DEV_OPERATORS='[{"token":"<local-random-review-token>","actor":"m9e-reviewer","role":"APPROVER"}]'
```

Replace the placeholder locally with a unique random value. Keep every
credential only in ignored
`.env` or the local credential UI; never commit or share its value. The
orchestration token is for n8n-to-API execution; the approver credential is
for the human review UI. Neither is an Odoo or HubSpot credential.

An incomplete or absent optional provider configuration does not make the API
unready. `/ready` checks API/database readiness only. In this configuration,
Compose still starts n8n and the authenticated execute-next request returns
bounded HTTP 503 before claiming work. For a no-write smoke test, leave one or
more provider settings blank in a fresh project; confirm `/ready` is 200 and
execute-next is 503. Restore the complete synthetic provider configuration
before the live E2E.

Start and migrate a fresh Compose project:

```sh
docker compose -p opsflow-m9e-demo up -d --build postgres api n8n
uv sync --frozen --dev
uv run alembic upgrade head
uv run alembic current
curl --fail http://127.0.0.1:8000/ready
```

The local `.env` database URL must point the host Alembic command to this
project's PostgreSQL on `localhost:5432`. Compose configures the API's
container-side database URL to `postgres:5432`. The API healthcheck gates n8n
on `/ready`, which means the API and database can receive requests; it does
not require optional provider settings to be complete. A provider-incomplete
API can therefore stay healthy and return the documented preclaim 503.

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

If creating orders through the review UI, start the frontend from this
checkout:

```sh
npm --prefix web ci
npm --prefix web run dev -- --host 127.0.0.1
```

Open `http://127.0.0.1:5173`, use the dedicated local development operator
configured as `APPROVER`, and submit the existing synthetic intake fixture
through the Phase 7 sandbox-intake workflow and
[`fixtures/phase7/synthetic-order.txt`](../../fixtures/phase7/synthetic-order.txt).
Use a fresh event ID. Follow the existing review contract and UI to inspect
the resulting `READY_FOR_APPROVAL` order. No direct database seeding of an
approved order is permitted. n8n cannot approve or synchronize an order with
no approved sync intent.

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
through the existing authorized OpsFlow review contract. Only OpsFlow creates
the durable sync intent. Invoke the same thin workflow again; n8n supplies no
order ID and cannot override approval.

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
