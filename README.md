# OpsFlow AI

OpsFlow AI is a production-grade portfolio project for reliable B2B purchase-order and operations automation. It is designed to demonstrate how messy inputs such as email, PDF, XLSX, and forms can move through AI-assisted extraction, deterministic validation, human review, and safe synchronization with business systems.

The project is intentionally sized as a portfolio project, not an enterprise platform. The goal is a clear, credible, locally demonstrable system that shows applied AI, workflow automation, backend engineering, integrations, reliability, and evaluation.

## Current status

**M0A — Repository Intelligence & Project Specification**, **M0B — Backend Foundation**, and **M0C — PostgreSQL, SQLAlchemy, Alembic & Docker** are `COMPLETE`. Phase 0 is `IN PROGRESS`; M0D–M0F are `NOT STARTED`, and Phases 1–12 remain `NOT STARTED`. The repository now contains only the minimal backend and infrastructure foundation; no later-milestone functionality exists.

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

M0B verified Python 3.12, `uv`, FastAPI, Pydantic v2, pydantic-settings, pytest, Ruff, mypy, and package building. M0C now verifies SQLAlchemy 2.x async PostgreSQL access through asyncpg, Alembic, PostgreSQL 16, Docker Compose, and the `/ready` readiness boundary. The remaining roadmap baseline—self-hosted n8n Community Edition, React, TypeScript, Vite, AI providers, document handling, business integrations, GitHub Actions, secret scanning, and structured logging—remains planned for later milestones.

## Documentation map

- [Architecture overview](docs/architecture/system-overview.md) — authority boundaries and intended system flow.
- [Development guide](docs/development/development-guide.md) — conventions, verified M0B commands, and planned workflow.
- [Decision records](docs/decisions/README.md) — how durable technical decisions will be recorded.
- [Project roadmap](docs/roadmap/project-roadmap.md) — approved phases, rules, status, and completion protocol.

## Cost and data posture

The project must remain deployable and demonstrable with **$0 mandatory development cost**. Local and open-source infrastructure, free developer environments, adapters, test doubles, and synthetic data are preferred. Optional paid AI testing must remain a convenience rather than an architectural dependency.

Never commit credentials, API keys, private business data, or real customer documents. Use local configuration and synthetic fixtures as later phases are implemented.

## Development status and commands

Verified M0B backend commands and still-planned commands are distinguished in the [development guide](docs/development/development-guide.md).
