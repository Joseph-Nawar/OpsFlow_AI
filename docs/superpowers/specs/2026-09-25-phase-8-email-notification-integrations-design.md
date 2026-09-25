# Phase 8 — Email & Notification Integrations Design

## Document control

| Field | Value |
| --- | --- |
| Repository | Joseph-Nawar/OpsFlow_AI |
| Phase | Phase 8 — Email & Notification Integrations |
| Milestone | M8A — Email & Notification Contract & Design |
| Baseline | main at 407c5fe96063f5790c79747278db98927a3e278a |
| Design branch | phase/8-email-notification-integrations |
| Frozen workflow runtime | n8nio/n8n:2.40.5 |
| Scope | Design and read-only compatibility probe; no product implementation |

Phase 7 is complete at this baseline. The roadmap still says Phases 8–12 are
NOT STARTED. This request explicitly defers the roadmap/status edit; the later
status closeout must mark the parent Phase 8 IN PROGRESS while M8A is underway.
This file is the M8A design artifact. The implementation plan is a later,
separately reviewed artifact and is not part of this task.

## Purpose and success criteria

Phase 8 replaces synthetic transport with recognizable sandbox SaaS
integrations while preserving Phase 7’s authenticated API and state authority.
It delivers three vertical flows:

1. A sandbox Gmail message enters through n8n, reuses
   POST /v1/orchestration/intakes, and enters the existing Phase 2–7 pipeline.
2. A persisted backend notification intent is claimed by n8n, sent to Slack,
   and acknowledged durably.
3. An APPROVED business event for a Gmail-origin order creates a persisted
   intent; n8n replies to its original Gmail message and acknowledges delivery.

Phase 8 does not synchronize an ERP or CRM. Approval wording may say that the
purchase order is approved for processing. It must not claim an ERP order was
created, that synchronization completed, or that the order is COMPLETED.

## Governing boundaries

Python, FastAPI, and PostgreSQL remain authoritative for order lifecycle,
validation, notification eligibility and rendering, durable intent, delivery
claims, attempt limits, retry timing, lease recovery, stale-token rejection,
and terminal delivery state.

n8n owns Gmail polling, email body/attachment transport, simple envelope
normalization, authenticated OpsFlow API calls, Gmail Reply and Slack Send
Message, and reporting the provider result. It has no raw database access and
does not decide business validity, lifecycle destination, approval, retry
authority, notification policy, or ERP/CRM behavior.

Notification transport never changes OrderState. A Slack or Gmail error leaves
the order in its existing authoritative state. Notification delivery is
separate from order audit and review concurrency: do not add audit events for
claims, attempts, or outcomes, and do not write delivery state into the order
or review revision. This preserves Phase 6 ETag behavior.

## Gmail intake contract

### Existing API and source identity

Reuse POST /v1/orchestration/intakes as one multipart document command. The
Gmail workflow sends:

| Part/header | Value |
| --- | --- |
| document | One selected attachment or a normalized plain-text body as a file |
| document_type | EMAIL_BODY, PDF, XLSX, or CSV |
| message_id | The raw Gmail message ID from the message field id |
| source_system | Optional form field; only GMAIL is accepted when present |
| Idempotency-Key | gmail:<raw Gmail message ID> |

For source_system=GMAIL, the backend requires a nonblank message_id and an
Idempotency-Key exactly equal to gmail:<message_id>. The Gmail message ID, not
the thread ID, is the durable source identity. Existing Phase 7 callers may
continue to omit source_system; an arbitrary non-null message_id is not proof
that its source was Gmail.

Persist GMAIL in the existing safe source-document metadata pair representation
as source_system=GMAIL, alongside the raw message_id. In the current JSONB array
shape this is [["source_system","GMAIL"]]. Existing request fingerprinting
includes the source document metadata and SHA-256, so redelivery of the same
Gmail identity and bytes replays the existing order; reuse of that identity
with changed selected bytes conflicts safely with HTTP 409. No second ingestion
pipeline or idempotency table is added.

Do not persist OAuth credentials, sender credentials, full mailbox metadata,
sender email solely for reply, or raw email/attachment bytes. Preserve the
existing backend-derived SHA-256 and source metadata only.

### Deterministic source selection

The Gmail Trigger is configured with Simplify off, attachment download on, and
the attachment prefix attachment_. One Gmail message is one n8n item. Examine
only binary properties with that prefix. Classify a supported business
attachment by its case-insensitive filename suffix:

