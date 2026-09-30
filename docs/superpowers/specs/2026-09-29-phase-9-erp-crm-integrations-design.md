# Phase 9 — ERP/CRM Contract, Current-API Probe & Design

**Milestone:** M9A — ERP/CRM Contract, Current-API Probe & Design
**Status:** M9A COMPLETE; M9B IN PROGRESS pending independent/human implementation review; M9C–M9F NOT STARTED
**Date:** 2026-09-29
**Revised:** 2026-09-30
**Branch base:** Phase 8 merge `528bbf1a3218f25dddcd0893ed601686f99223e3`

This document is the approved authoritative Phase 9 design. Provider documentation and the isolated Odoo probe below are research evidence. HubSpot account writes, credentials, and account-specific validation remain untested. M9A is COMPLETE following human design approval at commit `21e1cf4351e4637b074e19023754650db80f0eb3`.

**Evidence labels:** VERIFIED means confirmed in authoritative provider documentation or the isolated Odoo probe; DESIGN DECISION means the recommended Phase 9 behavior; ACCEPTED LIMITATION means an explicit scope/capability boundary; LIVE SETUP GATE means a fact that still needs an interactive account or credential check.

## 1. Problem and outcome

Phase 8 ends after a human approves an order for processing. Phase 9 adds the durable handoff from that approved OpsFlow order to the ERP and CRM:

`APPROVED → durable sync intent → SYNCING → confirmed Odoo sales order → HubSpot Company + Deal + association → COMPLETED`

The required business guarantees are:

- An order cannot reach an external write before it is approved.
- Approval and durable sync intent commit together.
- Retries converge on no more than one logical Odoo sales order, one HubSpot Company per trusted Odoo customer reference, and one HubSpot Deal per OpsFlow order.
- The order completes only after every required external receipt is durably recorded.
- A CRM failure after ERP success resumes at the missing CRM step and never recreates the ERP order.
- Provider calls are at-least-once. No exactly-once execution claim is made.

Python owns trusted-data mapping, deterministic validation, order policy, durable receipts, state changes, provider calls, and recovery. n8n schedules and invokes one narrow OpsFlow operation. Odoo and HubSpot remain external systems.

## 2. Constraints and non-goals

### Verified repository constraints

The Phase 1 state machine already defines `APPROVED`, `SYNCING`, `COMPLETED`, `FAILED_RETRYABLE`, and `FAILED_FINAL`, including `APPROVED → SYNCING`, `SYNCING → COMPLETED`, and failure transitions. `Order.retry()` returns a retryable order to its recorded failure origin. Phase 9 will use those transitions without adding states.

The existing `BusinessDataProvider` protocol returns trusted customer candidates and one trusted product result per requested order line. `TrustedProduct` already carries active status, currency, catalogue price, and available quantity. Existing validation policy owns customer/product resolution, currency and price checks, inventory checks, and routing.

Phase 8 already demonstrates a durable row per side effect, database-backed claims, expiring leases, bounded retries, provider-free tests, and external receipts. Phase 9 will apply those proven patterns to one order-sync row; it will not add a generalized integration engine.

Sources of truth and design boundaries are the [domain model](../../architecture/domain-model.md), [system overview](../../architecture/system-overview.md), [development guide](../../development/development-guide.md), and [Phase 8 design](2026-09-25-phase-8-email-notification-integrations-design.md) and [audit](../../audits/phase-8-audit.md). In particular, the LLM may extract values and evidence but cannot validate trusted data, approve an order, choose a provider mutation, or set CRM/ERP state.

### Explicit non-goals

- No production implementation, migration, adapter, or n8n Phase 9 workflow in M9A.
- No changes to the domain state machine.
- No CRM Contacts, custom objects, tickets, marketing automation, workflows, or broad customer sync.
- No Gmail-sender-to-CRM identity mapping.
- No Odoo Online dependency, paid SaaS requirement, real customer data, or credentials in Git.
- No event bus, microservice, integration framework, or provider-response archive.
- No claim that a remote HTTP call executes exactly once.

## 3. Verified current-provider findings

### Odoo 19 Community

**VERIFIED by isolated local probe:** a disposable official `odoo:19.0` Community container reported version `19.0-20260926`. Its database contained Odoo's standard Sales and Inventory modules, with synthetic records only. The local Community instance accepted a JSON-2 request authenticated with an Odoo user API key generated with its `rpc` scope and returned the caller context. The probe created one synthetic partner, one synthetic storable product, a synthetic quotation, and confirmed it. It returned the integer sale-order ID and sequence name. No project Compose file, tracked infrastructure, or external business system was changed.

Odoo 19 documents JSON-2 at `POST /json/2/<model>/<method>`, using an `Authorization: bearer <API key>` header and JSON request body. The request can include `context` and method arguments. A database selector can be sent with `X-Odoo-Database` when needed. The key belongs to an Odoo user and inherits that user's access rights. Odoo recommends a dedicated least-privilege integration user. Each JSON-2 request is its own database transaction: success commits and an error rolls back. A multi-write operation that must be atomic belongs in one server-side model method. See [Odoo 19 External API documentation](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html).

The exact tested standard-model create shape was `POST /json/2/sale.order/create`, bearer API-key authentication, `Content-Type: application/json`, and this JSON body:

~~~json
{
  "vals_list": [
    {
      "partner_id": 6,
      "order_line": [
        [0, 0, {
          "product_id": 1,
          "product_uom_qty": 1.0,
          "price_unit": 10.0
        }]
      ]
    }
  ]
}
~~~

The database header was `X-Odoo-Database: opsflow_m9a` in the local probe. The response was HTTP 200 with a one-element array containing the new record ID. A model read then returned the record name and state; `POST /json/2/sale.order/action_confirm` with `{"ids": [<id>]}` returned true and changed the state to `sale`. For read/search methods, use their named JSON arguments plus a `context` object, for example `allowed_company_ids` and `warehouse`; do not send XML-RPC positional argument arrays. The future bridge method will use this same JSON-2 model/method route shape, with its exact argument names set by the M9C addon contract.

**DESIGN DECISION:** use JSON-2 for new work. Odoo 19 marks the older XML-RPC and JSON-RPC external endpoints for removal in Odoo 22 (planned for fall 2028); they add no capability needed here. Odoo model names, installed fields, and access rights vary by database, so implementation setup must inspect that instance's model/field metadata rather than assume every deployment is identical.

The `odoo:19.0` Community runtime exposes the standard `res.partner`, `product.product`, `product.template`, `sale.order`, `sale.order.line`, `stock.quant`, and `stock.warehouse` models through JSON-2. The field probe and synthetic create/confirm trial below verified the Phase 9 mapping. Odoo's 19.0 source also defines sales-order lines and stock quantities in the public Community source: [sale order](https://github.com/odoo/odoo/blob/19.0/addons/sale/models/sale_order.py), [sale order line](https://github.com/odoo/odoo/blob/19.0/addons/sale/models/sale_order_line.py), [product template](https://github.com/odoo/odoo/blob/19.0/addons/product/models/product_template.py), and [stock product quantities](https://github.com/odoo/odoo/blob/19.0/addons/stock/models/product.py).

### HubSpot

**VERIFIED from current official developer documentation, not from a live account:**

