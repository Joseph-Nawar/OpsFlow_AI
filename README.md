# OpsFlow AI

**AI-assisted purchase-order processing with deterministic safeguards and human authority.**

Businesses receive purchase orders in inconsistent emails and documents. OpsFlow AI extracts order data from those inputs, checks it against trusted business rules and data, routes exceptions to people, and synchronizes approved orders with ERP and CRM systems. The project demonstrates applied AI inside a controlled business workflow rather than allowing a model to make or execute business decisions.

OpsFlow is a locally runnable portfolio project for freelance clients and Applied AI engineering roles. It is not a hosted service or a claim of production deployment.

See the [OpsFlow AI case study](docs/case-study.md) for the workflow, architecture decisions, evidence, and operational limits in a client-facing format.

## Current capabilities and demo status

Implemented capabilities include canonical processing of email text, CSV, XLSX, and PDF inputs; structured extraction through a provider interface; deterministic validation; a React human-review application; PostgreSQL-backed state and audit history; authenticated n8n orchestration; Gmail intake; separate approval-time and post-sync Gmail/Slack notification intents; and Odoo/HubSpot synchronization with durable receipts and recovery controls.

Phases 0–11 are complete. Phase 12 is in progress: M12A — Portfolio Framing and Onboarding is **complete**, independently reviewed at implementation SHA `e6c48a0d6e98ec213e324c5c1b5e8b4c357ce199`, and human-approved. M12B — Approved Completion-Notification Behavior is **complete**, human-approved after independent PASS review. Its technical implementation/remediation is `282a0ae6a7db4ab989f6b2c768142cf34c21098c`; its independent audit is `78a05c5f904d94d77f71622164bf252ed7c1c1ad`. The M12B-AUD-01 and M12B-F01 findings are resolved; the Low-severity M12B-AUD-02 migration downgrade precondition remains documented. M12C — Sandbox Demonstration and Local Reproducibility is **COMPLETE under the owner-approved limited-scope amendment**, after independent PASS review and human acceptance; see the [M12C review disposition](docs/audits/phase-12-m12c-review.md). The M12C-3 transaction remains factually **PARTIAL**: the initial Gmail Trigger intake POST returned HTTP 401, and owner-assisted recovery completed intake. Automated Gmail Trigger-to-OpsFlow intake remains **NOT DEMONSTRATED**. Extraction used scripted FakeProvider, not live Gemini. The reviewed evidence supports deterministic validation, separate human review and approval, actual Odoo/HubSpot synchronization, four Slack and two Gmail deliveries, and exact-source replay. All screenshots are **POST-RUN INSPECTION** captures, not contemporaneous transaction footage. The M12D case study is prepared for independent review; M12E–M12F remain **NOT STARTED**. The frozen Phase 11 provider-free reference passed **36/36 synthetic cases and all five correctness and safety gates**, with zero Gemini calls. A separate post-M12B compatibility run also passed 36/36 and all five gates, with zero direct-LLM side-effect violations; it does not replace the frozen reference. See the [roadmap](docs/roadmap/project-roadmap.md), [Phase 11 evaluation reference](docs/evaluation/reference/phase-11-provider-free-baseline.md), [Phase 11 audit](docs/audits/phase-11-audit.md), and [M12B independent audit](docs/audits/phase-12-m12b-review.md) for status and evidence.

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
          approval-time notification intents
          (delivery does not gate sync)
                         |
                Odoo, then HubSpot
                         |
       durable receipts + completed audit
                         |
           post-sync completion intents
          Slack + Gmail (Gmail provenance)
