# OpsFlow AI

**AI-assisted purchase-order processing with deterministic safeguards and human authority.**

Businesses receive purchase orders in inconsistent emails and documents. OpsFlow AI extracts order data from those inputs, checks it against trusted business rules and data, routes exceptions to people, and synchronizes approved orders with ERP and CRM systems. The project demonstrates applied AI inside a controlled business workflow rather than allowing a model to make or execute business decisions.

OpsFlow is a locally runnable portfolio project for freelance clients and Applied AI engineering roles. It is not a hosted service or a claim of production deployment.

## Current capabilities and demo status

Implemented capabilities include canonical processing of email text, CSV, XLSX, and PDF inputs; structured extraction through a provider interface; deterministic validation; a React human-review application; PostgreSQL-backed state and audit history; authenticated n8n orchestration; Gmail intake and approval-time notifications; and Odoo/HubSpot synchronization with durable receipts and recovery controls.

Phases 0–11 are complete. Phase 12 is in progress: M12A — Portfolio Framing and Onboarding is underway, and M12B–M12F have not started. The Phase 11 provider-free reference passed **36/36 synthetic cases and all five correctness and safety gates**, with zero Gemini calls. The new Phase 12 end-to-end portfolio demonstration—including post-sync Gmail and Slack completion notifications—has not yet been captured. No Phase 12 video or screenshots are available yet. See the [roadmap](docs/roadmap/project-roadmap.md), [Phase 11 evaluation reference](docs/evaluation/reference/phase-11-provider-free-baseline.md), and [Phase 11 audit](docs/audits/phase-11-audit.md) for status and evidence.

## How it works

```text
Gmail intake / email text / CSV / XLSX / PDF
                    |
                   n8n  (triggers and provider transport)
                    |
              Python / FastAPI
                    |
       canonical processing and extraction
                    |
   deterministic validation against trusted data
               /                 \
      ready for approval       exception
               \                 /
                human review and approval
                         |
                Odoo, then HubSpot
                         |
             PostgreSQL state and receipts
```

Python owns processing, extraction orchestration, validation, policy, persisted state transitions, and ERP/CRM integration contracts. n8n handles workflow triggers, sequencing, authenticated API calls, provider transport, and simple routing. The [architecture overview](docs/architecture/system-overview.md) describes the implemented boundaries and current notification behavior.

### Reliability and human authority

- Model output is an untrusted extraction draft. Deterministic code checks it against trusted customer, product, price, inventory, and policy data.
- Exceptions go to the review application. Review edits are revalidated; an authorized human explicitly approves or rejects an order.
- PostgreSQL persists order state, review history, audit events, integration receipts, and notification intents. Approval and synchronization transitions use guarded state and durable records.
- Stable identities, idempotent intake, claims, fencing, retries, and exact-source replay protect against duplicate logical orders and ERP/CRM objects. External calls can still have ambiguous acknowledgements; do not interpret these controls as physical exactly-once delivery.
- Current Gmail and Slack notifications report review, approval, or processing events. The Gmail approval reply targets the original sender/thread when persisted Gmail provenance is available. These are **not** post-sync completion notifications. M12B plans separate Gmail and Slack completion events tied to successful Odoo and HubSpot synchronization; that behavior is not implemented yet.

## Evaluation and limitations

The committed provider-free Phase 11 reference records 36/36 synthetic cases passing, all five correctness/safety gates passing, and zero Gemini calls. Provider-free extraction quality is `NOT_APPLICABLE`; these results are not Gemini accuracy. The reference is tied to run SHA `7b67e6e32a2c7f7c44894dcf38eb68968ce1195b` and corpus `3.0.0`.

Real Gemini extraction quality, aggregate provider latency, authoritative token totals, and estimated model cost remain unmeasured. The local timing diagnostics are not production SLAs. Phase 11's approved performance outcome is `NO_OPTIMIZATION`. Customer adoption, production deployment, ROI, and cost savings have not been measured or claimed. The [evaluation reference](docs/evaluation/reference/phase-11-provider-free-baseline.md), [baseline decision](docs/evaluation/reference/phase-11-baseline-decision.md), and [live Gemini evidence record](docs/evaluation/reference/phase-11-live-gemini-unavailable.md) preserve these boundaries.

## Local development

The following is a local PostgreSQL, API, and frontend quick start. It does not start n8n, run the end-to-end provider demo, or make external calls.

**Prerequisites:** Python 3.12, `uv`, Node.js 24 with npm 11.19.0, Docker Engine or Desktop with the Compose v2 plugin (`docker compose`), GNU Make, and Git. Python and Node ranges are pinned in the project manifests; `uv` and Docker/Compose versions are not pinned. PostgreSQL is supplied by Compose. The Compose file uses PostgreSQL 16 and publishes it on loopback port 5432. Confirm that port is free; if another service owns it, stop and identify that service before proceeding rather than connecting to an unknown database.

Install dependencies and create ignored local configuration:

```bash
uv sync --frozen --dev
npm --prefix web ci
cp .env.example .env
```

Start a fresh, named Compose project containing only PostgreSQL, then apply migrations:

