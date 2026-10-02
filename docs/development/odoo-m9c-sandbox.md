# M9C Odoo 19 Community sandbox

This guide describes the isolated local Odoo target for M9C. Do not point the
adapter or the opt-in tests at a shared, production, or customer database. The
required development path uses Odoo Community in Docker and has no mandatory
paid service.

## Probe record and setup status

The M9C probe used image `odoo:19.0`, reporting version `19.0-20260926`, with a
separate PostgreSQL container/network and database `opsflow_m9c_disposable`.
The Odoo HTTP port was bound to loopback port `18069`; this environment is
outside the tracked product Compose stack.

| Check | Result | Evidence boundary |
| --- | --- | --- |
| Odoo version | Verified as `19.0-20260926`. | Disposable server startup output. |
| JSON-2 route | `POST /json/2/res.company/read` returned a bounded read result. | Read-only probe. |
| Bearer API-key authentication | Accepted by JSON-2 with the database header for the dedicated bot and ordinary Sales/Stock test user. | Temporary keys were verified, then replaced keys were revoked. Secret values are not recorded. |
| Database header | `X-Odoo-Database` selected `opsflow_m9c_disposable`. | Read-only probe. |
| API documentation | `/doc` redirected to the browser login page; `/doc-bearer/index.json` and authenticated model descriptions were accessible with a temporary developer/admin key. | The dedicated bot does not need documentation access. |
| API documentation authorization | Odoo's `api_doc` controller requires `api_doc.group_allow_doc` for `/doc-bearer`; an ordinary authorized M9C bot without that documentation-only group gets 403. A temporary developer/admin API key can inspect the method and field contracts. | Do not add `api_doc.group_allow_doc` to either integration test user. Verify docs with the developer/admin setup context and verify bot access using fixed JSON-2 calls instead. |
| Odoo models and fields | Required customer, product, stock, sales order, order line, pricelist, and warehouse fields were visible in developer/admin metadata. The bot read the configured company, warehouse, pricelist, exact synthetic customer/SKU, `lst_price`, and warehouse-scoped `free_qty`. | `/doc-bearer` is restricted to the developer/admin context; direct bot JSON-2 reads were verified separately. |
| Bridge addon | Installed in the disposable database. A fresh native-test database passed all 13 bridge addon post-install tests. | Native tests exercise the ORM method and ACL logic, not the JSON-2 request transaction boundary. |
| Integration bot roles | Verified exact membership in `sales_team.group_sale_salesman`, `stock.group_stock_user`, and `opsflow_sale_bridge.group_opsflow_sale_bridge`. The ordinary test user has the first two and lacks the bridge group. Neither user has Product Manager, Sales Manager, Stock Manager, Settings, or Admin membership. | Salesperson implies `base.group_user`; these roles successfully read the needed data and the bot invoked the bridge. Stock User carries meaningful stock permissions, so retain a dedicated integration account and private API key. Do not use `product.group_product_user` or grant `product.group_product_manager`. |
| JSON-2 bridge create/replay/rollback and concurrent calls | The opt-in suite passed 5 tests against `opsflow_m9c_disposable`. It proved lost-local-receipt replay, forced same-snapshot concurrent UUID race with retryable loser and fresh replay, both confirmation rollback paths, and rejection of the ordinary user without the bridge group. | Synthetic data only. Requests used the real JSON-2 route and a fresh independent read/count for reconciliation, rollback, and authorization assertions. |

The setup used Odoo `19.0-20260926`, one company and USD currency, a rule-free
base pricelist, one synthetic customer, and one synthetic storable variant in
the configured warehouse. Its template base price was 10 and the variant extra
was 2; the bot read effective `product.product.lst_price` as 12 and positive
scoped `free_qty`. The ordinary test user authenticated and read the same
required model surfaces, but the bridge returned bounded `INTEGRATION_CONFIG`
without creating or reconciling an order. The authorized bot's fixed JSON-2
bridge call was exposed and returned the expected bounded validation rejection
for a deliberately invalid no-write probe.

The native addon suite and the separate opt-in JSON-2 suite both passed. The
JSON-2 suite exercised real request commits and rollbacks with synthetic data;
this evidence applies only to the named local disposable database and does not
authorize pointing the adapter at another Odoo environment.

An additional controlled JSON-2 probe created one synthetic confirmed order,
discarded its first receipt, lowered only that synthetic variant's stock until
the configured warehouse reported negative `free_qty`, then replayed the same
UUID and unchanged payload. The bridge returned the same receipt and an
independent read/count found one order. The adapter's signed-value parsing and
M9B reconciliation path are covered separately by provider-free integration
tests; no production inventory or customer data was involved.

## Isolated setup

Use a disposable local Odoo 19 Community instance, separate PostgreSQL database,
and an ignored configuration file stored outside the repository. Mount
`integrations/odoo` as the add-on path. If running the JSON-2 confirmation
rollback probe, also add `integrations/odoo/test_support` to Odoo's add-on paths
and install `opsflow_sale_bridge_failure_probe` only in the disposable test
database. The failure probe rejects confirmation only for its reserved
synthetic UUID.