| Suffix | document_type | Multipart file MIME |
| --- | --- | --- |
| .pdf | PDF | application/pdf |
| .xlsx | XLSX | application/vnd.openxmlformats-officedocument.spreadsheetml.sheet |
| .csv | CSV | text/csv |

Ignore every other attachment and every image/* binary, including normal
signature and inline image assets. The sender-provided MIME value is not the
type authority: the workflow supplies the canonical MIME above, and the
existing Python Phase 3 parser remains responsible for checking file content.
If there is exactly one supported attachment, submit it even when the email
body is non-empty. If there are multiple supported attachments, stop before the
OpsFlow API call with a visible AMBIGUOUS_SUPPORTED_ATTACHMENTS result; create
no order and select no file arbitrarily.

If there are no supported attachments, use the decoded plain-text body. Prefer
the Gmail parser’s text field; if it is absent, convert the parsed HTML body to
visible text with the built-in HTML node. Normalize CRLF and CR to LF, apply
Unicode NFC, trim leading/trailing whitespace, and preserve the remaining text
and line order. Do not remove quoted text or textual signatures. A non-empty
result becomes EMAIL_BODY, filename email-body.txt, MIME text/plain, using
the existing multipart document file part. If unsupported attachments exist
but the normalized body is non-empty, use the body. If the body is empty and
there is no supported attachment, stop before the API call with a visible
NO_SUPPORTED_SOURCE result. No OCR is introduced.

### Mailbox routing and authoritative state

Use a dedicated sandbox Gmail mailbox and a deterministic Gmail UI filter or
manual label named OpsFlow/Intake. The Gmail Trigger monitors only that label;
filter creation is not application code. The label is routing, not an OAuth
permission boundary.

After intake, route only the authoritative API response state, using the Phase
7 response envelope: NEEDS_REVIEW to Review Required,
READY_FOR_APPROVAL to Approval Required, FAILED_RETRYABLE or FAILED_FINAL to a
safe failure result, and PROCESSING or EXTRACTED to In Progress / Validation
Pending. Unexpected responses end visibly and safely. The workflow does not
choose a lifecycle state.

## Durable notification contract

Add one narrow PostgreSQL table, notification_deliveries. It is a durable
notification-intent and delivery record, not an event bus or generic job queue.
Use ordinary string columns with CHECK constraints, matching the repository’s
relational conventions.

| Field | Contract |
| --- | --- |
| id | UUID primary key |
| order_id | UUID FK to orders |
| trigger_audit_event_id | UUID FK to the existing audit event that caused this intent |
| channel | SLACK or GMAIL |
| kind | REVIEW_REQUIRED, APPROVAL_READY, PROCESSING_FAILED, or ORDER_APPROVED |
| payload | Immutable JSONB object; rendered safe delivery data only; maximum 16 KiB |
| status | PENDING, CLAIMED, DELIVERED, or FAILED_FINAL |
| attempt_count | Integer 0–3; increment once per granted claim |
| claim_token | Nullable opaque UUID for the current claim generation |
| claim_expires_at | Nullable timezone-aware timestamp |
| next_attempt_at | Non-null timezone-aware timestamp |
| provider_reference | Nullable bounded string, maximum 256 characters; only a provider’s confirmed message ID/reference |
| last_failure_code | Nullable allowlisted sanitized code, maximum 64 characters |
| created_at, updated_at | Timezone-aware timestamps |

Require UNIQUE(trigger_audit_event_id, channel, kind), a CHECK for supported
channels, kinds, statuses, and attempt_count, and a CHECK that CLAIMED rows
have both claim_token and claim_expires_at while non-CLAIMED rows have neither.
Add a claim-eligibility index over status, next_attempt_at, and claim_expires_at.
Reject payloads that are not JSON objects or exceed 16 KiB. Never persist raw
provider response bodies.

Slack payloads contain the already-rendered top-level text, safe order/PO
reference, authoritative state, bounded issue-count or fixed reason summary,
and review URL. Gmail payloads contain only the raw Gmail message ID and a
deterministically rendered reply body. Payloads never contain raw document
text, raw inbound email, prompts, trusted-data dumps, provider diagnostics,
credentials, or internal exception text.

### Event and channel policy

Create an intent only in the transaction that persists the event below:

| Existing event | Slack kind | Gmail kind |
| --- | --- | --- |
| ORDER_NEEDS_REVIEW or ORDER_REMAINS_NEEDS_REVIEW | REVIEW_REQUIRED | — |
| ORDER_READY_FOR_APPROVAL or ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION | APPROVAL_READY | — |
| ORDER_PROCESSING_FAILED or ORDER_VALIDATION_FAILED | PROCESSING_FAILED | — |
| ORDER_APPROVED | ORDER_APPROVED | ORDER_APPROVED only for a Gmail-provenance source |

A new ORDER_REMAINS_NEEDS_REVIEW event after a human correction is a new
business event and may notify again; reading or replaying the current order
does not create an event or notification. Human Retry itself creates no
notification. A later persisted failure has a new audit-event ID and may
create a new Slack intent.

Gmail ORDER_APPROVED requires the actual READY_FOR_APPROVAL → APPROVED
transition and an authoritative source document with source_system=GMAIL and a
Gmail message_id. Slack ORDER_APPROVED may be created for every actual approval.
The same approval event therefore has distinct Slack and Gmail rows under the
unique key. Phase 9 kinds such as SYNC_FAILED and ORDER_COMPLETED are conceptual
future extensions only; add no Phase 9 rows or enums now.

### Atomic insertion points

Insert each intent before commit, in the existing transaction that persists its
trigger event and state change. Do not call Gmail or Slack in a transaction.
The later implementation plan must place insertion in these existing paths:

- validation routing in application/validation.py, beside
  ORDER_NEEDS_REVIEW or ORDER_READY_FOR_APPROVAL;
- human correction revalidation in application/review_revalidation.py, beside
  ORDER_REMAINS_NEEDS_REVIEW or
  ORDER_READY_FOR_APPROVAL_AFTER_HUMAN_CORRECTION;
- orchestration failure persistence in orchestration/failures.py, beside
  ORDER_PROCESSING_FAILED or ORDER_VALIDATION_FAILED;
- approval in application/review_commands.py, beside ORDER_APPROVED, using
  the locked order’s source-document provenance for Gmail eligibility.

Use the ID of the actual event object as trigger_audit_event_id. Reuse the
existing transaction and order lock; do not create notification-specific order
events or a parallel lifecycle service. A persistence/uniqueness failure rolls
back the business transition and intent together. Delivery changes only
notification_deliveries and never alters the order/audit/review ETag generation.

## Service-only delivery API

Reuse the existing n8n-to-OpsFlow bearer service boundary and server-owned
orchestration identity. Both routes require the orchestration service token;
review-user credentials are not accepted.

### Claim

POST /v1/integrations/notifications/claim takes no business input and claims
exactly one row:

- HTTP 200 returns notification_id, channel, kind, immutable payload,
  attempt_number, fresh claim_token, and claim_expires_at.
- HTTP 204 means no row is currently eligible.
- Eligibility is PENDING with next_attempt_at <= database time, or CLAIMED
  with an expired lease and attempts remaining.
- In one short PostgreSQL transaction, first mark expired CLAIMED rows already
  at attempt_count=3 as FAILED_FINAL without another send; then select one
  eligible row ordered by next_attempt_at, created_at, id with
  FOR UPDATE SKIP LOCKED LIMIT 1.
- Granting a claim sets CLAIMED, increments attempt_count, creates a new UUID
  claim_token, and sets claim_expires_at to database time plus exactly 5
  minutes. The backend’s transaction and row lock are the ownership authority.
  Simultaneous callers cannot receive the same active claim generation.

The notification workflow uses Schedule Trigger every minute and makes one
claim request per execution. It ends on 204. This one-at-a-time cadence is
intentional for the expected low volume.

### Outcome and retry authority

POST /v1/integrations/notifications/{notification_id}/outcome accepts only a
claim_token and one of these bounded shapes:

| Outcome | Additional fields |
| --- | --- |
| DELIVERED | Optional provider_reference, at most 256 characters |
| FAILED | Required failure_code from RATE_LIMITED, AUTHENTICATION_FAILED, PERMISSION_DENIED, TARGET_NOT_FOUND, PROVIDER_UNAVAILABLE, TIMEOUT, DELIVERY_REJECTED, or UNKNOWN_FAILURE; optional integer retry_after_seconds from 0–300 |

The API accepts no arbitrary provider body, exception text, credential, or
timestamp. A valid success sets DELIVERED and records only the bounded
provider_reference. For a matching, unexpired CLAIMED token, a failed attempt
with attempt_count below 3 returns to PENDING, clears the claim, and sets
next_attempt_at using backend time. Attempt 3 becomes FAILED_FINAL. A
missing/unknown notification is 404; a malformed outcome is 422; an expired,
incorrect, or superseded token is 409 STALE_NOTIFICATION_CLAIM with no row
mutation; service authentication failure is 401; persistence unavailability
is a bounded 503 with no provider text.

The backend schedules retry after 30 seconds following attempt 1 and 120
seconds following attempt 2. When a valid Slack Retry-After hint is supplied,
use max(base delay, min(hint, 300 seconds)). The backend chooses and persists
next_attempt_at; n8n does not sleep, increment attempts, or decide terminal
state. Invalid/missing hints use the fixed base delay. Expired attempt 1 or 2
may be reclaimed immediately under a new token. An expired attempt 3 becomes
FAILED_FINAL, never a fourth send. Authentication failures also consume only
these bounded attempts; they do not loop indefinitely.

The API accepts outcomes only for the current matching unexpired claim. It
rejects a stale token even if the provider send may have succeeded. An
acknowledgement can itself be lost, so an external message may be sent again
after lease expiry. PostgreSQL cannot share a transaction with Gmail or Slack:
Phase 8 guarantees durable intent, one active OpsFlow claim token, duplicate
intent suppression, at most three claims, and business-state isolation. It does
not guarantee exactly-once external messages. Any duplicate is limited to the
notification; it cannot duplicate order creation, approval, or future ERP work.

## Notification workflows

### Durable dispatcher: workflows/n8n/opsflow-notification-dispatch.json

Schedule Trigger → authenticated claim → stop on 204 → Switch on channel →
native Slack Message / Send or Gmail Message / Reply → normalize the bounded
provider result → authenticated outcome report.

There is one claimed item per execution. Provider node errors use an error
output that reports only an allowlisted failure_code and an optional bounded
Retry-After integer. If the Slack node’s 2.40.5 error output does not expose
that header, omit the hint and let Python apply its fixed backoff. Never retry
the provider node inside n8n. Do not add a database node, AI node,
order-state mutation, review command, ERP/CRM call, Slack approval buttons,
interactive commands, modals, Slack authentication, or Slack-triggered Retry.

Set OPSFLOW_REVIEW_BASE_URL to an absolute local application origin, such as
http://localhost:5173. Validate that it has no userinfo, query, or fragment and
append /review/<order-id>; this matches the existing React route. The link
contains no token. The recipient still needs normal OpsFlow operator
authentication; Slack grants no review access. Keep the target Slack channel
configured in the local n8n workflow/editor, outside tracked application code.

### Gmail intake: workflows/n8n/opsflow-gmail-intake.json

Gmail Trigger → deterministic body/attachment envelope normalization → source
identity preservation → authenticated existing intake API → authoritative
state routing. The Phase 7 synthetic intake workflow remains intact. The Gmail
workflow may determine attachment count/bytes, body fallback, filename/type
transport mapping, and raw Gmail message ID; it never determines business
validity, customer validity, approval, policy, or lifecycle destination.

### Gmail approval reply

Use native Gmail Message → Reply with the persisted raw Gmail message ID,
plain-text deterministic body, Reply to Sender Only enabled, no attachment,
and n8n attribution disabled. The frozen Gmail 2.2 node supports all four
options. Do not persist a customer email address solely for reply; the Gmail
node resolves the original message recipients from Gmail.

## n8n 2.40.5 compatibility probe

The local frozen image reports n8n 2.40.5. It was run with docker run --rm,
without credentials, mounted data, mailbox access, Slack access, or external
message sends. Findings below come from the image’s packaged node definitions
and compiled implementation; they are not credential-backed executions.

| Node type | Available frozen version | Verified capability |
| --- | --- | --- |
| n8n-nodes-base.gmailTrigger | 1.4 (also 1, 1.1–1.3) | Message Received polling; label IDs, Gmail search, sender and read-status filters; max 50 per poll |
| n8n-nodes-base.gmail | 2.2 (also 1, 2, 2.1) | Message → Reply accepts messageId; supports Reply to Sender Only and disabling attribution |
| n8n-nodes-base.slack | 2.7 (also 1, 2, 2.1–2.6) | Message → Send maps to Slack chat.postMessage |
| n8n-nodes-base.scheduleTrigger | 1.4 | Scheduled notification polling |
| n8n-nodes-base.httpRequest | 4.5 | Authenticated API calls; multipart form-data can attach a named binary field |
| n8n-nodes-base.switch | 3.4 | Route returned state or channel |
| n8n-nodes-base.if | 2.3 | Deterministic count/body branches |
| n8n-nodes-base.set (Edit Fields) | 3.5 | Set/keep derived fields and binary data |
| n8n-nodes-base.moveBinaryData | 1.1 | Built-in JSON-to-binary conversion for body-only EMAIL_BODY multipart upload |

For Gmail Trigger 1.4, the packaged definition has one Message Received event,
poll filters including labelIds and Gmail q search, and options
downloadAttachments and dataPropertyAttachmentsPrefixName. Simplify defaults
to true; turn it off to retrieve the parsed body and attachments. The runtime
parser assigns binary property names attachment_0, attachment_1, and so on,
using the attachment prefix and parser enumeration index. It returns one item
per message with multiple binary properties and removes the attachment list
from JSON. The packaged parser does not filter inline image parts and does not
retain their disposition/content-ID in the binary metadata. Filtering must
therefore count supported filename/MIME candidates, not all binary keys.

The installed Set expressions, If/Switch, Move Binary Data, and HTTP Request
multipart binary field are sufficient for a standard-node implementation:
enumerate attachment_ keys, derive count/type/selected field, and dynamically
map the selected binary field; for a body, convert normalized text to a
text/plain email-body.txt binary part. No Code node is authorized by this
probe. Workflow contract tests and the M8C manual acceptance must prove these
expressions and multipart mapping in the running 2.40.5 editor/runtime before
the committed workflow is frozen.

Exact Gmail live item JSON, real label-filter behavior, actual MIME/body
normalization, attachment bytes, binary metadata in execution output, and
limited-scope OAuth compatibility are not proven by static node definitions.
M8C must use a dedicated test mailbox and pass all source-selection and
multipart cases below before committing its workflow. Do not use a real
mailbox in this compatibility probe. For Slack, the packaged Message → Send
path calls chat.postMessage; whether a failed 429 node output exposes the
Retry-After header is not proven statically. M8D must forward it only if a
bounded integer is visible; otherwise omit it and use the backend’s fixed
schedule.

## OAuth, Slack permissions, credentials, and cost

The n8n 2.40.5 Gmail OAuth2 credential’s default scopes include
https://mail.google.com/, gmail.modify, gmail.compose, Gmail labels, and
add-on scopes. Do not use these defaults. Set Custom Scopes and request only:

- https://www.googleapis.com/auth/gmail.readonly — the Gmail Trigger reads
  bodies/attachments; Gmail Reply also reads original headers and the profile.
- https://www.googleapis.com/auth/gmail.send — Gmail Reply sends the
  acknowledgement.

Google classifies gmail.readonly as restricted and gmail.send as sensitive.
gmail.readonly is mailbox-wide; the OpsFlow/Intake filter does not narrow OAuth
access. This is why Phase 8 requires a dedicated sandbox mailbox. A public
multi-user product would need Google OAuth verification for these scopes and a
security assessment if restricted Gmail data is stored on or transmitted
through servers. That production work is outside Phase 8.

Use an External Google OAuth app in Testing with only the dedicated sandbox
mailbox listed as a test user. Testing mode shows an unverified-app warning,
allows up to 100 test users, and expires user authorization/refresh tokens
after seven days; reauthorize the sandbox account as needed. Testing mode does
not make these scopes suitable for public distribution.

For Slack, use one sandbox app/bot and only chat:write for chat.postMessage.
Invite the bot to the one configured test channel; do not request
chat:write.public. Slack generally limits posting to one message per channel
per second and returns HTTP 429 with Retry-After seconds when rate limited.
The low-volume one-claim cadence is below that normal rate; backend retry still
handles rate limits caused by other traffic.

Gmail, Slack, and the existing OpsFlow service token live only in n8n
credential storage. Continue protecting that store with the existing
N8N_ENCRYPTION_KEY in local .env. Workflow exports may have sanitized
credential names/references only. Commit no credentials, OAuth client secret,
refresh/access token, Slack token, live message, attachment, or execution
history. n8n may carry message bytes transiently during the workflow; no raw
email or attachment is added to persistent OpsFlow state or source fixtures.

Mandatory development cost remains $0: local n8n Community, existing
PostgreSQL/API/frontend, a Gmail sandbox/test account, a Slack development
workspace, and synthetic documents. CI uses fakes/local services only; Gmail,
Slack, and LLM calls are not automated-test dependencies.

## Testing and acceptance

| Layer | Required evidence |
| --- | --- |
| Unit | Notification contracts; safe immutable payload rendering; status/claim invariants; attempt/backoff schedule; token validation; failure-code and Retry-After normalization |
| PostgreSQL integration | Atomic event+intent insertion; uniqueness by event/channel/kind; concurrent one-owner claim; lease recovery/fresh token; stale-token rejection; attempt exhaustion; success; retry; final failure; rollback consistency |
| API | Service auth; claim 200 and 204; malformed input; unknown notification; stale outcome; bounded errors; no provider text leakage |
| Lifecycle regression | Phase 6 ETags and review commands; Phase 7 orchestration, redelivery/retry generation, and business state |
| Workflow contract | Allowed node types/versions and connections; exact OpsFlow endpoints/mappings; credential hygiene; no secrets, execution state, database/AI/business-state mutation |
| CI | Fake/local only; no Google OAuth, Slack network, live email, or LLM dependency |
| Manual sandbox | Real test Gmail account and Slack development workspace; no real customer data |

M8C credential-backed Gmail gate: import the candidate into n8n 2.40.5, use
only the dedicated test mailbox and requested custom scopes, label test
messages OpsFlow/Intake, and prove (1) unlabelled mail is ignored; (2) one PDF,
XLSX, or CSV is sent as the matching multipart file/type; (3) text-only mail is
sent as EMAIL_BODY; (4) unsupported attachments plus non-empty text choose the
body; (5) multiple supported attachments stop before OpsFlow with no order;
(6) inline image/signature-only plus empty text stops with no order; (7) a
signature image alongside one supported document does not increase the
supported count; (8) source_system, raw message_id, and gmail:<message_id> are
exact; and (9) same identity/bytes replays one order while changed selected
bytes produce 409 and no second order. Inspect actual Gmail output only in the
local test execution; remove execution data after evidence capture.

M8D credential-backed Slack gate: send one native-node message to the invited
sandbox channel with top-level text, persist only its message timestamp as
provider_reference, acknowledge success, and verify failure normalization and
backend scheduling using deterministic local/API tests. If a real or controlled
429 response exposes Retry-After, prove it is bounded before reporting it.

M8E Gmail reply gate: approve a Gmail-origin order in the existing review UI,
prove the reply lands in the original test thread and only replies to sender,
verify the truthful approval wording, report the provider reference, and prove
a failure leaves APPROVED unchanged.

### Required adversarial matrix

| # | Scenario | Acceptance |
| --- | --- | --- |
| 1 | Same Gmail message observed twice | Same key and bytes replay one order; no duplicate authoritative order |
| 2 | Same Gmail identity with changed selected bytes | Backend returns safe 409 conflict; no new order |
| 3 | Exactly one supported attachment | Process that attachment, not the email body |
| 4 | No supported attachment and valid body | Submit EMAIL_BODY |
| 5 | Multiple supported attachments | Safe ambiguous workflow failure before API; no arbitrary selection/order |
| 6 | Unsupported-only attachments and empty body | Safe no-source failure before API; no order |
| 7 | Slack unavailable | Notification retries/fails independently; order state unchanged |
| 8 | Gmail Reply unavailable | Delivery retries/fails independently; APPROVED unchanged |
| 9 | Worker dies after claim, before send | Expired lease is reclaimed with a new token if attempts remain |
| 10 | Provider accepts send, worker dies before acknowledgement | Duplicate notification is possible after recovery; no exactly-once claim or business duplicate |
| 11 | Concurrent claimers | PostgreSQL grants one active claim generation per row |
| 12 | Claim lease expires | Next claim has a fresh token and increments attempts |
| 13 | Stale outcome token | HTTP 409; no row mutation |
| 14 | Attempt 3 fails or expires | FAILED_FINAL; no fourth send |
| 15 | Slack rate limit with Retry-After | Bounded hint only; backend computes persisted retry time |
| 16 | Invalid/revoked Gmail or Slack credential | At most three claims, safe final notification failure, no secret/provider text leak |
| 17 | Notification lifecycle | Claim/outcome does not change order review ETag generation |
| 18 | Slack review URL | Link requires normal OpsFlow operator access |
| 19 | Workflow export | No live body, attachment, token, credential secret, or execution data |
| 20 | Phase 9 boundary | No ERP/CRM behavior, SYNCING execution, or COMPLETED confirmation exists |

### M8E clean-clone/demo exit

From a clean clone: install/start PostgreSQL, API, n8n, and frontend; create or
relink Gmail, Slack, and OpsFlow credentials; configure the Gmail label/filter
and Slack target; import/publish both committed workflows; email a synthetic
PO; prove Gmail → OpsFlow intake and Slack notification; review/approve in the
UI; prove Gmail reply to the original test thread; show delivery records; verify
duplicate/retry behavior; and confirm no secret, live email/document, or
runtime execution data became tracked.

## Phase 8 implementation sequence

| Milestone | Frozen scope |
| --- | --- |
| M8A — Email & Notification Contract & Design | Approved design, 2.40.5 compatibility probe, design spec, then a separately reviewed implementation plan |
| M8B — Durable Notification Delivery Core | Migration, contracts/model/repository, safe payload rendering, atomic insertion, claim/outcome API, retry/concurrency semantics, unit/PostgreSQL/API tests |
| M8C — Gmail Intake Workflow | Gmail → n8n → existing intake → authoritative state routing, including sandbox Gmail verification |
| M8D — Slack Notification Delivery | Durable intent → claim → n8n → Slack → outcome acknowledgement |
| M8E — Gmail Reply & Cross-Boundary Hardening | Gmail reply, complete failure/retry matrix, clean-clone docs, credentials, final sandbox demo |
| M8F — Independent Phase 8 Audit & Closeout | Whole-phase audit → collect all findings → one consolidated remediation batch → differential verification → audit artifact → status closeout → PR/merge → post-merge main CI |

M8F does not stop at the first LOW or MEDIUM finding. This task creates no
implementation plan, workflow, migration, test, dependency, roadmap/status
change, implementation, or PR.

## Explicit non-goals

No Odoo, HubSpot, ERP/CRM mutation, SYNCING execution, synchronized/COMPLETED
customer confirmation, Gmail Pub/Sub push, Outlook, generic IMAP, tenant
mailboxes, customer portal, Slack approval buttons/commands/modals, Gmail
approval links, public multi-user Google OAuth distribution, production IAM,
Kafka, Redis, Celery, generic queue, notification analytics, cloud deployment,
Kubernetes, or OCR.

## Repository authorities and external facts

Repository authorities: [roadmap](../../roadmap/project-roadmap.md),
[system overview](../../architecture/system-overview.md),
[domain model](../../architecture/domain-model.md),
[development guide](../../development/development-guide.md),
[Phase 7 design](2026-09-22-phase-7-n8n-workflow-orchestration-design.md),
[Phase 7 plan](../plans/2026-09-22-phase-7-n8n-workflow-orchestration.md),
[Phase 7 audit](../../audits/phase-7-audit.md), [Phase 7 workflow
guide](../../../workflows/n8n/README.md), and [existing synthetic
workflow](../../../workflows/n8n/opsflow-sandbox-intake.json).

First-party external facts checked 2026-09-25:

- [n8n Gmail Trigger](https://docs.n8n.io/integrations/builtin/trigger-nodes/n8n-nodes-base.gmailtrigger/)
  supports polling, labels, Gmail search, sender/read filters, and bounded
  message counts; [Gmail Message operations](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.gmail/message-operations/)
  confirms Reply uses Message ID, supports Reply to Sender Only, and allows
  attribution to be disabled.
- [Google Gmail scopes](https://developers.google.com/workspace/gmail/api/auth/scopes)
  classifies gmail.readonly as restricted and gmail.send as sensitive;
  [Google’s Workspace data policy](https://developers.google.com/workspace/workspace-api-user-data-developer-policy)
  describes the restricted data handling implications. [Google OAuth Testing
  mode](https://support.google.com/cloud/answer/15549945?hl=en) limits test
  users and expires test authorizations after seven days.
- [n8n Slack node](https://docs.n8n.io/integrations/builtin/app-nodes/n8n-nodes-base.slack/)
  provides Message → Send; [Slack chat.postMessage](https://api.slack.com/methods/chat.postMessage)
  requires chat:write for bot tokens and documents channel membership and
  chat:write.public; [Slack rate limits](https://api.slack.com/apis/rate-limits)
  documents per-channel posting limits and HTTP 429 Retry-After behavior.
