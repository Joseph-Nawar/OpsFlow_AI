# OpsFlow AI: controlled purchase-order processing

OpsFlow converts purchase orders from emails and documents into orders that people can review, approve, and synchronize with business systems. The system extracts and checks; a person decides; OpsFlow records the result.

## The business problem

Purchase orders arrive in emails, spreadsheets, and PDFs. Teams re-enter line items, check customer and product data, resolve price or delivery questions, seek approval, then update separate ERP and CRM tools. Repeated handoffs invite transcription mistakes, duplicate processing, and unclear ownership.

OpsFlow provides a reviewable path through that work: what arrived, what the system extracted, which trusted-data checks passed or need attention, who reviewed and approved, and whether downstream updates completed. The project has not measured time saved, error reduction, or financial return.

## From incoming document to business-system updates

An order can arrive through the Gmail workflow or as supported email text, CSV, XLSX, or PDF content. n8n receives the trigger and transports an authenticated request to the Python API. Python normalizes the source and asks the configured extraction provider for a structured draft of the customer, order identifiers, dates, and line items.

That draft is untrusted. Deterministic Python checks compare it with trusted customer, product, pricing, inventory, duplicate, and policy data. A suitable order can move to the approval queue; missing or conflicting information is routed for review. A reviewer can correct fields, after which the application validates the revision again. A separate authorized approver makes the approval decision. Neither the model nor the workflow engine can approve an order or authorize a write to a business system.

After approval, Python coordinates synchronization to Odoo and then HubSpot. It persists the order state, audit events, and provider receipts so an operator can distinguish completed work from a failure that needs recovery. Slack and Gmail notifications are recorded as durable intents: approval-time messages report the approval event, while completion messages are created after the required Odoo and HubSpot receipts exist. Gmail replies use the original message provenance when available.

## Architecture decisions

The boundary is deliberate: Python owns document processing, extraction orchestration, deterministic validation, policy, state changes, auditability, and integration contracts. n8n remains a thin layer for triggers, sequencing, provider transport, and simple routing. Model output can propose fields and evidence, but cannot supply trusted facts or authority. See the [system overview](architecture/system-overview.md) and [domain model](architecture/domain-model.md).

PostgreSQL stores the order lifecycle, source identity, review history, audit trail, notification intents and outcomes, synchronization state, and durable provider receipts. Stable identities, guarded claims, bounded retries, and exact-source replay let the application resume or recognize work already represented in its logical state. In the demonstrated replay, the same source did not create another logical order or notification intent.

Logical idempotency does not guarantee exactly-once delivery to an external service. A provider may accept a message while its acknowledgement is lost; a later retry can send a duplicate Slack message or Gmail reply. OpsFlow records delivery attempts and outcomes, but notification delivery remains at least once.

## Evidence and what it establishes

The evidence below comes from three separate classes. Their populations and environments are different, so their results are not combined into one end-to-end score.

### 1. Frozen Phase 11 provider-free evaluation

The frozen [Markdown reference](evaluation/reference/phase-11-provider-free-baseline.md), [JSON result](evaluation/reference/phase-11-provider-free-baseline.json), and [Phase 11 audit](audits/phase-11-audit.md) report run `a50b6256-9f56-462d-8f12-5e01651e3c85`, source Git SHA `7b67e6e32a2c7f7c44894dcf38eb68968ce1195b`, corpus `3.0.0`, and mode `provider_free` via `make evaluate`. The population is 36 synthetic cases: nine each for email text, CSV, XLSX, and PDF. The run used scripted FakeProvider output and an isolated PostgreSQL 16 database; it made zero Gemini calls. Extraction quality is `NOT_APPLICABLE`, so these results are not live model accuracy.

| Frozen corpus gate | Observed result |
| --- | ---: |
| Cases passing | 36/36 |
| Deterministic violation routing | 7/7 |
| Duplicate blocking | 4/4 |
| Malformed/security handling | 4/4 |
| Invalid orders executed | 0/13 |
| Direct LLM side effects | 0/36 |

These results show that the evaluated synthetic cases followed the expected routing and safety contracts. They do not establish how accurately a live model extracts customer orders. Phase 11's approved performance decision remains [`NO_OPTIMIZATION`](evaluation/reference/phase-11-baseline-decision.md): the measured evidence did not justify a runtime change.

### 2. Historical Phase 8 and Phase 9 integration evidence

Earlier, separately scoped sandbox records cover Gmail intake and approval notifications in Phase 8, and Odoo/HubSpot synchronization and recovery in Phase 9. See the [Phase 8 audit](audits/phase-8-audit.md) and the [Phase 9 audit](audits/phase-9-audit.md). Those records retain their own candidate revisions, test populations, and provider modes; they are historical integration evidence, not part of the Phase 11 corpus or the M12C transaction. Phase 8 predates ERP/CRM synchronization and post-sync completion notifications, so it cannot fill the M12C automated-intake gap.

### 3. M12C owner-assisted sandbox demonstration

The [M12C-3 transaction record](development/phase9-n8n-sync-e2e.md) and its [independent review and acceptance](audits/phase-12-m12c-review.md) cover one synthetic Gmail email and one logical order in dedicated provider sandboxes. The transaction's candidate SHA was `fc70d37fd004847fab0a4c42499e75afe1d6198b`; extraction used scripted FakeProvider, not Gemini. Gmail, Odoo, HubSpot, and Slack were the external integration providers.

The Gmail Trigger found the source, but its intake POST returned HTTP 401. The owner then recovered intake from the same original MIME message using its Gmail identity and provenance. The recovery POST returned HTTP 201 and created the intended source and order. The exact request bytes from the failed POST were not retained, so byte-for-byte parity to that request is not claimed. A separate reviewer and approver were persisted. The order reached `COMPLETED`; Odoo's sale order and the HubSpot Deal association with the reused synthetic Company were confirmed. Four Slack notifications and two Gmail replies were delivered. Exact-source replay returned HTTP 200 with `idempotent_replay=true` and added no logical order or notification intent. Screenshots are post-run inspections of persisted state, not footage of the transaction as it happened.

This one owner-assisted run demonstrated downstream sandbox writes, human authority, recorded receipts and notification outcomes, and logical replay behavior. It did **not** demonstrate uninterrupted automated Gmail Trigger-to-OpsFlow intake. The historical Phase 8 evidence is separate and does not change that result.

## Operational limits and client setup

OpsFlow is a locally runnable portfolio project, not a hosted service or a production deployment. Before adapting it for a client, the implementation would need client-specific document and field mapping, trusted customer/product/pricing/inventory data, approval roles, notification destinations, provider accounts and credentials, and deployment controls for access, secrets, monitoring, backups, and recovery. A client pilot would also need validation against that client's documents, policies, and failure cases.

Live Gemini extraction quality, authoritative token usage, provider latency, and model cost are unmeasured. The provider-free corpus and one scripted-extraction sandbox transaction do not establish production performance. Customer adoption, production SLAs, time savings, ROI, and cost savings have not been measured or claimed.