```bash
docker compose -p opsflow-m12a-local up -d postgres
make migrate
```

If that Compose project name or its volume already exists, choose a new unique `-p` name and use it consistently in the corresponding Compose commands. The `make migrate` command reads the local `.env` database URL at `localhost:5432`. `.env` is ignored; keep all credentials there or in local n8n credential storage, never in Git.

Start the local API and review frontend in separate terminals:

```bash
uv run uvicorn opsflow.main:app --reload
npm --prefix web run dev
```

The local application defaults to a scripted extraction provider when no Gemini key is configured. It returns a fixed synthetic response rather than extracting your input, so it is not live Gemini evidence. Review and approval actions require distinct local development operator credentials; the quick start does not provide usable credentials. See the [development guide](docs/development/development-guide.md) and [Phase 9 clean-clone procedure](docs/development/phase9-n8n-sync-e2e.md) for guarded local role configuration.

To stop the database service while preserving this project's named data volume:

```bash
docker compose -p opsflow-m12a-local stop postgres
```

### Evaluation and integration setup

`make check` runs backend and frontend quality checks, including the full test suite. It requires a correctly configured disposable integration database; read the [development guide](docs/development/development-guide.md#destructive-migration-test-isolation) before running it. It does not provision or reset external services. `make evaluate` is provider-free, but its guarded evaluation database setup is described separately in the [evaluation instructions](docs/development/development-guide.md#phase-11-evaluation-commands). Neither command is part of the quick start.

The live Gemini evaluation command runs the full 36-case evaluation and may incur provider charges; it is not authorized for Phase 12. Any individual Gemini request for the future demo also requires separate explicit authorization and a spending ceiling. No Gemini, Gmail, Slack, Odoo, or HubSpot operation is performed by the commands above.

## Integrations and demonstration procedures

Existing integration guides document distinct provider procedures and historical sandbox evidence. They are not the pending full Phase 12 demonstration, and a provider-free run or prior integration test cannot substitute for that live end-to-end evidence.

- [n8n workflow setup and Gmail/Slack procedures](workflows/n8n/README.md) — n8n 2.40.5; Gmail intake/reply and Slack delivery require dedicated sandbox credentials and explicit setup.
- [Odoo sandbox setup](docs/development/odoo-m9c-sandbox.md) — disposable Odoo environment and credentials are required for live synchronization.
- [HubSpot sandbox setup](docs/development/hubspot-m9d-sandbox.md) — a developer-test portal and credentials are required for live synchronization.
- [Phase 9 n8n synchronization clean-clone procedure](docs/development/phase9-n8n-sync-e2e.md) — local Compose, role credentials, and the separate Odoo/HubSpot sandbox flow.

Phase 12's future full demonstration requires actual synthetic Gmail intake, application processing with provider mode identified, deterministic validation, human review and approval, successful Odoo and HubSpot synchronization with durable receipts, confirmed completion, actual post-sync Gmail and Slack delivery, and exact-source replay without a second logical order or duplicate ERP/CRM objects. Both completion notifications must be causally tied to successful synchronization; their external delivery order is not a correctness requirement. The demo requires dedicated disposable sandboxes and separate authorization for each live model or provider operation. No such run has been captured.

## Testing and security

`make check` runs backend tests and quality checks plus frontend tests, lint, and build. Configure a disposable integration database and follow the database safeguards in the [development guide](docs/development/development-guide.md#destructive-migration-test-isolation) before running it. `make security-audit` runs the repository's Python production-dependency and frontend production-dependency audits; pinned Gitleaks history-scan instructions are also in the development guide. These checks do not make provider calls.

The latest recorded dependency review found two high-severity transitive advisories in frontend development dependencies; the production-only frontend audit was clean at the Phase 11 audit baseline. They remain an explicit limitation pending current release-candidate review. See [dependency security guidance](docs/development/dependency-security.md) and the [Phase 11 audit](docs/audits/phase-11-audit.md).

## Technical documentation

- [Architecture overview](docs/architecture/system-overview.md) — implemented system boundaries and state flow.
- [Domain model](docs/architecture/domain-model.md) — canonical order lifecycle and invariants.
- [Development guide](docs/development/development-guide.md) — commands, database guards, evaluation, and workflow conventions.
- [Roadmap](docs/roadmap/project-roadmap.md) — authoritative phase scope and current status.
- [Phase 11 implementation plan](docs/superpowers/plans/2026-10-07-phase-11-evaluation-optimization.md) and [independent audit](docs/audits/phase-11-audit.md) — evidence provenance and closeout.
- [Phase 12 design](docs/superpowers/specs/2026-10-12-phase-12-portfolio-release-design.md) and [implementation plan](docs/superpowers/plans/2026-10-12-phase-12-portfolio-release.md) — approved scope and milestone gates.
- [Security guidance](docs/development/dependency-security.md) — pinned dependency-audit commands and current known advisory boundaries.

## License

No project license has been selected. Repository visibility does not grant permission to reuse project code or assets. Licensing remains a human-owner decision for a later Phase 12 milestone.