```

Python owns processing, extraction orchestration, validation, policy, persisted state transitions, and ERP/CRM integration contracts. n8n handles workflow triggers, sequencing, authenticated API calls, provider transport, and simple routing. The [architecture overview](docs/architecture/system-overview.md) describes the implemented boundaries and current notification behavior.

### Reliability and human authority

- Model output is an untrusted extraction draft. Deterministic code checks it against trusted customer, product, price, inventory, and policy data.
- Exceptions go to the review application. Review edits are revalidated; an authorized human explicitly approves or rejects an order.
- PostgreSQL persists order state, review history, audit events, integration receipts, and notification intents. Approval and synchronization transitions use guarded state and durable records.
- Stable identities, idempotent intake, claims, fencing, retries, and exact-source replay protect against duplicate logical orders and ERP/CRM objects. External calls can still have ambiguous acknowledgements; do not interpret these controls as physical exactly-once delivery.
- Approval-time notifications still report review, approval, or processing events; their delivery does not gate synchronization. After successful Odoo and HubSpot synchronization with durable receipts, the backend creates a separate Slack completion intent and, for persisted Gmail-origin orders, a reply to the original Gmail sender/thread. Both intents share the actual completion audit event and have independent outcomes and retries. M12B is implemented, independently audited, and human-approved. Retained M12C-3 evidence records four Slack and two Gmail deliveries, including post-sync completion intents tied to successful synchronization; automated checks alone do not establish those live outcomes. Automated Gmail Trigger-to-OpsFlow intake remains NOT DEMONSTRATED.

## Evaluation and limitations

The frozen provider-free Phase 11 reference records 36/36 synthetic cases passing, all five correctness/safety gates passing, and zero Gemini calls. Provider-free extraction quality is `NOT_APPLICABLE`; these results are not Gemini accuracy. The reference is tied to run SHA `7b67e6e32a2c7f7c44894dcf38eb68968ce1195b` and corpus `3.0.0`. Separately, the independently reviewed post-M12B compatibility evaluation (run `00947f6c-2277-4535-baa6-00f68dbd1f09`, corpus `3.0.0`) also passed 36/36 cases and all five gates, with `direct_llm_side_effects_zero` at 0/36, zero Gemini calls, and extraction quality `NOT_APPLICABLE`. This later run verifies compatibility; it does not replace or modify the frozen Phase 11 reference.

Real Gemini extraction quality, aggregate provider latency, authoritative token totals, and actual model cost remain unmeasured. The local timing diagnostics are not production SLAs. Phase 11's approved performance outcome is `NO_OPTIMIZATION`. Customer adoption, production deployment, ROI, and cost savings have not been measured or claimed. The M12B migration downgrade requires completion notification rows to be removed before restoring the previous kind constraint. The known full frontend development dependency tree still has two high-severity transitive advisories; production-only dependency audits were clean at the independent audit baseline. See the [evaluation reference](docs/evaluation/reference/phase-11-provider-free-baseline.md), [baseline decision](docs/evaluation/reference/phase-11-baseline-decision.md), [live Gemini evidence record](docs/evaluation/reference/phase-11-live-gemini-unavailable.md), [M12B audit](docs/audits/phase-12-m12b-review.md), and [dependency security guidance](docs/development/dependency-security.md) for these boundaries.

## Local development

The following is a local PostgreSQL, API, and frontend quick start. It does not start n8n, run the end-to-end provider demo, or make external calls.

**Prerequisites:** Python 3.12, `uv`, Node.js 24 with npm 11.19.0, Docker Engine or Desktop with the Compose v2 plugin supporting `docker compose up --wait`, GNU Make, and Git. Python and Node ranges are pinned in the project manifests; `uv` and Docker/Compose versions are not pinned. PostgreSQL is supplied by Compose. The Compose file uses PostgreSQL 16 and publishes it on loopback port 5432. Confirm that port is free; if another service owns it, stop and identify that service before proceeding rather than connecting to an unknown database.

Install dependencies and create ignored local configuration:

```bash
uv sync --frozen --dev
npm --prefix web ci
if [ ! -e .env ] && [ ! -L .env ]; then
  cp .env.example .env
