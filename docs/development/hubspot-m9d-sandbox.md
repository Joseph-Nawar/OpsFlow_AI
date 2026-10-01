# HubSpot M9D Synthetic Sandbox

This guide records the verified Task 1 provider contract and M9D implementation
test procedure for the synthetic test portal. It contains no credentials.
Provider-free M9D implementation evidence is available in the repository test
suites. The opt-in live coordinator suite also passed after the local runtime
credential was refreshed; all synthetic Company and Deal records created by
that suite were archived.

## Account and access

- Target portal: `149461984`, account type `DEVELOPER_TEST`, currency `USD`.
- The configured key's `GET /integrations/v1/me` response exposes `portalId`;
  M9D must require the expected portal ID and fail closed before writes when it
  does not match.
- The human inspected Service Key settings and verified exactly these runtime
  grants: `crm.objects.companies.read`, `crm.objects.companies.write`,
  `crm.objects.deals.read`, and `crm.objects.deals.write`. Company, Deal, and
  association probe writes succeeded with these grants; no separate
  association permission was needed.
- Keep schema, portal validation, and pipeline administration on the separate
  setup/admin identity. The runtime key has no schema-write grants.
- Keep the Service Key in ignored runtime configuration only. Never place its
  value in source, tests, command output, logs, or reports. To rotate it,
  generate a replacement with the same verified minimum grants, update ignored
  runtime configuration, verify the replacement, and revoke the old key.

## Portal setup

The setup/admin identity created and verified these properties in portal
`149461984`:

| Object | Label | Internal name | Type | Unique |
| --- | --- | --- | --- | --- |
| Company | OpsFlow Customer Reference v2 | `opsflow_customer_reference_v2` | string/text | yes |
| Deal | OpsFlow Order ID | `opsflow_order_id` | string/text | yes |
| Deal | OpsFlow Currency | `opsflow_currency` | string/text | no |
| Deal | OpsFlow PO Number | `opsflow_po_number` | string/text | no |

`opsflow_customer_reference_v2` is the only approved M9D Company identity
property. Its value is the exact trusted Odoo `res.partner.ref`. Do not use,
repair, rename, delete, or fall back to the obsolete `opsflow_customer_reference`.

Human-verified Company creation has no extra required properties, associations,
or conditional logic. Deal creation requires only Deal name, Pipeline, and Deal
stage. Company, Contact, and Line-item associations are optional; no
conditional logic is configured. All pipeline rules are off.

The configured synthetic Deal pipeline is `default` (Sales Pipeline), and its
initial stage is `appointmentscheduled` (Appointment Scheduled). The stage
belongs to that pipeline and accepted the probe Deal. Portal currency is USD.
Do not add currency conversion or runtime schema changes.

## Verified date-based API contract

The successful Task 1 probe used `Authorization: Bearer <runtime Service Key>`
with the fixed HubSpot API host. The selected endpoints accepted date version
`2026-09`; production code should centralize this version and keep paths fixed.
No v3/v4 fallback was used.

### Company upsert and lookup

One logical Company input used:

```http
POST /crm/objects/2026-09/companies/batch/upsert
```

```json
{
  "inputs": [
    {
      "id": "<opsflow_customer_reference_v2 value>",
      "idProperty": "opsflow_customer_reference_v2",
      "properties": {
        "opsflow_customer_reference_v2": "<same value>",
        "name": "<trusted Odoo name>"
      },
      "objectWriteTraceId": "<request correlation value>"
    }
  ]
}
```

The selected account accepted `idProperty` inside the input. `id` held the
unique-property value, which was also present in `properties`.
`objectWriteTraceId` was accepted per input and echoed exactly in the result.
It is request/item correlation only; the unique property provides identity.

The terminal response was HTTP 200 with `status=COMPLETE`, one result, an
opaque `id`, `new`, `properties`, and the echoed trace. Create returned
`new=true`; same-key replay and managed-name update returned the same ID with
`new=false`. The Company search route is:

```http
POST /crm/objects/2026-09/companies/search
```

Use an equality filter on `opsflow_customer_reference_v2`. One immediate
post-create search briefly returned no result; a later fresh read/search found
the Company. Do not depend on immediate search visibility alone to reconcile an
uncertain write. Same-key upsert replay returned the same ID.