### Recreate the local Community service from a clean checkout

The repository includes a sandbox-only Compose file; it is separate from the
OpsFlow application Compose stack. Copy its blank example, set a fresh local
PostgreSQL password and a one-time Odoo database-administrator password, and
keep that file ignored:

```bash
cp integrations/odoo/.env.m9c-sandbox.example integrations/odoo/.env.m9c-sandbox
```

Set `M9C_POSTGRES_PASSWORD` and `M9C_ODOO_ADMIN_PASSWORD` in that file. Source
the ignored values into the local shell without echoing them so the Odoo CLI
can receive PostgreSQL connection variables for one-shot subcommands:

```bash
set -a
. integrations/odoo/.env.m9c-sandbox
set +a
```

Start only the isolated Odoo project, choosing a unique Compose project name
and an unused loopback port:

```bash
docker compose \
  --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml \
  -p opsflow-m9c-disposable up -d
```

The PostgreSQL service has no published host port. Create an explicitly named
disposable database, then install Sales/Inventory and the bridge addon:

```bash
docker compose --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml -p opsflow-m9c-disposable \
  exec -T -e PGHOST=db -e "PGUSER=$M9C_POSTGRES_USER" \
  -e "PGPASSWORD=$M9C_POSTGRES_PASSWORD" odoo \
  odoo db init opsflow_m9c_disposable --password "$M9C_ODOO_ADMIN_PASSWORD" \
  --country US
docker compose --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml -p opsflow-m9c-disposable \
  exec -T -e PGHOST=db -e "PGUSER=$M9C_POSTGRES_USER" \
  -e "PGPASSWORD=$M9C_POSTGRES_PASSWORD" odoo \
  odoo module install -c /etc/odoo/odoo.conf -d opsflow_m9c_disposable \
  sale_stock opsflow_sale_bridge
```

`odoo db init` uses the CLI subcommand syntax; do not put `--config` before the
subcommand. The database name must be disposable and must never be a
shared/customer database. The seed helper is intended for one run per fresh
database; if its reserved bot already exists, it stops before setup writes so
it cannot silently generate another API key. Discard/recreate only the
disposable database before reseeding. The helper
[`prepare_m9c_sandbox.py`](../../integrations/odoo/prepare_m9c_sandbox.py) runs
only inside an Odoo superuser shell and rejects database names outside the
`opsflow_m9c_*` / `opsflow_m9e_*` pattern. It accepts only an explicit
`OPSFLOW-M9E-CUST-<suffix>` customer reference and
`OPSFLOW-M9E-SKU-<suffix>` product code. It creates a USD pricelist, trusted
synthetic customer/product, 100 units of synthetic stock, and a dedicated bot
with only the approved Salesperson, Stock User, and bridge groups. It writes a
new API key only to an operator-selected `/tmp` file with mode 600 and never
prints the key. Example fixture and invocation:

```bash
python3 - <<'PY'
import json
import secrets
from pathlib import Path

suffix = secrets.token_hex(5).upper()
Path('/tmp/m9c-fixture.json').write_text(json.dumps({
    'suffix': suffix,
    'customer_reference': f'OPSFLOW-M9E-CUST-{suffix}',
    'sku': f'OPSFLOW-M9E-SKU-{suffix}',
}))
PY
docker compose --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml -p opsflow-m9c-disposable \
  cp /tmp/m9c-fixture.json odoo:/tmp/m9c-fixture.json
docker compose --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml -p opsflow-m9c-disposable \
  exec -T -e OPSFLOW_M9C_SANDBOX_DATABASE=opsflow_m9c_disposable \
  -e PGHOST=db -e "PGUSER=$M9C_POSTGRES_USER" \
  -e "PGPASSWORD=$M9C_POSTGRES_PASSWORD" \
  -e OPSFLOW_M9C_FIXTURE_PATH=/tmp/m9c-fixture.json \
  -e OPSFLOW_M9C_API_KEY_PATH=/tmp/m9c-api-key \
  -e OPSFLOW_M9C_RESULT_PATH=/tmp/m9c-result.json odoo \
  odoo shell -c /etc/odoo/odoo.conf -d opsflow_m9c_disposable --no-http \
  < integrations/odoo/prepare_m9c_sandbox.py
```

Copy the mode-600 API key and non-secret numeric IDs from the container with
`docker compose cp`:

```bash
docker compose --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml -p opsflow-m9c-disposable \
  cp odoo:/tmp/m9c-api-key /tmp/m9c-api-key
docker compose --env-file integrations/odoo/.env.m9c-sandbox \
  -f integrations/odoo/docker-compose.sandbox.yml -p opsflow-m9c-disposable \
  cp odoo:/tmp/m9c-result.json /tmp/m9c-result.json
chmod 600 /tmp/m9c-api-key /tmp/m9c-result.json
```

