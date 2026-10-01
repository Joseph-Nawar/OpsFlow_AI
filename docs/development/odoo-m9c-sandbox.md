# M9C Odoo 19 Community sandbox

This guide describes the isolated local Odoo target for M9C. Do not point the
adapter or the opt-in tests at a shared, production, or customer database. The
required development path uses Odoo Community in Docker and has no mandatory
paid service.

## Probe record and current gate

The M9C probe used image `odoo:19.0`, reporting version `19.0-20260926`, with a
separate PostgreSQL container/network and database `opsflow_m9c_disposable`.
The Odoo HTTP port was bound to loopback port `18069`; this environment is
outside the tracked product Compose stack.

| Check | Result | Evidence boundary |
| --- | --- | --- |
| Odoo version | Verified as `19.0-20260926`. | Disposable server startup output. |
| JSON-2 route | `POST /json/2/res.company/read` returned a bounded read result. | Read-only probe. |
| Bearer API-key authentication | Accepted by JSON-2 with the database header. | Ephemeral administrator key, not the integration user. |
| Database header | `X-Odoo-Database` selected `opsflow_m9c_disposable`. | Read-only probe. |
| API documentation | `/doc` redirected to the browser login page; `/doc-bearer/index.json` and authenticated model descriptions were accessible with the API key. | The dedicated bot's visibility remains unverified. |
| Odoo models and fields | Required customer, product, stock, sales order, order line, pricelist, and warehouse fields were visible in authenticated model descriptions. | Administrator metadata probe; bot ACLs remain a gate. |
| Bridge addon | Installed in the disposable database. Odoo-native tests exercised the public model method, group guard, final recheck, uniqueness, replay, and confirmation path. | Tests ran inside rollback-isolated Odoo transactions; this is not proof of a JSON-2 write. |
| Product user group | The approved plan's external ID `product.group_product_user` does not exist in this Odoo 19 build. Installed ACL definitions grant product read through `base.group_user` and `stock.group_stock_user`; `product.group_product_manager` is broader. | **Live write gate remains open.** Do not silently substitute the manager role or create an API-key writer user until the intended least-privilege standard group/access combination is explicitly verified. |
| JSON-2 bridge create/replay/rollback and concurrent calls | Not run. | Blocked by the integration-user permission gate above. No Odoo business order was written during the probe. |

The Odoo-native addon tests passed on the disposable database. They created
synthetic records only within Odoo test transactions, which were rolled back.
They do not establish the JSON-2 request transaction boundary, real integration
user permissions, or live provider convergence. The opt-in JSON-2 suite remains
unrun until the access gate and the rest of the live checklist below pass.

## Isolated setup

Use a disposable local Odoo 19 Community instance, separate PostgreSQL database,
and an ignored configuration file stored outside the repository. Mount
`integrations/odoo` as the add-on path. If running the JSON-2 confirmation
rollback probe, also add `integrations/odoo/test_support` to Odoo's add-on paths
and install `opsflow_sale_bridge_failure_probe` only in the disposable test
database. The failure probe rejects confirmation only for its reserved
synthetic UUID.

The tested Odoo-native suite can be run with the Odoo executable inside the
container, using the disposable database name:

```bash
docker exec opsflow-m9c-odoo odoo \
  --config=/etc/odoo/odoo.conf \
  -d opsflow_m9c_disposable \
  -u opsflow_sale_bridge \
  --test-enable --stop-after-init --http-port=18070 --log-level=test
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
   `X-Odoo-Database`, and authenticated `/doc-bearer` model/method visibility.
2. Confirm the bridge addon is installed and
   `sale.order.opsflow_create_or_get_sale_order` is exposed to the dedicated
   bot. Confirm that the user belongs to
   `group_opsflow_sale_bridge`, is allowed in the configured company, and has
   only the ordinary sale, stock, product-read, and company access needed by
   ORM ACLs and record rules. The missing `product.group_product_user` ID must
   be resolved with verified least privilege before proceeding.
3. Verify the configured company, warehouse, one currency, rule-free base
   pricelist, product base Sales UoM, effective `product.product.lst_price`,
   and warehouse-scoped `free_qty`. Confirm there are no custom price rules.
4. Use only synthetic customer/product/order records and enough synthetic
   stock. Confirm confirmation side effects and UTC commitment-date storage.
5. Run the JSON-2 opt-in only after the gates above pass and the disposable
   database cleanup path is ready:

   ```bash
   OPSFLOW_ODOO_LIVE_TESTS=1 uv run pytest tests/odoo_live/test_phase9_bridge_json2.py -q
   ```

   The suite requires ignored runtime settings plus local synthetic customer
   reference and SKU values. It checks commit with discarded local receipt and
   same-identity replay, concurrent same-UUID convergence, and confirmation
   failure followed by a fresh JSON-2 read proving rollback. It is excluded
   from ordinary repository test runs unless explicitly enabled.

After collecting only sanitized version, receipt-presence, replay, and rollback
evidence, stop and remove only the disposable Odoo/PostgreSQL containers,
network, database, and volumes. Do not use a product Compose teardown with
volume removal as a substitute for isolating this environment.
