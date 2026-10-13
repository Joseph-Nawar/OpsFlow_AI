# OpsFlow AI System Overview

## Purpose

OpsFlow AI processes business-to-business purchase orders that arrive as email and document inputs. It extracts a structured order, validates it against trusted business data, routes uncertainty to a person, and synchronizes an approved order with ERP and CRM systems. The repository contains an implemented local system and integration workflows; the new full Phase 12 portfolio demonstration is still pending.

## Authority boundaries

### AI interprets; deterministic software decides

The extraction provider returns an untrusted structured draft: customer and purchase-order identifiers, dates, line items, quantities, prices, notes, and available evidence. The provider can be a scripted local provider or Gemini, depending on local configuration. A missing Gemini key selects the scripted provider; a key with valid model and timeout settings selects the real adapter. Provider identity must be stated when reporting any run.

The draft passes schema checks and deterministic validation against trusted customer, product, pricing, inventory, and policy data. The model does not decide whether a customer is valid, a price is acceptable, stock is sufficient, an order is a duplicate, an order should be approved, or a side effect should occur. Prompt-injection text in a source document remains data, not authority.

### n8n orchestrates; Python owns business logic

The self-hosted n8n Community runtime is pinned to 2.40.5. Its versioned workflows handle Gmail triggers, authenticated HTTP calls, scheduling, provider transport, bounded transport retries, and simple routing. Workflow credentials remain local to the operator's n8n instance.

Python/FastAPI owns canonical document processing, extraction orchestration and provider adapters, deterministic validation, policy, durable state transitions, review contracts, idempotency, audit records, notification eligibility, synchronization contracts, and persisted outcomes. n8n does not decide business validity or hold the authoritative order state.

## Implemented workflow

```text
Gmail label trigger or authenticated intake request
                         |
                         v
                  n8n workflow
                         |
                         v
              FastAPI intake endpoint
                         |
                         v
        canonical document processing
                         |
                         v
          structured extraction draft
                         |
                         v
       deterministic validation and routing
                   /           \
                  v             v
        READY_FOR_APPROVAL   NEEDS_REVIEW
                  \             /
                   human review
                         |
              explicit authorized approval
                         |
                         v
         Odoo synchronization, then HubSpot
                         |
        PostgreSQL state, events, and receipts
                         |
        current approval-time notifications
```

The Gmail intake workflow watches an operator-configured label, selects the message body or supported attachment, and sends the original Gmail message identity and source metadata to the authenticated intake endpoint. The Python document processor canonicalizes supported email text, CSV, XLSX, and PDF content before extraction. Intake identity and source provenance support idempotent replay; raw source document bytes are not persisted by the Phase 7 intake pipeline.

Deterministic validation either routes a suitable order to `READY_FOR_APPROVAL` or directs issues to `NEEDS_REVIEW`. The React review application presents extraction provenance, trusted reference data, validation results, and review history. Review edits are persisted as revisions and revalidated. A separate authorized approver must approve the order before synchronization can begin.

The authenticated sync workflow asks the backend to execute eligible orders. Python owns synchronization claims, recovery, adapter contracts, and durable outcomes. It synchronizes Odoo before HubSpot and records each external receipt. Completion requires the successful sync state and required durable receipts. The external-system adapters use stable identities so recovery and replay preserve at-most-one logical external record and converge to the existing record under their documented model.

## Persistence, idempotency, and recovery

PostgreSQL is the authoritative store for the order aggregate, source identity and provenance, extraction and validation state, immutable human-review revisions, audit history, notification intents and outcomes, synchronization state, and Odoo/HubSpot receipts. Database transactions protect local state transitions and the creation of durable work records. External API calls occur outside those local transactions; their effects cannot be rolled back by PostgreSQL.

Stable source and external identities, uniqueness constraints, claims, fencing, bounded retries, persisted receipts, and exact-source replay prevent a duplicate logical order or ERP/CRM object under the documented recovery contracts. This is not physical exactly-once execution: an external provider may accept an operation while its acknowledgement is lost. Notification delivery is at least once, so an ambiguous send acknowledgement can result in a duplicate external message even though the durable logical intent is idempotent.

The domain states, transition rules, and invariants are defined in the [domain model](domain-model.md). Existing Phase 8–11 implementation evidence and limitations are preserved in the [roadmap](../roadmap/project-roadmap.md), [Phase 8 audit](../audits/phase-8-audit.md), [Phase 9 audit](../audits/phase-9-audit.md), [Phase 10 audit](../audits/phase-10-audit.md), and [Phase 11 audit](../audits/phase-11-audit.md).

## Current notification behavior and M12B boundary

The current durable notification outbox supports Slack events for `REVIEW_REQUIRED`, `APPROVAL_READY`, `PROCESSING_FAILED`, and `ORDER_APPROVED`. Gmail delivery is a sender-only reply to the original thread for `ORDER_APPROVED`, and it requires persisted Gmail-source provenance. The approval reply says the order was approved for processing; it does not claim that synchronization completed. Each channel has separate durable outcomes and bounded retries, with at-least-once external delivery semantics.

**Post-sync completion notifications are not implemented.** M12B has an approved design contract for creating separate Gmail and Slack completion intents only after successful Odoo and HubSpot synchronization with durable receipts. Gmail would reply to the original sender/thread when persisted Gmail provenance exists. Slack would independently report successful synchronization; neither channel's delivery eligibility depends on the other's delivery. Both outcomes would be required by the Phase 12 full-demo acceptance criterion, but their external delivery order is not a correctness invariant. M12B remains NOT STARTED and needs separate implementation authorization and review. See the [approved Phase 12 design](../superpowers/specs/2026-10-12-phase-12-portfolio-release-design.md) and [implementation plan](../superpowers/plans/2026-10-12-phase-12-portfolio-release.md).

## Technology and current status

- **Backend:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, async PostgreSQL access, and Alembic.
- **Data:** PostgreSQL 16.
- **Frontend:** React, TypeScript, and Vite on Node.js 24.
- **Workflow:** self-hosted n8n Community 2.40.5.
- **Integrations:** Gemini adapter; Gmail intake and approval reply; Slack notification dispatch; Odoo ERP; HubSpot CRM.

Phases 0–11 are COMPLETE. Phase 12 is IN PROGRESS with M12A — Portfolio Framing and Onboarding authorized and underway; M12B–M12F remain NOT STARTED. The design and implementation plan are APPROVED. The authoritative current tracker is the [project roadmap](../roadmap/project-roadmap.md).

## Related documentation

- [README and local quick start](../../README.md)
- [Development guide](../development/development-guide.md)
- [Gmail, Slack, and n8n workflow procedures](../../workflows/n8n/README.md)
- [Odoo sandbox procedure](../development/odoo-m9c-sandbox.md)
- [HubSpot sandbox procedure](../development/hubspot-m9d-sandbox.md)
- [Phase 9 clean-clone integration procedure](../development/phase9-n8n-sync-e2e.md)