Never print the API-key file. Enter its value only in ignored OpsFlow `.env`
or an equivalent secret environment, and use the numeric result fields for the
company, warehouse, and pricelist settings. For M9E, attach only the Odoo
application container to the isolated OpsFlow Compose network using
`docker network connect --alias odoo <opsflow-project>_default
<odoo-container-id>`, then set the API URL to `http://odoo:8069`. Do not attach
the Odoo PostgreSQL container to the OpsFlow network. The integration bot key
and credentials remain out of n8n. After the sandbox evidence is collected,
stop/remove only this named disposable Odoo project and its volume.

The focused Odoo-native addon suite can be run with the Odoo executable inside
the container. Install the bridge and test-support addons in a fresh disposable
native-test database, then select only the bridge addon tests:

```bash
docker exec opsflow-m9c-odoo odoo \
  --config=/etc/odoo/odoo.conf \
  -d opsflow_m9c_native \
  -u opsflow_sale_bridge,opsflow_sale_bridge_failure_probe \
  --test-enable --test-tags /opsflow_sale_bridge \
  --stop-after-init --http-port=18070 --log-level=test
```

Use a free alternate HTTP port for the one-shot test process because the
disposable Odoo server may already be listening on its configured port. Do not
run these commands against the shared product Compose database.

## Runtime configuration and key lifecycle

Configure all six values together in an ignored local `.env` or equivalent
runtime environment:

```dotenv
OPSFLOW_ODOO_BASE_URL=
OPSFLOW_ODOO_DATABASE=
OPSFLOW_ODOO_API_KEY=
OPSFLOW_ODOO_COMPANY_ID=
OPSFLOW_ODOO_WAREHOUSE_ID=
OPSFLOW_ODOO_PRICELIST_ID=
```

Never put a key in tracked configuration, tests, fixtures, workflow exports,
logs, or reports. Odoo API keys expire. To rotate one, generate a replacement,
update only ignored runtime configuration, verify the new key against the
disposable instance, then revoke the old key. Phase 9 does not automate key
rotation. The test opt-in also requires synthetic customer reference and SKU
values in the process environment; keep those values local to the disposable
setup.

## Live verification gates

Before any JSON-2 business write, verify against the selected disposable
database and dedicated bot account:

1. Confirm Odoo 19 Community, `/json/2`, bearer API-key authentication,
   `X-Odoo-Database`, and `/doc-bearer` model/method visibility using a
   developer/admin account with Odoo's docs permission. The integration bot
   does not receive `api_doc.group_allow_doc`; its direct JSON-2 calls are
   checked separately.
2. Confirm the bridge addon is installed and
   `sale.order.opsflow_create_or_get_sale_order` is exposed to the dedicated
   bot. Assign only `sales_team.group_sale_salesman`,
   `stock.group_stock_user`, and `group_opsflow_sale_bridge`; verify the
   Salesperson role implies `base.group_user` and that these roles provide the
   required product/partner reads, `lst_price`/`free_qty` access, Sales writes,
   and company scope under the selected database's ordinary ACLs and record
   rules. Stock User carries meaningful stock permissions; keep this a
   dedicated bot with a private API key. Do not add Product Manager, Sales
   Manager, Stock Manager, Settings, or Admin roles without a concrete ACL
   failure and an explicit review.
3. Create a second ordinary Sales/Stock test user with those same standard
   roles but without `group_opsflow_sale_bridge`. Store only its separate
   private API key in ignored live-test process configuration as
   `OPSFLOW_ODOO_M9C_UNAUTHORIZED_API_KEY`; this value is test-only and is not
   part of OpsFlow production settings. Confirm it can authenticate and reach
   the method but receives the bounded authorization rejection.
4. Verify the configured company, warehouse, one currency, rule-free base
   pricelist, product base Sales UoM, effective `product.product.lst_price`,
   and warehouse-scoped `free_qty`. Confirm there are no custom price rules.
5. Use only synthetic customer/product/order records and enough synthetic
   stock. Confirm confirmation side effects and UTC commitment-date storage.
6. Run the JSON-2 opt-in only after the gates above pass and the disposable
   database cleanup path is ready:

   ```bash
   OPSFLOW_ODOO_LIVE_TESTS=1 uv run pytest tests/odoo_live/test_phase9_bridge_json2.py -q
   ```

   The suite requires ignored runtime settings, local synthetic customer
   reference and SKU values, and the test-only ordinary-user key. It checks
   commit with discarded local receipt and same-identity replay, a forced
   same-snapshot concurrent UUID race followed by fresh retry/replay, both
   raising and non-raising confirmation rollback through fresh JSON-2 reads,
   and authorization rejection for the ordinary user without the bridge group.
   It is excluded from ordinary repository test runs unless explicitly
   enabled.

After collecting only sanitized version, receipt-presence, replay, and rollback
evidence, stop and remove only the disposable Odoo/PostgreSQL containers,
network, database, and volumes. Do not use a product Compose teardown with
volume removal as a substitute for isolating this environment.
