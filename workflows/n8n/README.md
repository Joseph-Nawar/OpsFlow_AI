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

For a clean clone, import the file while the workflow is inactive, create or
relink the `OpsFlow Orchestration` credential, select it in the HTTP Request
node, save the workflow, and use the n8n 2.40.5 editor's `Publish` control
(the runtime activation operation is `POST /rest/workflows/{id}/activate`).
Import alone does not register the production webhook: an inactive disposable
copy returned 404 for its production URL, while the same copy returned 200
after it was published/activated. Use the production URL
`POST /webhook/opsflow-sandbox-intake`; do not use the temporary
`/webhook-test/...` URL as the durable endpoint.

Backend states are routed to operator responses as follows: `NEEDS_REVIEW` →
Review Required; `READY_FOR_APPROVAL` → Approval Required; `FAILED_RETRYABLE`
→ Retryable Failure; `FAILED_FINAL` → Final Failure; `PROCESSING` → Processing /
In Progress; `EXTRACTED` → Extraction Complete / Validation Pending. Any other
state uses the safe Unexpected State response.

`FAILED_RETRYABLE` requires a human to use the existing review UI Retry action,
then resubmit the same document with the same event ID. Task 11 has no
automatic transport retry, retry loop, or wait node. n8n owns only transport,
state routing, and operator response; raw document bytes and credentials are
not committed here.

## Task 12 pinned-runtime evidence

This evidence was collected from the running `n8nio/n8n:2.40.5` image on
2026-09-23. The committed workflow imported into a disposable 2.40.5 data
directory with `active=false`, all 10 nodes recognized, and these node
versions: Webhook 2.1, HTTP Request 4.5, Switch 3.4, and Respond to Webhook
1.5. The credential reference was accepted without a credential ID; a clean
clone must create or relink the named local credential before publishing.

The committed HTTP Request node currently uses Response Format `JSON`,
`Never Error` enabled, and `Include Response Headers and Status` disabled.
In the 4.5 export, these are under
`parameters.options.response.response.responseFormat = "json"`,
`parameters.options.response.response.neverError = true`, and the omitted
`fullResponse` field. A disposable copy with the exact UI option
`Include Response Headers and Status` enabled exported
`parameters.options.response.response.fullResponse = true`; its main output
was an object with `body`, `headers`, `statusCode`, and `statusMessage`.
The later status expression therefore reads `$json.statusCode`, while the
backend response state is at `$json.body.state`.

With `Never Error` enabled, a local-only probe returned normal/main output for
2xx, 401, 409, 422, 500, and 503; the body remained available, and with the
full-response option enabled the corresponding status code and headers were
also available. The real local API separately produced bounded 401
`ORCHESTRATION_UNAUTHENTICATED`, 422 `INVALID_ORCHESTRATION_INTAKE`, and 409
`IDEMPOTENCY_CONFLICT` responses. A real M7C HTTP test produced a 2xx
`FAILED_RETRYABLE` body. That is a lifecycle/business response routed by
`body.state`, not a transport failure and not a retry trigger.

A connection refusal remained a node error even with `Never Error` enabled.
The exact 2.40.5 node setting is `On Error = Continue (using error output)`;
the exported node value is `onError = "continueErrorOutput"`. Its error
output included bounded `error` and `details` objects, including an
`ECONNREFUSED` code, while the normal output remained separate. The standard
runtime also provides Switch 3.4, Edit Fields (Set) 3.x, and Wait 1.x nodes
for status routing, a bounded attempt field, and delay without Code/Function
or business logic. A second HTTP Request can retain the same binary field and
the exact event-ID-to-`Idempotency-Key` expression.

Native Retry On Fail is not selective enough in 2.40.5. Its exact controls are
`Retry On Fail`, `Max. Tries`, and `Wait Between Tries (ms)`, exported as the
node fields `retryOnFail`, `maxTries`, and `waitBetweenTries`. With
`retryOnFail=true`, `maxTries=2`, and a 1 ms wait, HTTP 401, 409, 422, 500,
and 503 each caused two probe requests when `Never Error` was disabled; 2xx
`FAILED_RETRYABLE` caused one. When `Never Error` was enabled, both 401 and
503 correctly stayed on normal output, but neither was retried. There is no
native status filter that simultaneously retries only connection failures and
503.

The frozen Task 12 decision is therefore **Decision B — standard-node-only
fallback**. Task 13 may add full-response status handling, connection-error
output, Switch/If routing, Edit Fields, Wait, and a second request. It may
retry only connection/node transport errors and HTTP 503, preserving the
original binary and event ID. It must not retry 401, 409, 422, generic 500,
or a 2xx `FAILED_RETRYABLE` response; after exhaustion it must return a visible
unavailable response without claiming lifecycle recovery. The budget is
**maximum two transport retry attempts after the initial request**. Task 12
does not modify or enable these retry nodes in the committed workflow; Task 13
owns that implementation.

## Task 13 transport recovery

The workflow now implements the frozen standard-node fallback with three
HTTP Request 4.5 attempts and two one-second time-interval Wait 1.1 nodes.
Each request uses JSON full responses, `Never Error`, and the node-level
`Continue (using error output)` setting. HTTP status switches retry only an
exact numeric `503`; connection errors use the separate error output. The
final exhausted path returns a bounded HTTP 503 `UNAVAILABLE` response.

The original Webhook item is retained through an Edit Fields node and a
Merge 3.2 Combine-by-Position node with unpaired items excluded. This means
the retry branch receives the original binary document only when its Wait
signal arrives, while non-503 responses cannot enter a retry path. All three
attempts preserve the original filename, MIME, document type, optional
`message_id`, and exact `X-OpsFlow-Event-Id` to `Idempotency-Key` mapping.

Runtime verification confirmed one send for 2xx, 401, 409, 422, 500, 2xx
`FAILED_RETRYABLE`, `PROCESSING`, and `EXTRACTED`; three sends for exhausted
503 and connection failure; and identical source identity across the three
503 attempts. The retryable demo seed is available for either lifecycle
origin:

```sh
uv run python scripts/phase7_seed_retryable_demo.py --origin processing
uv run python scripts/phase7_seed_retryable_demo.py --origin extracted
```

`FAILED_RETRYABLE` remains a backend lifecycle response, not a transport
retry trigger. A human must use the existing review Retry action and then
resubmit the same document with the same event ID. Automatic recovery beyond
this bounded transport fallback is outside Task 13.