fi
```

The guard creates `.env` only when no file, directory, or symlink exists at that path. An existing local configuration is left unchanged.

Start a fresh, uniquely named Compose project containing only PostgreSQL. Its project name owns the local service and project-scoped data volume. Wait for PostgreSQL's health check, then verify the effective Alembic target before applying migrations:

```bash
docker compose -p opsflow-m12a-local up --wait postgres &&
{
  uv run python - <<'PY'
from sqlalchemy.engine import make_url
from opsflow.settings import get_settings

expected = ("postgresql+asyncpg", "localhost", 5432, "opsflow", "opsflow")
try:
    url = make_url(get_settings().database_url)
    actual = (url.drivername, url.host, url.port, url.database, url.username)
except Exception:
    raise SystemExit("Refusing migration: effective database target could not be verified.")

if actual != expected:
    raise SystemExit(
        "Refusing migration: target must be the local OpsFlow database "
        "at localhost:5432/opsflow as user opsflow."
    )
print("Verified effective migration target: local OpsFlow database.")
PY
} &&
make migrate
```

Compose `--wait` returns after the service is healthy, as reported by its configured `pg_isready` check. The read-only verifier parses the same `get_settings().database_url` used by Alembic and compares its driver, host, port, database, and username with the documented local target. It prints no URL, password, or other credential, does not connect to the database, and fails closed on a mismatch; the `&&` chain then prevents `make migrate` from running. `OPSFLOW_DATABASE_URL` or an existing `.env` can override defaults, so this check runs immediately before migration. If another service owns loopback port 5432, stop and identify it before proceeding rather than connecting to an unknown database. If this Compose project name or its volume already exists and its state is not the intended disposable local database, choose a new unique `-p` name and use it consistently in corresponding Compose commands; Compose scopes the PostgreSQL data volume to that project. `.env` is ignored; keep credentials there or in local n8n credential storage, never in Git.

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

The live Gemini evaluation command runs the full 36-case evaluation and may incur provider charges; it is not authorized for Phase 12. The M12C-3 run used FakeProvider and made no live Gemini extraction claim. Any later Gemini request requires separate explicit authorization and a spending ceiling. No Gemini, Gmail, Slack, Odoo, or HubSpot operation is performed by the commands above.

## Integrations and demonstration procedures

Existing integration guides document distinct provider procedures and historical sandbox evidence. The M12C-3 transaction is a segmented, owner-approved demonstration: it records the initial Gmail Trigger HTTP 401 and owner-assisted recovery, then shows actual downstream sandbox synchronization, notifications, and replay. It does not demonstrate uninterrupted automated Gmail-to-OpsFlow intake. Historical Phase 8 evidence is separate: the [workflow guide](workflows/n8n/README.md) records M8C Gmail sandbox cases A–I and M8E primary/clean-clone Gmail intake through review and approval with Slack and original-thread approval replies; the [Phase 8 audit](docs/audits/phase-8-audit.md) says M8F reused those records and made no live provider sends. Phase 8 does not establish Phase 12 Odoo/HubSpot synchronization or post-sync notifications.

- [n8n workflow setup and Gmail/Slack procedures](workflows/n8n/README.md) — n8n 2.40.5; Gmail intake/reply and Slack delivery require dedicated sandbox credentials and explicit setup.
- [Odoo sandbox setup](docs/development/odoo-m9c-sandbox.md) — disposable Odoo environment and credentials are required for live synchronization.
- [HubSpot sandbox setup](docs/development/hubspot-m9d-sandbox.md) — a developer-test portal and credentials are required for live synchronization.
- [Phase 9 n8n synchronization clean-clone procedure](docs/development/phase9-n8n-sync-e2e.md) — local Compose, role credentials, and the separate Odoo/HubSpot sandbox flow.

The 2026-10-18 M12C-3 run used the original synthetic Gmail source but required owner-assisted intake recovery after the Gmail Trigger's OpsFlow POST returned HTTP 401. The failed request's exact body bytes were not retained. The run used the application's scripted FakeProvider path, deterministic validation, distinct human review and approval, actual Odoo and HubSpot synchronization with durable receipts, reuse of the existing synthetic HubSpot Company with one Deal and association, four Slack and two Gmail notification deliveries, and exact-source replay without a second logical order. Post-sync notifications were causally tied to successful synchronization; their external delivery order is not a correctness requirement. The run remains factually **PARTIAL** because automated Gmail Trigger-to-OpsFlow intake was not demonstrated. Twelve raw captures and separate sanitized derivatives remain in the private evidence area; the derivatives are labeled **POST-RUN INSPECTION** and are not contemporaneous transaction footage. No video has been produced. See the [M12C runbook](docs/development/phase9-n8n-sync-e2e.md) and [review disposition](docs/audits/phase-12-m12c-review.md) for acceptance, limitations, and public-media handling notes.

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