### Deal upsert and lookup

One logical Deal input used:

```http
POST /crm/objects/2026-09/0-3/batch/upsert
```

The input uses the same shape as Company, with `id` equal to the canonical
lowercase OpsFlow order UUID, `idProperty` set to `opsflow_order_id`, and
`opsflow_order_id` included in `properties`. Managed properties are
`opsflow_order_id`, `dealname`, `amount`, `pipeline`, `dealstage`,
`opsflow_currency`, and `opsflow_po_number`.

Create, same-UUID replay, and managed `dealname` update returned HTTP 200,
`status=COMPLETE`, exactly one result, and the same ID. `new` was true only on
creation. The exact synthetic amount string `24.00` was accepted and read back
unchanged; USD, pipeline `default`, and stage `appointmentscheduled` also read
back unchanged. The unique lookup route is:

```http
POST /crm/objects/2026-09/0-3/search
```

Use an equality filter on `opsflow_order_id`.

### Deal-to-Company default association

The bodyless default/unlabeled association request is:

```http
PUT /crm/objects/2026-09/deal/{dealId}/associations/default/company/{companyId}
```

It returned HTTP 200, `status=COMPLETE`, `completedAt`, and two directed
results. Each result used nested `from.id`, `to.id`, and
`associationSpec.associationCategory` / `associationSpec.associationTypeId`
fields. The Deal-to-Company result had type 341, and the reverse
Company-to-Deal result had type 342. A fresh
read uses:

```http
GET /crm/objects/2026-09/deal/{dealId}/associations/company
```

The read returned one Company relation with unlabeled Deal-to-Company type 341.
It also exposed primary Company type 5 for the sole/first associated Company.
M9D sends only the approved default association request; it must not
independently add or remove primary status. Repeating the same PUT returned
`COMPLETE`, and the independent read still showed one relation row/type 341.

## Observed response and rate behavior

- All successful Company and Deal upserts returned HTTP 200,
  `status=COMPLETE`, one result, and no item errors. In the implementation live
  run, the top-level `errors` field was omitted; the parser treats an omitted
  field as an empty error list and still validates any returned item errors.
- Association PUT returned HTTP 200 and `status=COMPLETE`.
- No `PENDING`, `PROCESSING`, or `CANCELED` response was observed. Same-key
  replay returned the existing IDs, so the observed terminal contract requires
  no operation handle or OpsFlow migration.
- HTTP 207 and HTTP 429 were not induced. No successful write returned
  `Retry-After`. Keep deterministic fake tests for item-level 207 and rate
  limit behavior; do not force provider throttling.
- Successful writes exposed `x-hubspot-ratelimit-max=190`,
  `x-hubspot-ratelimit-interval-milliseconds=10000`,
  `x-hubspot-ratelimit-secondly=19`, and
  `x-hubspot-ratelimit-daily=1000000`.

## Synthetic probe cleanup and evidence

The probe used only these synthetic identities:

- Company reference `OPSFLOW-M9D-PROBE-89755BB9`, ID `450254569667`.
- Deal UUID `749c6773-1245-4cfe-a8a8-86d90cb045c3`, ID `524327563504`;
  synthetic PO `OPSFLOW-M9D-PO-1196DBED`.

After create, replay, managed-field update, count, and association verification,
the Deal and Company were archived (HTTP 204). Fresh active object reads then
returned 404; archived reads confirmed `archived=true`; active searches returned
no result rows; and the Deal's association read returned zero rows. The custom
properties and portal configuration were left unchanged.

The separate M9D implementation live suite verified Company create/replay and
managed-name update, Deal create/replay and managed-field update, association
replay/type 341, and same-key recovery after deliberately discarding Company
and Deal results before M9B receipt persistence. It also proved the Company
receipt survived an injected Deal failure and the Deal receipt survived an
injected association failure; retries resumed from the first missing receipt
without repeating Odoo or earlier durable HubSpot steps. The suite's synthetic
records were archived, and a follow-up active-record inventory found no
remaining Company/Deal records with its synthetic prefixes.

HTTP 207, rate limiting, and nonterminal states remain provider-free evidence
because those responses were not safely induced live. Never put a credential
value in this guide, test output, logs, or Git.
