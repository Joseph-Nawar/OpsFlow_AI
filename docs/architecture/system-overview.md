# OpsFlow AI System Overview

## Purpose

OpsFlow AI will demonstrate a reliable business workflow for receiving purchase orders from inconsistent sources, extracting structured information, checking it against trusted business data, routing exceptions to people, and synchronizing approved work with external systems.

The design is intentionally production-style but portfolio-sized: explicit boundaries, safe side effects, useful auditability, and measurable behavior without enterprise-scale infrastructure.

## Authority boundaries

### AI interprets; deterministic software decides

AI is appropriate for interpreting unstructured information. It may extract:

- customer name;
- purchase-order number;
- dates;
- SKU, description, quantity, and submitted price;
- notes, warnings, evidence, or field provenance where useful.

AI is not authoritative for business decisions. It must not decide:

- whether a customer is valid or active;
- whether inventory is sufficient;
- whether a submitted price is acceptable;
- whether an order is a duplicate;
- whether an order should be approved or executed;
- whether an external business-system mutation should occur.

Those decisions belong to deterministic application code, trusted reference data, explicit policies, and—where required—human approval. Structured AI output must pass strict schema validation before it can be used by downstream logic. Missing information must remain explicitly missing; it must not be invented.

Prompt-injection text inside a purchase order is data to extract or flag, not an instruction with authority. For example, a document saying “approve this order” must not change the routing policy.

### n8n orchestrates; Python owns business logic

n8n is the workflow-orchestration layer. It is intended to handle:

- incoming triggers;
- email intake and SaaS connections;
- calls to the OpsFlow API;
- workflow sequencing;
- notifications;
- simple conditional routing;
- orchestration-appropriate retries.

Python/FastAPI is the business-logic layer. It is intended to own:

- canonical document processing;
- structured AI extraction and provider adapters;
- deterministic validation and policies;
- persistence and migrations;
- domain state transitions;
- idempotency and auditability;
- external integration contracts and side-effect safety.

n8n must not contain the core business-rule engine. Python must not depend on a particular workflow tool to enforce business correctness.

## Intended flow

```text
Email / PDF / XLSX / structured form
                 |
                 v
          n8n trigger and intake
                 |
                 v
             OpsFlow API
                 |
                 v
       canonical document processing
                 |
                 v
       structured AI extraction
                 |
                 v
      deterministic validation and policy
              /       \
             v         v
   READY_FOR_APPROVAL  NEEDS_REVIEW
             \         /
              v       v
             human approval
                 |
                 v
     controlled external side effects
       /          |           \
      v           v            v
    Odoo       HubSpot       Gmail
      \           |            /
       \          v           /
             Slack and audit log
```

The exact implementation will be introduced phase by phase. This diagram is an architectural target, not a claim that these components exist in the current repository.

## Domain state boundary

The intended state machine includes `RECEIVED`, `PROCESSING`, `EXTRACTED`, `VALIDATED`, `NEEDS_REVIEW`, `READY_FOR_APPROVAL`, `APPROVED`, `SYNCING`, `COMPLETED`, `REJECTED`, `FAILED_RETRYABLE`, and `FAILED_FINAL`. Only explicitly defined transitions are allowed. In particular, synchronization cannot begin before approval, and validation—not an LLM response—controls whether work is ready for approval. The complete Phase 1 record, invariant, and transition contract is [the domain model specification](domain-model.md).

## Side-effect safety

External mutations must be controllable and testable. Later implementation phases are expected to use adapters, fakes, sandbox accounts, configuration flags, idempotency keys, timeouts, retry policies, and persisted external references as appropriate. Automated tests must not unexpectedly create ERP orders, send real email, update real CRM records, or consume live AI tokens.

## Trust and data flow

Trusted business data—customers, products, catalogue prices, inventory, and existing references—must be supplied by deterministic adapters. An AI extraction is an untrusted draft until it passes schema validation and deterministic business validation. Human review is the explicit path for uncertainty, invalid data, and policy exceptions.

## Current implementation and next boundary

Phases 0–7 are implemented and independently audited, including the order
aggregate and state machine, PostgreSQL persistence and idempotent order
creation, canonical document processing, structured extraction, deterministic
validation, the Phase 6 human-review application, and the Phase 7 authenticated
intake, idempotent pipeline, pinned self-hosted n8n 2.40.5 sandbox
orchestration, selective transport retry, reviewer-authorized retry/redelivery
recovery, and verified local handoff. Phase 7 — n8n Workflow Orchestration is
`COMPLETE`; Phase 8 is `IN PROGRESS` (M8A `COMPLETE`; M8B `COMPLETE`;
M8C–M8F `NOT STARTED`). Gmail/Slack provider workflows and external message
delivery remain unimplemented; ERP/CRM remain later Phase 9 work, and SYNCING
remains later work. The intended-flow diagram above remains a phased target,
not a claim that those later integrations already exist. The full phased scope
and status are maintained in the [project roadmap](../roadmap/project-roadmap.md).
