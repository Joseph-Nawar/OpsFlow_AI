# OpsFlow AI

OpsFlow AI is a production-grade portfolio project for reliable B2B purchase-order and operations automation. It is designed to demonstrate how messy inputs such as email, PDF, XLSX, and forms can move through AI-assisted extraction, deterministic validation, human review, and safe synchronization with business systems.

The project is intentionally sized as a portfolio project, not an enterprise platform. The goal is a clear, credible, locally demonstrable system that shows applied AI, workflow automation, backend engineering, integrations, reliability, and evaluation.

## Current status

The repository is completing **M0A — Repository Intelligence & Project Specification**, a documentation bootstrap within the Phase 0 foundation effort. The broader **Phase 0 — Product & Engineering Foundation** remains `NOT STARTED` until application/tooling setup begins. No application implementation, runtime, database, workflow, integration, or future-phase code exists yet.

The canonical phase tracker and approved scope are in [the project roadmap](docs/roadmap/project-roadmap.md).

## Architectural guardrails

- **AI interprets unstructured information; deterministic software controls business decisions and side effects.** An LLM may extract fields and evidence, but it may not decide validity, approval, execution, or external mutation.
- **n8n orchestrates workflows; Python owns business logic.** n8n will handle triggers, sequencing, SaaS connections, notifications, and simple routing. Python will own document processing, extraction, validation, policy, persistence, state transitions, auditability, and integration contracts.

The system is expected to evolve toward this flow:

```text
Email / PDF / XLSX / Form
            |
           n8n
            |
       OpsFlow API
            |
  document processing and extraction
            |
 deterministic validation and policy
        /                 \
     valid              exception
       |                   |
 ready for approval    human review
        \                 /
             approval
                |
       ERP / CRM / notifications
                |
             audit log
```

## Intended technology baseline

The approved roadmap currently targets Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x, Alembic, PostgreSQL, self-hosted n8n Community Edition, React, TypeScript, Vite, a provider-neutral AI layer with Gemini initially, PyMuPDF, openpyxl, CSV/email parsing, optional Tesseract OCR, Odoo, HubSpot, Gmail, Slack, Docker Compose, pytest, Ruff, mypy, GitHub Actions, secret scanning, and structured logging. These tools are planned; they are not installed or verified by this documentation-only milestone.

## Documentation map

- [Architecture overview](docs/architecture/system-overview.md) — authority boundaries and intended system flow.
- [Development guide](docs/development/development-guide.md) — conventions, planned commands, and phase workflow.
- [Decision records](docs/decisions/README.md) — how durable technical decisions will be recorded.
- [Project roadmap](docs/roadmap/project-roadmap.md) — approved phases, rules, status, and completion protocol.

## Cost and data posture

The project must remain deployable and demonstrable with **$0 mandatory development cost**. Local and open-source infrastructure, free developer environments, adapters, test doubles, and synthetic data are preferred. Optional paid AI testing must remain a convenience rather than an architectural dependency.

Never commit credentials, API keys, private business data, or real customer documents. Use local configuration and synthetic fixtures as later phases are implemented.

## Development status and commands

No application commands are claimed as verified yet because the corresponding tooling does not exist in this repository. Planned commands and their verification expectations are recorded in the [development guide](docs/development/development-guide.md).