- HubSpot's current API direction is date-based versioning, with March and September releases and an 18-month support window. The Fall 2026 developer update lists both Companies and Deals among APIs updated in platform/API release `2026-09`. HubSpot's legacy API notice says v1–v3 move to unsupported status in September 2027 and v4 has its own March 2027 support end. See the [date-based versioning guide](https://developers.hubspot.com/changelog/introducing-date-based-api-versioning), [Fall 2026 developer update](https://developers.hubspot.com/changelog/fall-2026-spotlight), and [legacy API support notice](https://developers.hubspot.com/changelog/legacy-apis-and-legacy-apps-whats-going-unsupported-and-when).
- **Service Keys** are in public beta and are intended for account-level system-to-system access when OAuth installation and webhooks are not needed. They are the current replacement for new integrations previously built with legacy private apps. A key is scoped to the creator's granted account permissions, remains account-level, and can be rotated with a seven-day overlap. New HubSpot accounts created on or after 2026-09-28 can no longer create legacy private apps; HubSpot says to use Service Keys for new in-account integrations. See [Service Keys](https://developers.hubspot.com/changelog/service-keys) and the [legacy private-app creation sunset](https://developers.hubspot.com/changelog/legacy-private-app-creation-sunset).
- The Fall 2026 update lists Companies and Deals among APIs updated for `2026-09`. The per-endpoint references inspected for this revision now render `2026-09` example paths and put `idProperty` inside each generated input, while their prose still describes `idProperty` as a query parameter; earlier M9A/review evidence showed `2026-03` examples/paths. Treat this as version-sensitive, inconsistent documentation evidence, not proof that the selected account accepts a particular route or request shape. See the [Fall 2026 developer update](https://developers.hubspot.com/changelog/fall-2026-spotlight), [Company upsert reference](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/companies/batch/upsert-companies), and [Deal upsert reference](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/deals/batch/upsert-deals).
- The currently rendered batch-upsert references document response statuses `PENDING`, `PROCESSING`, `CANCELED`, and `COMPLETE`, and show both HTTP 200 and HTTP 207 response variants with result/error fields. This documents possible response shapes; it is not live proof of the selected account's route, completion behavior, or result correlation contract. See the [Company upsert reference](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/companies/batch/upsert-companies) and [Deal upsert reference](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/deals/batch/upsert-deals).
- HubSpot documents unique custom properties for Company and Deal records; new custom properties can use `hasUniqueValue: true` as stable object identities. Exact versioned upsert paths and payloads still require live validation. See [unique-property support](https://developers.hubspot.com/changelog/unique-properties-for-contacts).
- Starting with `2026-09`, API writes enforce account-configured record validation, required fields, and association permissions. A pipeline stage or account rule can therefore reject an otherwise valid integration payload. The sandbox setup must check these rules and permissions, and tests must exercise the selected account. See [2026-09 CRM write validation enforcement](https://developers.hubspot.com/changelog/crm-api-write-validation-enforcement).
- A free developer account provides test accounts, public API access, and sample CRM data. Developer test accounts are isolated, periodically reset, and can be created with a 90-day Enterprise trial; up to ten are available per developer account. See [Developer Platform Basics](https://developers.hubspot.com/developer-platform-basics) and HubSpot's [developer test-account guide](https://developers.hubspot.com/blog/how-to-safely-experiment-with-ai-in-hubspot-before-you-touch-real-data).
- The current published general limits for privately distributed apps on Free/Starter are 100 requests per app per 10 seconds and 250,000 per account per day. The page does not establish an exact quota bucket for Service Keys on the 2026-09 API, so that account-specific figure remains an interactive setup check. Three HubSpot writes per order are well below the published baseline at portfolio scale. Honor `429` responses and rate-limit headers, and verify the test account's actual limit during M9D. See [API usage guidelines and limits](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines).

**DESIGN DECISION:** target HubSpot's current date-based API generation and intend to use `2026-09` for Company, Deal, and association operations wherever those endpoints are actually available. Do not fall back to numbered v3/v4 paths because endpoint references disagree or lag; resolve the selected date-versioned contract in the test account.

**LIVE SETUP GATE:** before M9D freezes the adapter contract, exercise these against the selected developer test account: exact Company batch-upsert path; exact Deal batch-upsert path and object-type representation; exact association path; exact `idProperty` placement; and the Service Key's Company, Deal, and association permissions. Confirm each accepted route and response in the account. No exact `2026-09` object path is considered verified by this M9A documentation probe.

**HubSpot batch receipt rule — DESIGN DECISION:** an upsert response is not itself a durable receipt. OpsFlow records a Company or Deal ID only after a terminal `COMPLETE` result for the one requested logical object, exactly one successful result matching the submitted stable identity, a confirmed HubSpot record ID, and no per-item error for that object. A per-item error maps to the bounded failure model. `CANCELED` is a failed step with no receipt. `PENDING` or `PROCESSING` is a transient in-flight step: do not record a receipt and do not advance to Deal, association, or completion. HTTP `207` is neither automatic success nor automatic failure: inspect the submitted item's result and errors. A `207` may yield a receipt only when all the same terminal, unique-match, confirmed-ID, and no-item-error conditions hold; otherwise map its error or ambiguity to the bounded failure model and persist no receipt.

**LIVE SETUP GATE for nonterminal upserts:** M9D must identify the documented and live-supported completion mechanism for `2026-09`: a response-provided status/result link or polling contract, if available, or a bounded later replay/reconciliation using the same unique property if that is documented and safe. Do not invent a polling endpoint. Until verified, keep the same HubSpot step in the existing durable sync/retry flow; nonterminal work is not a successful receipt. If the verified contract requires a provider operation handle across invocations, persist only that bounded opaque handle in the existing `order_syncs` row, never the raw response.

## 4. Architecture

The flow is:

1. Approval commits the `APPROVED` transition, its audit event, and one `order_syncs` intent in the same local transaction.
2. The OpsFlow sync executor claims one eligible row and moves a first-run order from `APPROVED` to `SYNCING` in the claim transaction.
3. Python makes a fresh read-only Odoo trusted-data lookup and deterministic final validation against the immutable approved order.
4. Python calls the Odoo bridge once. The bridge creates or returns the unique sale order and confirms it in the same Odoo transaction.
5. OpsFlow persists the Odoo ID and name in a short local transaction before starting HubSpot work.
6. Python upserts the trusted Company and persists its ID only after the terminal-success rule in Section 7; then it upserts the Deal and persists its ID under the same rule, creates the default Deal–Company association, and persists that confirmation. Each durable receipt commits before the next business step.
7. OpsFlow changes `SYNCING → COMPLETED` only after all required receipts are present and writes the completion audit event atomically.

No database transaction spans a network call. n8n never sees provider credentials or provider business payloads.

## 5. Odoo mapping and trusted-data adapter

### Trusted data

Use the existing `BusinessDataProvider` contract directly. One configured `OdooERPAdapter` implements its asynchronous lookup and exposes the approved-order write operation. A separate read adapter and write adapter would duplicate the endpoint, company, credential, timeout, and error configuration. Split the class later only if independent permissions or deployment boundaries require it.

The adapter returns existing `TrustedBusinessData`, `TrustedCustomer`, and `TrustedProduct` values. The existing deterministic validator remains responsible for customer/product ambiguity, active checks, supported currency, price tolerance, inventory, and routing. Odoo is trusted reference data; Odoo and n8n do not own OpsFlow validation policy.

| OpsFlow value | Odoo 19 Community model/field | Mapping rule |
| --- | --- | --- |
| Customer | `res.partner` | Search by exact trusted `ref`; use `name`, `active`, `is_company`, and `customer_rank`. Require one unambiguous active company customer. Do not use email or sender identity. |
| Product identity | `product.product` | One sellable variant per SKU; exact `default_code`; use `name`, `active`, `sale_ok`, `is_storable`, and `uom_id`. Its template relation is `product_tmpl_id`. |
| Product currency | `product.product.currency_id` / `product.template.currency_id` | Many2one to `res.currency`; use the effective product catalogue currency in the configured company. Do not infer currency from an amount. |
| Catalogue price | `product.product.lst_price`; based on `product.template.list_price` plus `product.product.price_extra` | Use the matched sellable variant's effective public Sales Price in its own UoM and configured company currency. Odoo computes the variant price from template `list_price` plus its normal attribute price extras; do not read only the template base where a variant extra applies. Do not provide partner, alternate-UoM, date, or pricelist-rule context to this catalogue-price read. |
| Available quantity | `product.product.free_qty` | Choose this field for `TrustedProduct.available_quantity`. |
| Quantity on hand | `product.product.qty_available` | Do not map to `available_quantity`: it includes stock already reserved. |
| Forecast quantity | `product.product.virtual_available` | Includes planned incoming/outgoing stock; it is not current free stock and is not used for the validation contract. |
| Quant-level available quantity | `stock.quant.available_quantity` | Per-quant quantity after reservation; do not sum rows ad hoc across locations/lots. Use the product-level scoped `free_qty` computation. |
| Warehouse scope | `stock.warehouse` `company_id`, `lot_stock_id`; JSON-2 context | Configure one explicit Odoo company and warehouse. Send `allowed_company_ids=[company_id]` and `warehouse=warehouse_id` in context. Do not rely on the Odoo UI's active company or an implicit all-warehouse total. |

**Inventory ruling:** map `free_qty`, not `qty_available` or a sum of `stock.quant.available_quantity`. Odoo's 19.0 stock code computes `free_qty` from on-hand quantity minus reserved and expired-unreserved quantity, in the product's unit of measure. In the disposable probe, confirming a synthetic sale for two of ten units produced `free_qty=8` while `qty_available=10`. The configured company and warehouse context define which locations contribute; the adapter must reject missing or invalid scope instead of silently reading another company's stock. Requested and available quantities must use the product's Odoo unit of measure; Phase 9 supports the same unit only and does not perform implicit unit conversion.

At approval processing, the live adapter participates in the existing deterministic validation. Immediately before ERP creation, it repeats the exact customer/product/active/currency/price/stock checks against current Odoo data. Missing/archived customer or SKU, currency drift, price outside policy, or insufficient current `free_qty` prevents the write. The order remains the approved OpsFlow snapshot: provider data can block it but cannot silently rewrite the approved price, quantity, or customer.

### Sales order

| Concern | Odoo 19 model/field | Phase 9 decision |
| --- | --- | --- |
| Order | `sale.order` | Create a standard sales order with one or more `order_line` One2many commands. The local JSON-2 probe created a quotation using only explicit `partner_id` and one `order_line` command; use configured company/pricelist defaults explicitly in the real setup. |
| Customer | `partner_id` | Set to the trusted `res.partner` ID. Odoo supplies invoice/shipping addresses from that partner unless explicitly configured otherwise. |
| Line | `sale.order.line` | Create through `order_line: [[0, 0, {product_id, product_uom_qty, product_uom_id, name, price_unit}]]`. The live probe confirmed a line can also default its name and unit from the product. The implementation should still send the validated SKU, quantity, UoM, and approved unit price explicitly. |
| Customer PO | `client_order_ref` | Store the approved PO number as the customer's reference. It is not the idempotency key. |
| Delivery request | `commitment_date` | Map the approved requested delivery date when present. Do not map it to `validity_date`, which is quotation expiration. |
| Currency and pricelist | `pricelist_id` → read-only `currency_id` | Use the one configured base/default sales pricelist to establish the demo sales-order currency and normal Sales setup. Verify its currency matches the approved OpsFlow order. The configured pricelist must have no custom product, category, customer, quantity, date, discount, or formula rules that change the approved line price. Never assume a raw amount changes the order currency. |
| Confirmation | `action_confirm` | Confirm the sales order before returning success. |
| External receipt | `sale.order.id`, `sale.order.name` | Persist Odoo's integer record ID and sequence name (the probe returned ID `1`, name `S00001`). The bridge's immutable OpsFlow key is the cross-system idempotency identity. |

The canonical trusted catalogue price is the variant's effective public Sales Price (`product.product.lst_price`, from template `list_price` plus normal variant price extras). Existing deterministic validation compares the submitted PO price against that trusted price under OpsFlow's existing price policy. The created and confirmed order uses the approved line `submitted_price`, because that is the PO value accepted by deterministic validation and human approval; the configured base/default sales pricelist primarily establishes currency and must not introduce a competing rule. The OpsFlow total is the decimal sum of approved quantity × submitted unit price, before Odoo tax; HubSpot receives this approved OpsFlow total, not Odoo's tax-inclusive `amount_total`. Odoo applies the configured company/product taxes independently.

The mandatory demo uses one configured company, one currency, and one configured base/default sales pricelist with no custom pricing rules. Clean-clone setup validation must fail if the selected pricelist contains rules inconsistent with this contract; the bridge must fail closed if its configured demo-pricelist invariant is violated. Do not evaluate or approximate Odoo's dynamic pricing engine.

**Quotation-versus-confirmed ruling:** create and confirm a sales order. The roadmap outcome is that approval authorizes the downstream business write and the Phase 9 lifecycle reaches `COMPLETED` only after ERP and CRM synchronization; leaving an unconfirmed quotation would not demonstrate that approved execution boundary. Confirmation can trigger Odoo procurement and delivery behavior, so the mandatory demo uses only synthetic data in the local Community database.

## 6. Odoo bridge and at-most-one ERP order

A tiny Odoo 19 addon is practical: Odoo's documented transaction boundary explicitly recommends a server-side model method when several writes must commit or roll back together, and the JSON-2 API exposes model methods. The addon scope is limited to:

- an immutable nullable `sale.order.opsflow_order_id` string containing the canonical OpsFlow UUID;
- a database unique constraint on that field (multiple nulls remain valid for orders created outside OpsFlow);
- one narrow model method, conceptually `sale.order.create_or_get_opsflow_sale_order(...)`;
- bounded input validation and a receipt containing only `opsflow_order_id`, sale-order integer ID, sale-order name, and confirmed state.

The bridge performs lookup, create, and `action_confirm` in one JSON-2 request/transaction. If the key already exists, it verifies the order corresponds to the same immutable approved payload and returns the existing receipt; it does not create another order or rewrite unrelated Odoo fields. If confirmation fails, the Odoo request transaction rolls the create back. A different payload under the same OpsFlow UUID is an idempotency conflict for reconciliation.

The database unique constraint is the final concurrency guard. Two calls racing for one UUID may cause one caller to receive a uniqueness error; OpsFlow classifies that result as an uncertain outcome and retries the same bridge method in a fresh JSON-2 transaction. That lookup sees the winner and returns its existing receipt. An existing record is reusable only when its trusted customer, PO reference, currency, requested date, and ordered product/quantity/UoM/approved-price lines match the immutable approved order and its Odoo state is confirmed; a payload or state mismatch requires reconciliation. The guarantee is one logical record, not one successful HTTP response.

| Option | Assessment |
| --- | --- |
| A. Client search, then ordinary create | Unsafe by itself. Search and create are separate JSON-2 transactions, so concurrent callers can both observe no row and create two sales orders. |
| B. Unique field plus ordinary create calls | A database constraint blocks duplicate rows, but callers still have to recover a lost response, handle a collision, coordinate confirmation, and avoid leaving an unconfirmed order across separate calls. |
| C. Unique field plus one atomic bridge method | Recommended. One database constraint protects concurrency; one method owns lookup/create/confirm and returns a bounded receipt. A later call with the same UUID converges on the same order after timeout, lost response, or worker restart. |

Do not add a general Odoo connector framework, queue, webhook, or synchronization engine to this addon.

## 7. HubSpot model, authentication, and API

### Authentication and version

Use a HubSpot **Service Key** as a Python-only bearer credential for the developer/test account. HubSpot documents that the creator needs Developer Tools access and can grant a key only scopes they already hold; the key receives only its selected scopes. Request the minimum Company/Deal write access and any permission needed for their association. The CRM object APIs document scope names `crm.objects.companies.write` and `crm.objects.deals.write`, but do not assume those labels fully describe Service Key permission controls: verify the exact grants offered and accepted in the selected account. The `2026-09` write-validation note identifies `CRM_ASSOCIATIONS_WRITE_ACCESS` for user-level OAuth and says that association rule does not affect portal-level app tokens; the Associations guide does not establish a distinct Service Key requirement. Verify actual association access in the developer test account. Create CRM properties through account setup, keeping schema-write access off the runtime key. Do not grant Contact, marketing, webhook, or broad read/write scopes. See [Service Keys](https://developers.hubspot.com/changelog/service-keys) and the [current scope reference](https://developers.hubspot.com/docs/apps/developer-platform/build-apps/authentication/scopes).

Target the current date-based Company, Deal, and Associations APIs, intending to use `2026-09` wherever the endpoint is available. Exact paths, Deal object-type representation, and request shapes remain live setup gates as recorded in Section 3; rendered examples and prose are not account acceptance evidence and are insufficient to freeze those contracts. API IDs are opaque strings and must not be parsed as 32-bit integers.

Service Keys are documented for Developer Platform Projects version 2026.09 or later. Whether key creation is enabled in the selected developer test account remains a live setup gate.

A single order needs three CRM mutations: Company upsert, Deal upsert, and one Deal–Company association. A Company or Deal ID becomes an OpsFlow receipt only after the terminal-success rule below; an HTTP acceptance or nonterminal batch response is not a receipt. OpsFlow does not need a search-then-create call. After a lost response, use the verified completion mechanism; repeat a unique-key upsert only when the selected API's contract makes that replay safe.

### Narrow data model

**Company — one per trusted Odoo customer**

- Built-in `name`: trusted Odoo partner name.
- Custom `opsflow_customer_reference`: immutable unique property (`hasUniqueValue=true`); value comes only from the exact Odoo `res.partner.ref`.
- No email addresses, contacts, Gmail senders, or unrelated business fields.

**Deal — one per OpsFlow order**

- Built-in `dealname`: bounded readable name from approved PO number and short OpsFlow order ID.
- Built-in `amount`: approved OpsFlow line total as a decimal string, in the one configured portal currency.
- Built-in `pipeline` and `dealstage`: configured integration pipeline and initial stage IDs. Tests must use the account's actual internal IDs; labels are not API IDs.
- Custom `opsflow_currency`: ISO currency code, preserved as a narrow text property.
- Custom `opsflow_po_number`: approved customer PO reference.
- Custom `opsflow_order_id`: immutable unique property (`hasUniqueValue=true`); value is the canonical OpsFlow UUID.
- Company association: default unlabeled Deal → Company relationship through the selected date-based Associations API; exact path is a live setup gate.

OpsFlow sends only these managed properties. It does not read HubSpot records to validate a customer or make approval decisions. CRM values never become trusted ERP/business reference data. During incomplete sync, OpsFlow owns the configured initial pipeline/stage and sends the same values on retry. After `COMPLETED`, Phase 9 performs no further sync, so HubSpot users own later sales-stage progression.

**Currency and cost ruling:** HubSpot documents that its native deal Currency/exchange-rate behavior requires Starter, Professional, or Enterprise features and multiple-account-currency setup. Keep the mandatory free demo to one configured currency that matches the Odoo company/pricelist and HubSpot portal currency. Store the ISO code in `opsflow_currency`; use `amount` only after a setup check confirms that matching currency. Do not convert currency or require a paid HubSpot subscription. A free developer test account currently offers a 90-day Enterprise trial, which is optional sandbox convenience and not a mandatory runtime dependency. HubSpot's current default-deal properties are documented [here](https://knowledge.hubspot.com/properties/hubspots-default-deal-properties).

**Account validation:** before live sandbox writes, create the two unique properties, the PO and currency properties, and select the account’s built-in default sales pipeline plus its configured initial stage ID; exercise the Service Key's actual write and association permissions. Check that no account-specific conditional required fields or association restrictions reject the payload. The `2026-09` release enforces configured validation and permission rules on CRM writes. An account configuration rejection does not cause Python to invent extra CRM records or loosen OpsFlow's rules.

Contacts, custom objects, marketing automation, HubSpot workflows, and HubSpot-as-source-of-truth behavior remain out of scope. Gmail sender identity is transport provenance only and must never create or identify a Company or Contact.

## 8. Durable OpsFlow synchronization model

M9B should add the smallest durable table, `order_syncs`, with one row per approved order:

| Field | Purpose |
| --- | --- |
| `order_id UUID PRIMARY KEY REFERENCES orders(id)` | Enforces one sync intent per OpsFlow order. Insert in the approval transaction. |
| `claim_token UUID NULL`, `claim_expires_at TIMESTAMPTZ NULL` | Fenced ownership lease. Both null means unclaimed. |
| `attempt_count SMALLINT NOT NULL` | Number of retryable provider outcomes (errors or nonterminal pending states) or expired-lease recovery events in the current automatic retry generation. Increment when recording that outcome, not on a successful claim or a clean budget yield. |
| `retry_generation SMALLINT NOT NULL` | Count of explicit human retries; audit events preserve previous generation outcomes. |
| `next_attempt_at TIMESTAMPTZ NOT NULL` | Earliest eligible automatic retry time. |
| `odoo_sale_order_id BIGINT NULL`, `odoo_sale_order_name TEXT NULL` | Minimal Odoo receipt; persist before any HubSpot call. |
| `hubspot_company_id TEXT NULL` | Minimal Company receipt. |
| `hubspot_deal_id TEXT NULL` | Minimal Deal receipt. |
| `hubspot_pending_operation_ref TEXT NULL` | Optional bounded opaque operation handle only if the verified HubSpot completion contract requires polling across invocations; never store its raw response. |
| `hubspot_association_confirmed_at TIMESTAMPTZ NULL` | Durable confirmation of the required association. |
| `in_flight_step` | Nullable enum: `ODOO_LOOKUP`, `ODOO_BRIDGE`, `HUBSPOT_COMPANY`, `HUBSPOT_DEAL`, or `HUBSPOT_ASSOCIATION`. Set before each external operation and cleared with its receipt; a surviving value identifies a possibly committed operation after a crash. |
| `last_failure_step`, `last_failure_code` | Bounded enums describing the latest failed provider step. No raw error body or stack trace. |
| `last_attempt_at`, `created_at`, `updated_at` | Recovery scheduling and operational inspection timestamps. |

Add check constraints for paired claim token/expiry, nonnegative counters, and valid bounded failure codes. Add unique indexes for each non-null Odoo sales-order ID and HubSpot Deal ID so two local orders cannot accidentally claim the same order receipt. Do not unique-index `hubspot_company_id`: multiple OpsFlow orders for one trusted customer intentionally share its Company. HubSpot's unique `opsflow_customer_reference` property enforces that external identity. Use the provider's native type where stable (Odoo integer ID) and opaque text for HubSpot IDs. Database status is derived from the existing order state, lease fields, `next_attempt_at`, and receipts; do not create a second sync-state machine.

Persist receipts and checkpoint timestamps only. Do not store raw Odoo or HubSpot response JSON, credentials, sender/customer email addresses, or provider stack traces. Provider error messages are reduced to a bounded internal code and safe operational note.

The Phase 8 notification row/claim design supplies proven principles: row-per-work-item, locked claim, skip-locked concurrency, expiring lease, finite retry count, local receipt before next side effect, and bounded failure data. Reuse those principles and simple repository conventions; do not generalize notification delivery into a shared engine.

## 9. Lifecycle and state semantics

- Approval is the authorization boundary. An order in any state other than `APPROVED` cannot start a sync write.
- Durable sync intent is inserted atomically with the `READY_FOR_APPROVAL → APPROVED` transition and approval audit event. If insert or commit fails, the whole local transaction rolls back and approval does not become durable.
- `APPROVED → SYNCING` occurs when the backend successfully claims the first job, not when the intent is inserted and not just before the first provider call. A committed `APPROVED` order always has durable work; a crashed worker leaves a visible `SYNCING` order and reclaimable lease.
- A retryable provider outcome records the failed/incomplete step, bounded code, and next-attempt time. Up to three retryable provider outcomes (including nonterminal pending states) or expired-lease recovery events are allowed per retry generation, with 30-second then 2-minute base delays. A successful claim that yields only because of the request budget does not consume a retry attempt. Schedule the next retry no earlier than `Retry-After`: use the later of that value and the base delay. When that generation is exhausted, transition `SYNCING → FAILED_RETRYABLE`; operator review is required. The existing human Retry operation calls `Order.retry()`, returns to the recorded `SYNCING` origin, increments `retry_generation`, resets the per-generation attempt count, and preserves every successful receipt.
- A permanent mismatch or unrecoverable idempotency conflict transitions `SYNCING → FAILED_FINAL` and requires manual reconciliation. Do not add transitions.
- No-work, retry-wait, in-progress, retryable-failure, final-failure, and completion outcomes returned to n8n are bounded values; provider details remain inside OpsFlow.

## 10. Transaction boundaries

| Boundary | Atomic local/remote work |
| --- | --- |
| Approval | Lock/check current order and ETag; transition to `APPROVED`; append approval event; insert exactly one `order_syncs` row. Commit all or none in one PostgreSQL transaction, reusing Phase 8's durable-intent boundary. |
| Claim / first SYNCING | Lock one eligible order-sync row and its order, using `FOR UPDATE SKIP LOCKED`; validate state and retry time; transition `APPROVED → SYNCING` on first claim; append start/resume event; assign random claim token and expiry; commit before provider calls. A successful claim alone does not consume the retry attempt count. |
| Provider call | In a short PostgreSQL transaction, require the current unexpired claim token and persist the bounded `in_flight_step`; commit. Then call the provider with no PostgreSQL transaction held and a bounded timeout. |
| Persist receipt | Re-lock sync row; require the current unexpired claim token; persist the receipt/checkpoint and clear `in_flight_step`. Keep the same lease while this claimed run continues; clear the lease on completion or when recording a failure/retry wait. Commit the Odoo receipt before starting HubSpot. |
| Completion | In a short transaction, verify all required receipts and the current claim token; transition `SYNCING → COMPLETED`; append completion event; clear the lease. Commit together. |

A stale worker may finish an external call after its lease expires. Its token cannot write a local receipt or change order state. A new worker repeats the same idempotent provider operation, then persists the winning response. A database failure after provider success is safe because the provider key, not the lost local acknowledgement, determines the same remote record.

## 11. Claim, lease, and retry model

One endpoint call claims at most one due order. Use the database clock for eligibility and lease expiry, a random UUID claim token as a fencing value, and a five-minute lease. The planned Odoo lookup and bridge timeouts are 20 seconds each and each individual HubSpot call timeout is 15 seconds; these are per-call bounds only, not a promise that a full serial path or verified HubSpot status mechanism fits inside one request. M9E may tune them from measured behavior without changing the recovery contract.

An order is claimable when:

1. it is `APPROVED`, has one uncompleted sync row, and has no live claim; or
2. it is `SYNCING`, the prior lease expired or retry time is due, and its current automatic retry generation has attempts remaining.

Use one row lock with `skip_locked` so concurrent scheduler requests claim distinct rows or return no work. When reclaiming an expired lease, record one retryable expiry event; if it exhausts the generation, move to `FAILED_RETRYABLE` instead of issuing another claim. Otherwise assign a new token and repeat the persisted `in_flight_step` with the same provider identity. A clean budget yield releases its claim without incrementing retry count. When any final allowed retryable outcome exhausts the generation, move `SYNCING → FAILED_RETRYABLE`, store `WORKER_LEASE_EXHAUSTED` for an expired worker or the bounded provider code, clear the lease, and preserve receipts plus the uncertain in-flight step; the order cannot remain stuck in `SYNCING`. Thus repeated worker crashes pause for human Retry rather than exceeding the retry-generation limit. Every local write after a provider call checks the latest token and expiry. A stale token is rejected even if its former worker reports success.

Retryable network/timeout/429/5xx outcomes use the bounded three-attempt automatic generation. Set `next_attempt_at` to the later of the 30-second/2-minute base delay and the provider `Retry-After`; never retry before the provider-supplied time. Exceeding the generation pauses in `FAILED_RETRYABLE` for the existing operator Retry command. Permanent business/configuration failures do not burn all three attempts in a tight loop; record them as `FAILED_RETRYABLE` for operator correction and explicit Retry, or `FAILED_FINAL` when the approved order/external-key mapping cannot safely be reconciled. A human Retry starts a new generation and reuses the same order and provider keys.

`PENDING` or `PROCESSING` HubSpot batch states are represented as the same `HUBSPOT_COMPANY` or `HUBSPOT_DEAL` `in_flight_step`, with no receipt, and a bounded `PROVIDER_PENDING` retry schedule. If M9D verifies a poll handle, retain only the opaque handle and poll using the documented contract; otherwise schedule a later same-key replay/reconciliation only after M9D verifies that behavior is safe. Do not sleep or poll indefinitely in one request.

### Synchronous execute-next budget

`POST /v1/orchestration/order-sync/execute-next` remains the only claim-and-execute endpoint; Phase 9 adds no second claim endpoint or background worker. Each provider call keeps its bounded timeout, and one backend execution has a separate hard total-duration budget selected from measured M9E behavior. The backend never continues indefinitely inside one HTTP request. Before starting a provider call, it must have enough remaining budget for that call's configured maximum timeout and a bounded local receipt/checkpoint transaction. Once a provider returns a confirmed success, persist the receipt before ending the request; do not discard a successful receipt to meet the scheduling budget. If the remaining budget is insufficient for the next step, persist immediate eligibility, release the claim, and return a bounded `yielded` result with the authoritative order state. A later scheduler invocation reclaims the order and resumes from the first missing durable step. If a provider timeout leaves an uncertain outcome, retain its in-flight step and use the same stable identity on later recovery.

n8n's HTTP Request timeout must exceed the backend's total execution budget plus response margin, while remaining below the five-minute claim lease. The exact backend and n8n timeout values are operational parameters for M9E; the ordering above is the design invariant. Any bounded database operation needed to save a successful provider receipt must fit within the reserved checkpoint allowance.

## 12. Partial-success recovery

The runner checks persisted receipts before each operation:

1. No Odoo receipt: revalidate live Odoo data, then invoke the bridge with the same OpsFlow UUID.
2. Odoo receipt present: skip Odoo create/confirm.
3. No HubSpot Company ID: Company upsert with the same trusted Odoo customer reference; wait for terminal `COMPLETE` and exactly one matching successful result with a confirmed ID before persisting the Company receipt or proceeding.
4. Company receipt present, no Deal ID: Deal upsert with the same OpsFlow order UUID; apply the same terminal-result rule before persisting the Deal receipt or proceeding.
5. Company and Deal receipts present, association timestamp absent: repeat the default Deal → Company association.
6. All four checkpoints present: atomically transition to `COMPLETED`.

If Odoo succeeds and HubSpot fails, later runs start at Company upsert. If Company reaches terminal success and Deal fails, they start at Deal. If Deal reaches terminal success and association fails, they start at association. A `PENDING`/`PROCESSING` batch remains at its current HubSpot step with no receipt and cannot advance. Neither timeout nor local crash erases an earlier receipt. If a provider write committed but OpsFlow crashed before recording its ID, use the M9D-verified poll or safe same-key reconciliation contract to recover the confirmed result; never infer success from acceptance alone.

## 13. Failure model

The row stores only a bounded `failure_step` and `failure_code`:

| Failure condition | Internal category | Recovery |
| --- | --- | --- |
| Odoo/HubSpot credential rejected, missing scope, invalid base URL/database/company/pipeline/stage, account validation or association permission | `INTEGRATION_CONFIG` | Stop automatic retries; `FAILED_RETRYABLE`, fix configuration/account permissions, then use existing human Retry. |
| Provider connection failure or timeout before a known response | `PROVIDER_UNAVAILABLE` | Outcome may be uncertain; repeat the same stable-key operation. Automatic bounded retry, then `FAILED_RETRYABLE` for review. |
| Provider 429 | `PROVIDER_RATE_LIMIT` | Schedule no earlier than `Retry-After`; resume only the missing step. |
| Provider 5xx | `PROVIDER_UNAVAILABLE` | Bounded automatic retry; if exhausted, `FAILED_RETRYABLE`. |
| Malformed/invalid success response | `PROVIDER_INVALID_RESPONSE` | Do not write a guessed receipt. Treat mutation as uncertain and repeat with the same idempotency identity; if unresolved, `FAILED_RETRYABLE` for reconciliation. |
| HubSpot Company/Deal batch is `PENDING` or `PROCESSING` | `PROVIDER_PENDING` | Keep the same `in_flight_step`, persist no ID receipt, and use only the M9D-verified status/result or safe same-key reconciliation contract on a bounded later attempt. |
| HubSpot Company/Deal batch is `CANCELED` | `PROVIDER_REJECTED` | Failure with no receipt; preserve earlier receipts and apply bounded retry/review policy. |
| HubSpot HTTP 207 contains a per-item validation/error result | `INTEGRATION_CONFIG` or `PROVIDER_REJECTED`, based on the bounded error classification | Do not persist a receipt; fix configuration or require operator review. Never treat the HTTP status as total success. |
| HubSpot HTTP 207 or batch body is contradictory, malformed, or has no unambiguous terminal result | `PROVIDER_INVALID_RESPONSE` | No receipt; preserve the step as uncertain and use only the verified completion/reconciliation mechanism. |
| Trusted Odoo customer missing, archived, or ambiguous | `TRUSTED_CUSTOMER_MISSING` or `TRUSTED_CUSTOMER_AMBIGUOUS` | Do not create Odoo or CRM data. `FAILED_RETRYABLE`; correct the trusted mapping and explicitly retry. |
| Product/SKU missing, archived, ambiguous, or currency changed | `TRUSTED_PRODUCT_MISSING` or `TRUSTED_PRODUCT_CHANGED` | Do not create external records. `FAILED_RETRYABLE`; correct Odoo master data and explicitly retry. |
| Current `free_qty` below approved quantity | `INVENTORY_INSUFFICIENT` | Do not create the order. `FAILED_RETRYABLE`; replenish/resolve stock then explicitly retry. |
| Provider rejects a write for a fixable account/business configuration reason | `PROVIDER_REJECTED` | No automatic retry loop for a non-transient rejection. `FAILED_RETRYABLE`; operator fixes provider configuration and retries. |
| Final worker lease expires before a result can be persisted | `WORKER_LEASE_EXHAUSTED` | Preserve receipts and in-flight step, move to `FAILED_RETRYABLE`, and require the existing human Retry to begin a new automatic generation. |
| Odoo unique collision with matching OpsFlow UUID | `IDEMPOTENCY_REPLAY` | Fresh bridge call reads and returns the existing order receipt. |
| Odoo unique collision with a different payload/state, or external ID mismatch | `IDEMPOTENCY_CONFLICT` | `FAILED_FINAL`; reconcile the mapping manually; never mint a replacement OpsFlow key. |
| HubSpot Company/Deal/association failure after Odoo succeeded | Provider category plus `failure_step=HUBSPOT_COMPANY`, `HUBSPOT_DEAL`, or `HUBSPOT_ASSOCIATION` | Preserve all receipts; retry only the missing CRM operation. |
| Confirmed permanent order/identity corruption or unsupported external state | `RECONCILIATION_REQUIRED` | `FAILED_FINAL`, operator reconciliation; no automatic mutation. |

Provider-specific status, body, stack trace, and credentials never become domain state or API output. Logs may record provider name, operation, order ID, attempt/generation, status family, and correlation ID if bounded and free of secrets/PII.

## 14. Idempotency and convergence

| External mutation | Stable key / guard | After request loss or concurrent duplicate |
| --- | --- | --- |
| Odoo sales-order create + confirm | Unique immutable `sale.order.opsflow_order_id` plus one atomic bridge call | Repeat bridge call with the same OpsFlow UUID. Existing row is returned; a concurrent insert collision is resolved by a fresh call. Confirmation and creation roll back together on failure. |
| HubSpot Company create/update | Unique `opsflow_customer_reference` plus the selected date-versioned upsert contract | Use the M9D-verified poll or safe same-key reconciliation after lost responses. Persist no receipt before terminal `COMPLETE`, exactly one matching success, and a confirmed HubSpot ID; the unique property is the logical-record convergence guard. |
| HubSpot Deal create/update | Unique `opsflow_order_id` plus the selected date-versioned upsert contract | Use the M9D-verified poll or safe same-key reconciliation after lost responses. Persist no receipt before terminal `COMPLETE`, exactly one matching success, and a confirmed HubSpot ID; the unique property is the logical-record convergence guard. |
| HubSpot Company–Deal relation | Stable pair of persisted HubSpot IDs plus default-association `PUT` | Repeat the same `PUT`; it targets the same pair and converges on the single required default relationship. |

Connection drop before a request, timeout while commit is possible, lost response after commit, and crash before local receipt persistence all retain the same provider identity. For HubSpot, use a verified operation-status contract or a documented and tested safe same-key reconciliation; do not blindly resubmit an asynchronous write. A database lease prevents normal concurrent execution; Odoo uniqueness and HubSpot unique properties protect the remaining overlap after lease expiry. Execution is at-least-once; the guarantees concern logical records and durable receipts.

## 15. n8n role and OpsFlow API boundary

Use one proposed sanitized workflow named `opsflow-order-sync`:

`Schedule Trigger → authenticated OpsFlow HTTP Request → Switch on bounded backend result → end`

n8n calls a single proposed `POST /v1/orchestration/order-sync/execute-next` endpoint. The backend claims and executes/resumes at most one safe progression inside that call, subject to its bounded total-execution budget. The response contains only a bounded result such as `completed`, `worked`, `yielded`, `no_work`, `retry_wait`, or `needs_review`, the OpsFlow order ID when applicable, and the authoritative order state. Provider IDs may be omitted from the scheduler response; they remain in authenticated OpsFlow read/audit paths.

A single claim-then-execute workflow would add a token handoff and a second endpoint without improving provider correctness: the one endpoint can claim under a short transaction, call providers outside the transaction, and fence receipt writes by its internal token. The database remains the concurrency authority.

n8n must not hold Odoo or HubSpot credentials, construct provider payloads, decide retry policy, choose or mutate business state, or create external records. Reuse Phase 7/8 orchestration service authentication and sanitized workflow conventions. Provider credentials stay in the Python runtime's ignored environment configuration.

## 16. Security and cost/local demo

### Security

- Odoo: use a dedicated local integration user with only partner/product/stock read access, the bridge method, and necessary sale-order create/confirm rights. Store its API key in ignored environment configuration; the key inherits the account's ACLs and must never appear in source, logs, n8n credentials, workflow exports, or API responses.
- Odoo API keys expire by design: manual key creation requires a duration and Odoo 19 documents a maximum of three months. Clean-clone instructions must document regeneration/rotation. Update only ignored runtime configuration, verify the replacement key works, then revoke the old key. Do not automate key rotation in Phase 9. See [Odoo 19 API key documentation](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html).
- HubSpot: create a scoped Service Key in the test account, store it in an ignored environment variable, and expose it only to Python. Restrict it to Company/Deal writes and the required association permission. Rotate/delete it through HubSpot account controls.
- OpsFlow API: reuse the existing authenticated orchestration boundary and server-resolved service actor. Return bounded error codes; never forward provider response bodies or secrets.
- Use synthetic customers, products, orders, PO numbers, and HubSpot records only. No email address is necessary in either provider payload.

### $0 mandatory development cost

Local Odoo 19 Community in Docker and a free HubSpot developer/test account are the required sandbox path. A HubSpot developer test account is isolated, free, and periodically resets; the optional 90-day Enterprise trial can support feature testing without a paid subscription. The reference demo uses one portal currency to avoid the paid multi-currency feature. No Odoo Online plan or paid account is required. HubSpot's general Service Key rate bucket and this specific test account's write permissions still require account-side verification.

## 17. Future adversarial test matrix

M9B–M9E must use provider fakes for deterministic failure injection and isolated local/test accounts for external boundary checks. No automated suite may call a live production ERP/CRM account.

| Scenario | Required observable result |
| --- | --- |
| Non-`APPROVED` order cannot sync | No lease, provider call, external record, or state transition. |
| Duplicate sync-start/execute request | One intent and at most one active owner; same stable provider keys on replay. |
| Concurrent claim of one order | Exactly one valid claim token; a second worker gets no claim. |
| Worker crash before provider call | Expired lease is reclaimed; no state or receipt is lost. |
| Lease expiry while provider call is in flight | Stale token cannot persist a receipt; next worker repeats the same idempotent key. |
| Stale claim token writes after reclaim | Database rejects receipt/state mutation. |
| Odoo customer absent, archived, or ambiguous | No Odoo order or HubSpot object is created; bounded trusted-data failure. |
| Odoo product absent/archived or currency mismatch | No external order is created. |
| Odoo variant has a normal `price_extra` | Trusted catalogue price equals its effective public `product.product.lst_price`; it includes the template base plus variant extras. |
| Configured Odoo default pricelist contains custom pricing rules | Clean-clone/setup validation fails closed; Phase 9 does not evaluate or apply dynamic price rules. |
| Odoo insufficient `free_qty` | No sales order is created; `qty_available` is not substituted. |
| Odoo timeout before mutation | Same bridge key may be retried without a duplicate. |
| Odoo create/confirm commits but response is lost | Retry returns the same ID/name; one confirmed order. |
| Duplicate Odoo mutation attempt | Database uniqueness leaves one logical order; matching retry returns its receipt. |
| Odoo create succeeds but confirmation fails | The bridge transaction leaves no partial unconfirmed OpsFlow order. |
| HubSpot Company write fails after Odoo success | Odoo receipt remains; retry starts at Company; no Odoo call. |
| HubSpot Deal write fails after Company success | Company receipt remains; retry starts at Deal. |
| HubSpot upsert returns `COMPLETE` and one matching successful result | Persist exactly the confirmed record ID, then allow the next business step. |
| HubSpot HTTP 207 returns `COMPLETE`, exactly one matching successful result, confirmed ID, and no item error | Persist that one receipt; 207 alone is not the decision. |
| HubSpot upsert returns `PENDING` or `PROCESSING` | No receipt and no next business step; resume the same durable step using only the M9D-verified status/reconciliation contract. |
| HubSpot upsert returns `CANCELED` | Fail the current step; persist no receipt. |
| HubSpot HTTP 207 includes per-item error/validation result | Map the item error to a bounded failure; persist no receipt and never treat 207 as whole-call success. |
| HubSpot HTTP 207/body is ambiguous or contradictory | `PROVIDER_INVALID_RESPONSE`; no receipt until safe reconciliation establishes one terminal matching result. |
| HubSpot response is lost after Company/Deal upsert | Use the verified poll/status link or documented safe same-key reconciliation; never infer completion or record an ID from acceptance alone. |
| Duplicate HubSpot retries | One Company per customer ref and one Deal per order ID. |
| Association failure or lost response | Retry same Deal–Company default PUT; persist confirmation only after success. |
| Provider 429 | Respect `Retry-After`; no rapid retry or lost receipt. |
| Provider 5xx/network interruption | Bounded retry and correct retryable/final outcome. |
| Execute-next budget is nearly exhausted | Do not start an operation without room for its timeout and receipt transaction; persist/release after the last checkpoint and return bounded `yielded` for the next scheduler call. |
| Repeated clean budget yields before a provider outcome | Preserve all receipts and do not consume the automatic retry-generation count. |
| Provider confirms success near the execution-budget boundary | Persist the receipt inside the reserved checkpoint budget before returning; a request budget does not discard confirmed success. |
| n8n request timeout configuration | Timeout exceeds backend budget plus response margin and remains below the five-minute lease. |
| Restart after each partial-success boundary | Resume from exactly the first missing checkpoint. |
| `COMPLETED` order is scheduled again | No claim and no provider mutation. |
| Human recovery from `FAILED_RETRYABLE` | Existing Retry returns to recorded `SYNCING` origin, increments retry generation, retains earlier receipts, and resumes the missing step. |
| HubSpot 2026-09 account validation/permission rejection | Safe bounded error; no secret or provider body exposed; operator can correct test-account setup. |
| Secrets absent from Git | Prospective Gitleaks scan of changed files passes; no credential fixture is committed. |
| Clean clone | Documented setup builds isolated Odoo addon/database and HubSpot test configuration using synthetic data and ignored credentials, without copying developer state. |

## 18. Clean-clone requirements

M9E must document and demonstrate from a clean checkout:

1. Start PostgreSQL, OpsFlow, n8n, and the disposable Odoo Community 19 instance without copying a primary database or credential volume.
2. Install/initialize only the documented Odoo Community modules, bridge addon, company, warehouse, one currency, the base/default sales pricelist without custom pricing rules, taxes, synthetic products, stock, customer references, and least-privilege integration user.
3. Create or select a free HubSpot developer test account; create its unique Company/Deal properties and configured pipeline/stage; create a Service Key using the minimum account permissions.
4. Place Odoo, HubSpot, and OpsFlow service credentials only in ignored local environment/credential stores. Document Odoo key expiration and the generate → update ignored runtime config → verify replacement → revoke old key procedure. Verify workflow exports contain no key values.
5. Apply committed migrations, import/publish the sanitized workflow, run deterministic provider-fake tests, then an explicitly enabled synthetic sandbox E2E.
6. Show the confirmed Odoo order, one HubSpot Company, one Deal, one association, durable OpsFlow receipts, and `COMPLETED` state.
7. Re-run the same order-sync request and prove no duplicate logical records appear. Explain that HubSpot test accounts periodically reset and how to recreate their synthetic setup.

The exact Odoo image digest, account setup screenshots/IDs, and account-specific HubSpot quota are M9E setup evidence, not facts established by this design probe.

## 19. Proposed Phase 9 milestones

| Milestone | Purpose and scope | Tests and observable acceptance | Explicit non-goals |
| --- | --- | --- | --- |
| **M9A — ERP/CRM Contract, Current-API Probe & Design** | Verify Odoo 19 Community and current HubSpot contracts; approve this design. | Source-backed findings, disposable Odoo probe, complete design review, linked documents and clean documentation checks. | Production code, migrations, adapters, n8n workflow, implementation plan. |
| **M9B — Durable Sync State, Claiming & Recovery Contract** | Add one durable sync row per approved order; atomically create intent with approval; add fenced claim/lease, bounded retries, receipts, failure codes, authenticated execute-next boundary. | PostgreSQL tests for approval atomicity, duplicate intent, concurrent claim, stale token, lease expiry, each domain transition, retry-generation recovery, budget yield without retry-count consumption, and receipt preservation at the execution-budget boundary. | Provider SDKs, external writes, Odoo addon, HubSpot records, n8n workflow. |
| **M9C — Odoo Trusted-Data + Idempotent ERP Adapter** | Implement Odoo 19 JSON-2 mapping to `BusinessDataProvider`; add the tiny `sale.order` uniqueness/bridge addon; preflight, create, confirm, and persist ERP receipt. | Provider-free contract tests and isolated Odoo Community tests for field mapping, `free_qty`, draft/confirmed lifecycle, concurrency, uncertain outcome, and no duplicate order. | HubSpot adapter, Gmail/Contact sync, general Odoo connector framework. |
| **M9D — HubSpot CRM Adapter & Partial-Success Recovery** | Implement Service Key configuration; create the two unique properties in a test account; target current date-based Company/Deal/association APIs, intending `2026-09` where supported; persist only terminal receipts. | Fake-backed timeout/429/5xx/207/nonterminal tests plus an isolated developer-test account probe that confirms exact Company and Deal paths/object types, association path, `idProperty` placement, Service Key permissions, terminal completion/poll/replay contract, unique upsert, and receipt IDs. | Contacts, marketing automation, HubSpot business policy, paid subscription requirement. |
| **M9E — n8n Sync Orchestration + Full Sandbox/Clean-Clone E2E** | Add one sanitized scheduled `opsflow-order-sync` workflow that invokes the OpsFlow execute-next endpoint; document clean reconstruction. | Clean clone runs synthetic approved order to confirmed Odoo + HubSpot Company/Deal/association + `COMPLETED`; replay and partial recovery show no duplicate logical records. | Provider calls from n8n, credentials in workflow, real customer data, cloud hosting. |
| **M9F — Independent Whole-Phase-9 Audit** | Independently audit contracts, code, migrations, tests, external sandbox evidence, privacy, cost, and docs. | Findings closed with evidence; required scenarios and clean-clone acceptance pass; audit/status documents report commit and tree state. | New feature scope or unapproved architecture changes during audit. |

M9A is COMPLETE following human review. M9B is IN PROGRESS under its approved implementation plan; M9C–M9F remain NOT STARTED.

## 20. User-owned setup gates and accepted limitations

### Still requiring interactive account verification

- Create/select the free HubSpot developer/test account and confirm Service Keys are enabled for it.
- Create the Service Key and verify its exact Company, Deal, and association permissions in the selected account.
- Exercise and record the exact Company path, Deal path and object-type representation, Association path, and `idProperty` placement against that account; do not freeze an adapter contract from documentation alone before account acceptance.
- Verify how the selected date-versioned Company/Deal API reports `PENDING`, `PROCESSING`, `CANCELED`, and `COMPLETE`, how to reconcile nonterminal work, and how HTTP 207/per-item errors are returned. Persist no receipt until one terminal successful matching result and confirmed record ID are observed.
- Configure the unique properties and pipeline/stage IDs; check account-side required fields, write rules, and association permissions.
- Record the Service Key rate-limit bucket/headers and confirm the configured portal currency.
- Create an Odoo least-privilege user/key and configure the target company, warehouse, one currency, rule-free default pricelist, and taxes in a clean-clone sandbox. Document key expiration and rotation.

No credentials or provider records were created outside the disposable local Odoo database during M9A. No HubSpot account was accessed.

### Accepted limitations

- Initial Phase 9 demo supports one explicit company/warehouse, one currency, and one base/default sales pricelist with no custom product/category/customer/quantity/date/discount/formula price rules. The product variant's effective public Sales Price is the trusted catalogue price; the pricelist establishes matching sales-order currency and normal Sales setup. Customer-specific/dynamic Odoo pricelist evaluation is not supported. Supporting it later requires an explicit extension to the trusted-data lookup contract with the pricing context Odoo needs; it must not be added implicitly. No implicit cross-company stock aggregation, unit conversion, or currency conversion.
- Odoo inventory is a scoped live validation snapshot. Stock can change after lookup; Odoo's standard confirmation path may create procurement/delivery work. Future addon tests must document stock reservation semantics for the selected local setup.
- A free HubSpot developer test account is resettable and its optional Enterprise trial is time-limited. The clean-clone procedure must reconstruct synthetic state.
- The bridge and unique keys guarantee at-most-one logical record per stable identity while calls are at-least-once. They do not make PostgreSQL and remote provider commits one distributed transaction.
- `FAILED_RETRYABLE` uses the existing human Retry operation after a bounded automatic generation. Editing the approved OpsFlow order after approval is not introduced by Phase 9. A Deal must not be advanced by a human while its OpsFlow synchronization is incomplete, because an idempotent replay sends the same configured initial stage.

### Verification evidence available to M9A

- Repository preflight matched main/HEAD to the expected Phase 8 merge SHA and found no Phase 9 application adapter, migration, or workflow.
- Local disposable Odoo runtime: Community image `odoo:19.0`, server `19.0-20260926`; JSON-2 API key authentication returned HTTP 200.
- Odoo `fields_get` and synthetic create/confirm probe verified model/field names, relation shape, sale line One2many command, `client_order_ref`, confirmed state `sale`, and returned sale-order ID/name. Inventory probe observed `free_qty=8` and `qty_available=10` after reserving two units from ten.
- HubSpot findings are documentation-backed only; no live account, credential, or write was used.
- Documentation/static checks, prospective secret scan, commit, and push are recorded in the M9A closeout report after they are run.

## Primary provider references

- [Odoo 19 External API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html)
- [Odoo 19 Sales Order source](https://github.com/odoo/odoo/blob/19.0/addons/sale/models/sale_order.py)
- [Odoo 19 Sales Order Line source](https://github.com/odoo/odoo/blob/19.0/addons/sale/models/sale_order_line.py)
- [Odoo 19 Product Template source](https://github.com/odoo/odoo/blob/19.0/addons/product/models/product_template.py)
- [Odoo 19 Product Variant source](https://github.com/odoo/odoo/blob/19.0/addons/product/models/product_product.py)
- [Odoo 19 product variants and price extras](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/products/variants.html)
- [Odoo 19 pricelist rules](https://www.odoo.com/documentation/19.0/applications/sales/sales/products_prices/prices/pricing.html)
- [Odoo 19 Stock Product Quantity source](https://github.com/odoo/odoo/blob/19.0/addons/stock/models/product.py)
- [HubSpot Service Keys](https://developers.hubspot.com/changelog/service-keys)
- [HubSpot legacy private-app creation sunset](https://developers.hubspot.com/changelog/legacy-private-app-creation-sunset)
- [HubSpot date-based API versioning](https://developers.hubspot.com/changelog/introducing-date-based-api-versioning)
- [HubSpot Fall 2026 developer update](https://developers.hubspot.com/changelog/fall-2026-spotlight)
- [HubSpot legacy API support notice](https://developers.hubspot.com/changelog/legacy-apis-and-legacy-apps-whats-going-unsupported-and-when)
- [HubSpot Companies batch upsert](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/companies/batch/upsert-companies)
- [HubSpot Deals batch upsert](https://developers.hubspot.com/docs/api-reference/latest/crm/objects/deals/batch/upsert-deals)
- [HubSpot record associations](https://developers.hubspot.com/docs/api-reference/latest/crm/associations/associate-records/guide)
- [HubSpot unique properties](https://developers.hubspot.com/changelog/unique-properties-for-contacts)
- [HubSpot CRM API write validation](https://developers.hubspot.com/changelog/crm-api-write-validation-enforcement)
- [HubSpot Developer Platform Basics](https://developers.hubspot.com/developer-platform-basics)
- [HubSpot API usage guidelines and limits](https://developers.hubspot.com/docs/developer-tooling/platform/usage-guidelines)
- [HubSpot default Deal properties and currency availability](https://knowledge.hubspot.com/properties/hubspots-default-deal-properties)
