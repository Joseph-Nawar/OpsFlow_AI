# OpsFlow sandbox intake workflow

This workflow is authored and exported from n8n `2.40.5` (`n8nio/n8n:2.40.5`).
Start the local stack with:

```sh
docker compose up -d postgres api n8n
```

Open the editor at [http://localhost:5678](http://localhost:5678) and import
`opsflow-sandbox-intake.json`. The stable webhook path is
`POST /webhook/opsflow-sandbox-intake`; it forwards to
`http://api:8000/v1/orchestration/intakes` over the Compose network.

The known-good synthetic input is `fixtures/phase7/synthetic-order.txt` with
`document_type=EMAIL_BODY` and MIME `text/plain`. Each request must provide a
fresh, caller-owned `X-OpsFlow-Event-Id`; the workflow forwards that exact value
as `Idempotency-Key` and does not generate or normalize a replacement. An
optional `message_id` form field is forwarded unchanged.

The HTTP Request node uses the `httpBearerAuth` credential type. On a clean
clone, create or relink a credential named `OpsFlow Orchestration` in n8n and
set its token from the local `OPSFLOW_ORCHESTRATION_TOKEN` environment value;
the token is never stored in this repository. Import the workflow, open the
HTTP Request node, and select that credential if n8n did not relink it by name.
The committed file was produced with n8n's `export:workflow --published`
command and sanitized to remove runtime credential IDs and execution data.

Backend states are routed to operator responses as follows: `NEEDS_REVIEW` →
Review Required; `READY_FOR_APPROVAL` → Approval Required; `FAILED_RETRYABLE`
→ Retryable Failure; `FAILED_FINAL` → Final Failure; `PROCESSING` → Processing /
In Progress; `EXTRACTED` → Extraction Complete / Validation Pending. Any other
state uses the safe Unexpected State response.

`FAILED_RETRYABLE` requires a human to use the existing review UI Retry action,
then resubmit the same document with the same event ID. Task 11 has no
automatic transport retry, retry loop, or wait node. n8n owns only transport,
state routing, and operator response; raw document bytes and credentials are
not committed here. n8n runtime hardening and transport-retry decisions are
later work.
