# Phase 12 Portfolio Release Design Proposal

## Status and authority

**Status: APPROVED for Phase 12 planning only.** The human owner approved this
design direction at planning SHA `90b33e7b041f11796b755e9bd5e9bf0d835d0ae7`,
subject to the completion-notification and full-demo acceptance clarifications
recorded below. This approval does not authorize M12A–M12F implementation,
live provider calls, external mutations, media production, licensing changes,
publication, or deployment. Every implementation milestone remains NOT
STARTED pending its separate authorization and review gate.

The approved starting baseline is main SHA
17c155df3b2635f60f88c6596c1d74b02015fb2d. Local main, origin/main, and the
remote main ref agreed at that SHA; the tracked and untracked worktree was
clean. PR #13 is merged at the same SHA. Its post-merge push CI run completed
successfully at [GitHub Actions run 38294788043](https://github.com/Joseph-Nawar/OpsFlow_AI/actions/runs/38294788043).
The PR check rollup also reports successful Backend, Frontend, production
dependency security, and Secret scan jobs.

The Phase 12 planning branch is phase/12-portfolio-release. The canonical
Phase 12 status is IN PROGRESS for approved planning; implementation and
milestones M12A–M12F remain NOT STARTED. Phases 0–11 remain COMPLETE.
Historical audit and milestone records are not rewritten.

This proposal interprets the approved [Phase 12 roadmap](../../roadmap/project-roadmap.md)
and the [Phase 11 design](2026-10-07-phase-11-evaluation-optimization-design.md)
and [Phase 11 implementation plan](../plans/2026-10-07-phase-11-evaluation-optimization.md).
The roadmap remains authoritative if any wording differs. The project keeps
its existing boundaries: AI interprets source documents, deterministic
software validates and authorizes business actions, Python owns business
logic and persisted state, and n8n owns thin orchestration and provider
transport.

## 1. Goal and non-goals

### Goal

Present OpsFlow AI as a credible, concise portfolio project for prospective
freelance clients and Applied AI engineering recruiters. A reader should
quickly understand the purchase-order problem, see the implemented system
work end to end, reproduce the local setup, inspect evidence behind each
technical claim, and understand the system's limits.

### Non-goals

- Turn OpsFlow into a hosted or commercial product.
- Add cloud deployment, a new platform, a general-purpose demo framework,
  or new business integrations.
- Claim production deployment, customer adoption, ROI, cost savings, or a
  production SLA.
- Replace the approved Phase 11 evaluation contract, baseline, corpus, or
  NO_OPTIMIZATION decision.
- Treat provider-free fakes, integration-test doubles, or previous runs as
  current live-provider results.
- Publish media, change repository visibility, select a license, or execute
  external operations without the relevant separate human authorization.

Local and open-source infrastructure remains the default, with $0 mandatory
development cost. Optional model usage and any other potentially billable
provider action remain separate choices.

## 2. Existing assets and release gaps

| Roadmap requirement | Complete and reusable | Present, needs release refinement | Missing and required | Human decision or external dependency |
| --- | --- | --- | --- | --- |
| Business problem and solution | README describes B2B purchase-order automation and the production-style portfolio goal. | Put the problem, decision boundaries, outcome, and demo link before the exhaustive historical phase log. | A compact first-screen portfolio narrative and visual demo entry point. | Human review of public framing and claims. |
| Architecture and technical explanation | System overview defines AI/deterministic and Python/n8n boundaries; domain model defines the order contract. | Update current implementation wording and explain the implemented Gmail, review, notification, Odoo, HubSpot, and evaluation boundaries. | A short recruiter/client-facing explanation connected to the existing deep documentation. | Human review that explanations stay within implemented behavior. |
| Local setup | README, Makefile, Compose, .env.example, development guide, and pinned tool versions exist. | Distill the currently valid clean-checkout path and link to the correct integration-specific procedures. | A single top-level path from clone to the full portfolio demo and teardown. | Local-only setup has no external prerequisite; real demo setup depends on credentials/accounts listed below. |
| n8n workflows | Four sanitized, version-controlled workflows target n8n 2.40.5; exports use credential-name references and avoid provider secrets. | Connect their separate intake, sync, and notification procedures into one honest runbook. | A recorded Phase 12 rehearsal combining the whole business path from a literal clean clone. | Dedicated provider accounts, local credential setup, and separate authorization for each external send/write. |
| Synthetic data | The Phase 7 synthetic PO, fixture preparation, and 36-case Phase 11 corpus/trusted catalog are committed. The active evaluation corpus is 3.0.0. | Select one stable synthetic demo identity and keep it distinct from benchmark ground truth. The existing Phase 7 sample has stale dates that may require an explicit human review correction. | A rehearsed, documented demo input and matching isolated trusted Odoo data, with no private business records. | Human confirms chosen synthetic identities and dates; Odoo/HubSpot setup requires dedicated disposable sandbox environments. |
| Gmail and Slack | Phase 8 documents live dedicated-sandbox Gmail intake, approval reply, Slack delivery, and a clean-clone review-to-approval run. | Separate the existing approval reply and approval Slack event from any post-sync confirmation. | Post-sync Gmail confirmation and Slack completion events are not implemented. | Requires dedicated test mailbox/workspace, credentials, separate send authorization, and owner approval of any application behavior change. |
| Odoo and HubSpot | Phase 9 adapters, sandbox instructions, synthetic data setup, stable identities, receipts, recovery, and live sandbox evidence exist. | Reuse the full Phase 9 clean-clone procedure while joining it to the real Gmail intake and Phase 8 notification paths. | One captured run that proves all required systems in the requested sequence. Prior separate integration evidence does not satisfy this. | Requires disposable Odoo database, HubSpot developer-test portal, credentials, and separate write authorization. |
| Evaluation and reliability | The provider-free reference records 36/36 passing cases and all five hard gates. Phase 8–11 audits preserve findings, limitations, clean-clone work, and final dispositions. | Summarize selected metrics with their population, mode, source SHA, environment, and evidence links. | Real Gemini quality, latency, authoritative token usage, and model cost remain unmeasured. | A live Gemini demo call and a live evaluation are separately authorized; the full 36-case live evaluator has no bounded-subset/cost-cap option today. |
| Public security and privacy | .gitignore, sanitized workflow exports, credential guidance, production dependency audit, and pinned Gitleaks CI exist. | Recheck full Git history, ignored artifacts, public claims, asset provenance, and current advisories at the release candidate. | A clear public-facing privacy/security note and a documented release disposition for the existing development-only advisories. | Resolve or explicitly approve disposition of current advisories; scan Git history and current files before public-ready acceptance. |
| License and media | Synthetic document fixtures and workflow JSON are tracked. There are no tracked screenshots, demo video, or root LICENSE file. | Keep future screenshots and recordings synthetic, sanitized, and provenance-tracked. | Human-selected project license, licensed asset inventory, sanitized screenshots, and a concise public demo video. | Owner chooses code/docs/media license and repository-vs-external media storage; external hosting is optional and separately approved. |
| Independent release audit | Independent phase audits exist through Phase 11. | Reuse their frozen-baseline, evidence-matrix, findings, remediation, and approval conventions. | Final independent Phase 12 audit and documentation closeout. | Must be conducted by a reviewer other than the implementation author and accepted by the human owner. |

The complete-flow gap is substantive. Phase 8 Gmail replies are created at
`ORDER_APPROVED` and state only that the order was approved for processing.
Its Slack events cover review, approval, and failure; channel delivery rows
have independent outcomes and at-least-once external delivery. Phase 9's sync
completion transaction verifies durable Odoo and HubSpot receipts, transitions
the order to `COMPLETED`, and records `ORDER_SYNC_COMPLETED` atomically, but it
creates neither a completion email nor a completion Slack event. The original
roadmap described confirmation email followed by Slack; the approved Phase 12
clarification makes both actual post-sync notifications mandatory while
explicitly removing relative external delivery order as a correctness
invariant. Both events must be causally tied to completed Odoo/HubSpot
synchronization and evidenced independently.

The smallest candidate application change is **Option A**: in the existing
Phase 9 completion transaction, reuse its `ORDER_SYNC_COMPLETED` audit event
identity and add independently safe Gmail and Slack outbox intents after all
Odoo/HubSpot receipts pass. A Gmail intent is eligible only for persisted
Gmail provenance; Slack reports successful synchronization regardless of
customer-email delivery. Each row
uses the existing durable claims, stable event/channel/kind identity,
bounded retries and `FAILED_FINAL` handling. Reuse the completion audit-event
identity and the existing uniqueness constraint to make replay idempotent.
This requires a new notification kind, persistence constraint migration,
backend-owned payloads and focused atomicity/replay tests. The owner has
approved this business contract at design level; that decision does not
authorize implementation. It preserves current approval-time notification
meanings and the known at-least-once delivery limit. If Gmail permanently
fails or times out, Slack can still report completed synchronization. If
Gmail accepts a message but its durable acknowledgement is lost, its row may
retry and duplicate the email; Slack's eligibility remains independent.
Python continues to own intent eligibility, durable claims, retries, and
outcomes; n8n remains the thin provider-transport boundary. Both completion
intents are created only after the Odoo and HubSpot durable receipts satisfy
the existing completion transaction.

Option A does **not** enforce Gmail-before-Slack delivery, and the approved
demo contract does not require it. The current dispatcher claims due rows by
eligibility time, creation time, and row identity; it has no channel-priority
or prerequisite control, and no such control will be added solely to order
the demonstration. Record actual provider outcomes and timestamps. Acceptance
requires both genuine post-sync deliveries and durable evidence that their
intents arose from successful Odoo/HubSpot completion; relative delivery
timestamps do not affect correctness. Do not stage provider results or claim
that one channel always delivers first.

Option B would make Slack completion claim eligibility depend on the matching
Gmail completion row reaching durable `DELIVERED`. This guarantees ordering of
recorded acknowledgements only, not physical exactly-once provider behavior.
If Gmail permanently fails after its bounded attempts, Slack remains
withheld; if Gmail times out or accepts a send while its acknowledgement is
lost, the row may retry and duplicate the email before Slack is released. The
existing contract has no operator retry/requeue or reconciliation endpoint,
so recovery would require new supported operator actions and clear handling
for an email that may already have been accepted. For non-Gmail source orders,
there is no eligible Gmail reply to gate on; the contract would need an
explicit exception to release Slack on sync completion or would suppress that
signal indefinitely. This couples a truthful
operations signal about completed ERP/CRM work to an unrelated customer-mail
delivery result and can hide successful order completion. It is more
operationally complex than the roadmap's demonstrated chronology warrants.

Option C makes no application change. The demo can show the existing
approval-time notifications and a separately labeled Odoo/HubSpot completion,
but it cannot claim post-sync notification events or pass the current full
demo acceptance. A narrower demo would require a separately approved roadmap
acceptance amendment. It must not be silently substituted for the existing
requirement.

The owner has selected and approved Option A at design level: Slack reports
successful order synchronization independently of customer email delivery,
while Gmail independently confirms completion to a genuinely Gmail-origin
sender/thread. Both actual deliveries remain mandatory for the full demo and
must be causally tied to successful Odoo/HubSpot synchronization. Record each
provider outcome and timestamp, but do not gate acceptance on their relative
order. This approved clarification changes the current Phase 12 acceptance
wording only; it does not rewrite Phases 0–11. M12B implementation still needs
its separate milestone authorization and independent code review. A runbook
or presentation edit cannot substitute for the application behavior.

## 3. Audience and presentation

The primary readers are:

- A freelance buyer who needs confidence that the project handles a real
  document-to-business-system workflow safely.
- An Applied AI recruiter or engineering interviewer evaluating system
  boundaries, extraction, deterministic rules, human authority, integration
  safety, recovery, evaluation, and cost awareness.

The README should lead with the business problem, what OpsFlow automates,
what still requires a person, one truthful demo, and an easy local-start link.
Then it should explain the architecture, safety boundaries, integrations,
evaluation, limitations, stack, and checks. Detailed setup and audits remain
in their current documents; the README should link to them instead of copying
them.

The technical discussion should explain existing design decisions rather
than promise future features: why n8n is thin, why Python owns business
authority, why extracted values remain untrusted, why high-value approval is
human-controlled, how stable identities and receipts support replay, and
what the provider-free evaluation proves.

## 4. Demonstration architecture

### Required sequence

The roadmap requires a demonstrated extraction stage, but it does not name a
live Gemini request or request count. This proposal recommends one actual
Gemini extraction on synthetic input as stronger Applied AI evidence; this is
a separate proposed criterion and requires a one-request cap and explicit
spend ceiling before use. The extraction stage must still be shown through the
application; if a provider-free adapter is used, label it as a rehearsal and
do not call it a live Gemini result. The mandatory portfolio sequence uses
actual sandbox integrations for every provider step it claims as live:

1. A synthetic PO arrives in a dedicated Gmail test mailbox and is selected
   by the existing labeled Gmail intake workflow.
2. `workflows/n8n/opsflow-gmail-intake.json` sends the original synthetic
   source identity and bytes to `POST /v1/orchestration/intakes`. Python's
   document processor parses the supported source and produces canonical
   content before extraction. A direct provider prompt that bypasses this
   application path is not demo evidence.
3. The application extraction stage produces an untrusted structured draft
   from the processed synthetic document. For the proposed stronger evidence,
   use one actual Gemini extraction subject to separate authorization for at
   most one generation request and
   an owner-approved spend ceiling. A fake provider may support local
   rehearsal, but that run is partial and cannot pass the live-Gemini
   evidence criterion. If the provider or credentials are unavailable at
   preflight, make zero calls and stop. Before calling, verify that the full
   intake path's automatic HTTP retries, idempotent redelivery, lease recovery,
   and human Retry action cannot cause a second provider invocation. If that
   one-call bound cannot be established, do not call Gemini. A timeout or
   ambiguous result consumes the one-call budget; deactivate/stop the intake
   and do not retry, fall back, or make another call without fresh explicit
   authorization.
4. Python deterministically checks the extracted fields against trusted
   synthetic business data. The model cannot validate or approve the order.
5. The React review application presents provenance, evidence, validation
   issues, trusted references, and the current state. A distinct reviewer
   credential may correct fields and save/revalidate. A distinct approver
   credential explicitly approves. No direct database seeding or workflow
   approval is allowed.
6. The existing n8n order-sync workflow invokes the Python-owned coordinator.
   Real disposable Odoo receives the sale order first; the real HubSpot
   developer-test portal receives the company/deal/association after it.
   Only the successful Odoo and HubSpot receipts permit completion.
7. Subject to an explicitly approved M12B contract, after confirmed Odoo and
   HubSpot receipts Python creates a sender-only completion reply for the
   original Gmail message and an independent Slack completion event. Under
   approved Option A, both intents are created only after successful Odoo and
   HubSpot synchronization with durable receipts. Either channel can be
   delivered or retried independently; Slack reports completed
   synchronization even if Gmail is delayed or fails. Both actual deliveries
   are required for the full demo. Capture their provider outcomes and
   timestamps; relative delivery order is not an acceptance condition.

The existing approval-time Gmail reply and Slack event can still occur before
ERP/CRM synchronization. The demo must distinguish these from the final
post-sync completion notifications. External notification delivery remains
at-least-once; the demo and case study must not claim physically exactly-once
email or Slack delivery.

### Services, accounts, and trusted synthetic data

Required local components are Git, Docker Compose, PostgreSQL 16, the API,
n8n 2.40.5, Python 3.12 with uv, Node.js 24/npm, and the React review UI.
Required external sandbox dependencies are a dedicated Gmail test mailbox,
a dedicated Slack workspace/channel and app, a disposable Odoo Community
database with the least-privilege bridge user, a HubSpot developer-test
portal with the documented synthetic schema, and (for the proposed live
extraction) a configured Gemini account. The live extraction remains a
separate unapproved operation. Without a preflight-ready provider and
separate authorization for one call and its spend ceiling, stop with zero
calls and label the live-Gemini evidence criterion incomplete.

The operator prepares distinct local orchestration, reviewer, and approver
credentials. Gmail OAuth, Slack bot credentials, Odoo API key, HubSpot service
key, and optional Gemini key remain only in the ignored local .env or the
local n8n credential store as appropriate. Odoo/HubSpot provider secrets do
not enter n8n. The Gmail label does not limit OAuth scope, so the mailbox itself
must be dedicated. Only synthetic sender, customer, product, PO, and
attachment data may be used.

If the full sandbox is unavailable, the truthful alternatives are:

- A local provider-free walkthrough using existing fakes and the review UI.
  It needs only the local Compose toolchain, no external credentials, and no
  provider spend, but it proves no live Gmail, Gemini, ERP, CRM, email, or Slack
  step and remains a partial demo.
- A separately labeled presentation of existing Phase 8/9 live integration
  evidence. It needs no new account operation or provider spend, but each clip
  or record must retain its original date, scope, and source SHA; separate
  historical runs do not prove one ordered end-to-end run.
- Defer the full demonstration. This avoids credential and spend requirements
  while leaving the mandatory Phase 12 demo acceptance incomplete.

Use the existing [Phase 9 Odoo/HubSpot E2E and clean-clone guide](../../development/phase9-n8n-sync-e2e.md),
[Odoo sandbox guide](../../development/odoo-m9c-sandbox.md),
[HubSpot sandbox guide](../../development/hubspot-m9d-sandbox.md), and
[n8n workflow guide](../../../workflows/n8n/README.md). The Phase 12 work
should add a concise whole-flow entry to the existing Phase 9 runbook rather
than duplicate its detailed sandbox procedures.

### Visible stages and evidence

| Stage | Live evidence to capture | Evidence that is not a substitute |
| --- | --- | --- |
| Gmail intake | Dedicated mailbox contains the synthetic message; the real Gmail workflow selected its source and the OpsFlow source provenance refers to that message. | A curl/local webhook or fake Gmail message labeled as live Gmail. |
| Document processing | API/order evidence identifies the original source and document hash; the committed processor supports and parses the synthetic file format before extraction. | A manually prepared prompt or a provider-only call that skips the application's document processor. |
| Extraction | Review UI shows the persisted untrusted extracted draft and source evidence; show the provider mode explicitly. | Provider-free 36/36 results or fake-provider output presented as Gemini accuracy. |
| Deterministic validation | UI shows the route and issue facts derived from trusted synthetic catalog/inventory and server rules. | LLM explanation alone or a prerecorded validation screen. |
| Human review and approval | Reviewer correction/revalidation if needed, then separate approver credential and persisted approval audit event. | Direct SQL, n8n node, or shared reviewer/approver token. |
| Odoo and HubSpot | Order state is COMPLETED; durable receipts exist; actual sandbox contains exactly one OpsFlow-identified sale order, one uniquely identified company/deal, and the expected association. | Fake adapters, mocked HTTP responses, or historical integration-test output. |
| Completion email and Slack | Both actual post-sync deliveries must be causally tied to successful Odoo/HubSpot synchronization and supported by durable completion receipts and notification outcomes. Capture each provider outcome and timestamp; relative delivery order is immaterial. | Existing approval reply, approval Slack message, a local printout, an execution-test double, staged provider success, or an assertion that one provider always delivers first. Missing or failed delivery on either channel fails the full-demo criterion. |
| Replay | Re-submit the exact same original message identity and source; show no second logical order or CRM/ERP object and no new completion intent. | A fresh event ID or changed document bytes treated as a replay. |

Evidence should retain only a synthetic demo run identifier, source and order
identities approved for public display, state/event sequence, provider receipt
presence, actual provider record counts, and sanitized screenshots. No raw
mailbox bodies, attachments, access tokens, provider response bodies, personal
addresses, workflow execution history, or private account IDs go into Git.
n8n successful/failed/manual execution-data saving remains disabled.

### Setup, reset, cleanup, replay, and failures

**Local infrastructure and configuration reproducibility:** Use a literal
fresh clone at the committed candidate SHA. Use a unique Compose project name
and fresh PostgreSQL and n8n volumes. Never copy an existing
`.env`, n8n volume, database, ignored file, or provider credential from
another checkout. A second clone verifies only that local setup can be
reproduced with fresh state and documented configuration. It does not
authorize any provider call, send, write, account change, or charge. This
local check requires no external service and no cloud host.

**One newly verified live sandbox transaction and exact-source replay:**
Run the one newly authorized business transaction from one clean candidate
clone at that SHA. Before any external operation, positively verify the
dedicated Gmail mailbox, Slack workspace/channel, fresh disposable Odoo
database, and HubSpot developer-test portal. Confirm unique synthetic
identities and that the targets contain no conflicting records. Prepare
trusted synthetic Odoo
customer/product/inventory and HubSpot properties. Start fresh local
services, apply migrations, verify API readiness, import sanitized workflows
inactive, bind approved credentials, and activate only the workflow needed
for this run. Use one synthetic source and one event identity. Retain exact
replay identifiers only in protected local operator notes. Do not globally
reset accounts or delete unrelated records.

On success, verify order and provider record counts before replay, then submit
the exact retained synthetic source bytes to the authenticated intake with
the original Gmail message identity and idempotency key. This exact-source
replay does not re-fetch Gmail. Verify there is no second logical order,
ERP/CRM business record, or completion intent. The replay should stand down
through existing idempotency and must not make another Gemini call or send
or write to downstream providers. If preflight or authorization fails, stop
before approval or business writes. After a stage failure or unexpected
state, stop subsequent actions, preserve state, and record a bounded failure.
A timeout or ambiguous provider acknowledgement is not permission to repeat
the run. Use provider-free tests for injected timeouts and recovery scenarios;
do not induce an outage or lost acknowledgement in real accounts to make
evidence.

**Additional provider operations:** A successful first run may require Gmail
message retrieval; one authorized Gemini generation request; Odoo customer,
product, and inventory lookups plus an order write; HubSpot lookup and
Company/Deal/association operations; and both existing approval-time and
post-sync Gmail/Slack sends if each notification path is eligible. Before
execution, list each provider, target, permitted read/write/send, retry
ceiling, and spend ceiling in a separate authorization, including any
account cleanup or key revocation. Existing bounded retries may repeat a
provider attempt; the authorization must account for that risk. If any result
is uncertain, stop and reconcile against durable receipts and the uniquely
identified sandbox targets before asking for a fresh authorization. A second
clean clone is local-only and never authorizes additional live operations.

Deactivate workflows after the run. Archive/delete uniquely identified
synthetic Odoo/HubSpot records, remove Gmail messages, archive Slack evidence,
or revoke temporary keys only when that exact cleanup action has separate
explicit authorization. Otherwise leave the external state intact and report
the cleanup limitation. Remove only the named disposable local Compose
project and volumes after confirming ownership. Never use a global volume
reset.

Record the candidate SHA, tool versions, local-state identifiers, verified
provider sandbox types, individual authorized operation counts/outcomes,
completion timestamps, exact replay result, cleanup disposition, and
deviations. If footage is approved, capture the M12C run once for both
verification and M12E editing; do not repeat external operations just to
collect media. Historical Phase 8 and Phase 9 clean-clone evidence and
provider-free demonstrations remain useful context but do not replace a new
whole-flow Phase 12 run.

## 5. Evidence-to-claim contract

| Claim area | Reusable evidence and proposed presentation | Limits and unavailable evidence |
| --- | --- | --- |
| Automated PO processing | A newly recorded live sandbox trace links Gmail source provenance to persisted order state and actual Odoo/HubSpot receipts. Say the workflow automates intake, draft extraction, deterministic routing, and approved synchronization. | Human approval remains required. The live all-provider run has not yet been captured. |
| Structured extraction | Show one live demo extraction only if the actual Gemini provider was used and the screen/source confirms it. Link the [Phase 11 live-Gemini unavailable record](../../evaluation/reference/phase-11-live-gemini-unavailable.md) for current status. | Real Gemini quality is unmeasured. One illustrative extraction is not an accuracy metric. Provider-free extraction status stays NOT_APPLICABLE. |
| Deterministic validation | The [committed Phase 11 provider-free reference](../../evaluation/reference/phase-11-provider-free-baseline.md) reports 7/7 deterministic-violation routes; its 36/36 run passes the hard gates. Attribute these to the Phase 11 corpus and reference, not live Gemini. | Does not prove that Gemini extracts correctly or that all real business data is covered. |
| Human authority and exception routing | The [provider-free reference](../../evaluation/reference/phase-11-provider-free-baseline.md) reports zero invalid orders executed (0/13), 100% deterministic-violation routing (7/7), safe malformed/security handling (4/4), and zero direct LLM side effects (0/36). The UI/audit trail shows separate review and approval. | The unit of evidence is this synthetic corpus and these tested boundaries. |
| Duplicate protection and idempotency | The [provider-free reference](../../evaluation/reference/phase-11-provider-free-baseline.md) reports duplicate blocking 4/4; the real sandbox demo must show stable identities, one logical order, durable Odoo/HubSpot receipts, and unchanged counts on exact replay. | External email and Slack delivery are at-least-once and can duplicate after a lost acknowledgement. Do not claim physical exactly-once. |
| Replay and recovery | The [provider-free reference](../../evaluation/reference/phase-11-provider-free-baseline.md) reports recovery 3/3; prior provider-specific tests cover safe retry and receipts. The demo may show a normal same-source replay only. | Do not turn provider-free outage tests into live service outage claims. A historic missing immediate retry-command return state remains documented. |
| Reliability and security | Cite the Phase 8–11 audits, current PR/CI evidence, full-history secret scan, current production dependency audit, and actual live demo receipts separately. | Local/demo bearer authentication is not production IAM; process-local metrics reset; health is last-observed; a provider can accept a send while its acknowledgement is lost; PostgreSQL outage can leave bounded recovery failure. |
| Latency and performance | The [committed provider-free reference](../../evaluation/reference/phase-11-provider-free-baseline.md) records parse p95 1.511 ms (38 samples), validation p95 0.027375 ms (35), provider-free intake p95 104.683166 ms (30), replay p95 102.078792 ms (8), and recovery p95 114.783042 ms (4), on its recorded Darwin/arm64, Python 3.12, PostgreSQL 16 environment. Label them local observations and preserve source links. | No live Gemini/provider latency is measured. Small local samples are not production SLAs. The [approved Phase 11 decision](../../evaluation/reference/phase-11-baseline-decision.md) is NO_OPTIMIZATION; no performance gain is established. |
| Provider use and API cost | The [provider-free reference](../../evaluation/reference/phase-11-provider-free-baseline.md) has zero Gemini calls, no authoritative token usage, and cost NOT_APPLICABLE. A live run may claim usage/cost only from authoritative provider tokens and a matching dated pricing snapshot. | The [live-Gemini unavailable record](../../evaluation/reference/phase-11-live-gemini-unavailable.md) preserves that current live tokens, provider latency, and Gemini cost are unmeasured. Zero calls in a provider-free run is not evidence of zero real usage or zero model cost. |
| Manual-step reduction | Present the workflow map and identify the required human review/approval and sandbox credential setup. A recorded run can count visible human actions as observations. | No before/after manual-work baseline or time study exists. Do not claim a percentage, hours, ROI, or cost savings. |

The case study should carry evidence links, corpus/run SHA, mode, sample
counts, environment, and limitations near each numeric statement. Preserve
the existing reference JSON, Markdown, corpus sources, and Phase 11
NO_OPTIMIZATION disposition unchanged. The provider-free 36/36 PASS is
correctness and safety evidence, not real Gemini extraction accuracy. Live
Gemini quality, aggregate provider latency, authoritative token totals, and
model cost remain unavailable without separately approved valid measurements.

## 6. Human decision register

The completion-notification contract and demo acceptance clarification below
are approved at planning level. The remaining choices are recommendations for
human decision, not approvals.

| Decision | Recommended default | Tradeoff and downstream effect |
| --- | --- | --- |
| Project license | Choose explicitly between a permissive software license such as MIT or Apache-2.0, or intentionally keep the source unlicensed/all-rights-reserved while it remains publicly viewable. Use a separate documentation/media license only if the owner wants those assets reusable under different terms. Review the [MIT text](https://opensource.org/license/mit), [Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0), and [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository); do not select terms in this plan. | MIT grants broad use subject to retaining its notice; Apache-2.0 provides an express patent license and requires preserving applicable notices; without a license, default copyright generally grants no reuse permission. The owner must choose. Review the Python/npm dependency licenses, Odoo bridge's declared LGPL-3, and all third-party assets/notices before adding a root LICENSE. |
| Demo Gemini call | The roadmap requires an extraction stage but does not expressly mandate a live Gemini call. Recommend strengthening the portfolio demo with one actual Gemini generation request on the synthetic document. Before that request, require an explicit authorization naming provider/model, at most one request, and a concrete maximum spend in currency; if no spend ceiling is approved, do not call. | This is qualitative evidence only, not an accuracy evaluation. The existing SDK disables HTTP retries, but an ambiguous timeout still consumes the one-call budget. If credentials/provider are unavailable at preflight, stop with zero calls; do not fall back or retry without fresh authorization. No live quality, aggregate latency, authoritative tokens, or model cost becomes available from one call. |
| Completion notification contract | **Approved: Option A.** After durable Odoo and HubSpot receipts pass in the existing completion transaction, reuse `ORDER_SYNC_COMPLETED` identity and the durable notification outbox to create a Gmail-source-provenance-bound reply to the original sender/thread and an independent Slack completion intent. Preserve independent bounded retry/outcomes, idempotent logical intents, and at-least-once external delivery. | Preserves approval-time semantics and lets Slack report successful sync independently of customer-email delivery. Both actual post-sync provider deliveries are mandatory for the full demo, but their relative delivery order is not a correctness invariant. No channel-priority scheduling, operator API, or generalized framework is approved. Implementation still requires a separate M12B authorization and code review. |
| Demo environment | Prefer one full synthetic sandbox run: local Compose services, dedicated test Gmail/Slack, one authorized Gemini call, disposable Odoo Community database, and HubSpot developer-test portal. First verify targets and unique disposable identities. A second clone is a local setup check only. | Gives new end-to-end evidence but requires accounts, credentials, setup, and separately approved external operations. Existing provider retries can repeat attempts, so authorization must name targets, operation/retry ceilings, and any spend cap. Alternatives are a local provider-free rehearsal or historical Phase 8/9 evidence, each explicitly partial, or deferring live execution; none substitutes for the required full demo. |
| Live Gemini evaluation | Retain the documented unavailable evidence by default. This approved design does not request or authorize the full 36-case live evaluation. | The existing `make evaluate-live` command executes the complete 36-case evaluation corpus; it has no strict small-subset/cost-cap option. It must not be described as a limited measurement. If desired later, first approve a separate bounded measurement design and hard call/spend cap; then authorize that distinct live run. A single Gemini call in a demo is qualitative evidence, not evaluation. |
| Media | Make a professionally edited, approximately 90–120 second public video a normal required portfolio deliverable, with readable capture of the actual user workflow and provider evidence, captions, and sanitized screenshots. Capture the authorized M12C run once for both demo verification and M12E editing. Use synthetic-data and sandbox disclosures, and keep an inspectable unedited run record privately where appropriate. | Keep raw captures out of Git. Do not use an arbitrary size cap that harms legibility. Recommend an optimized MP4 and VTT in the repository when practical; if repository size or playback is impractical, ask the owner to approve a suitable public external host after reviewing privacy, terms, availability, and possible cost. No media capture, upload, or production is authorized by this approved design. Review every frame and asset license; no credentials, private identifiers, account details, or non-synthetic data. |
| Public security and privacy | Run pinned full-history Gitleaks and current-content checks, ignored-file checks, production and complete dependency advisory review, workflow/media/license review, and a final privacy/claims audit at the release candidate. Resolve findings or record a narrowly scoped, human-approved disposition. | The repository is already public, so review cannot make past visibility private. The current full npm audit has known High development-tree findings while the production-only audit is documented clean; recheck exact advisories and production exposure rather than claiming they are fixed. |

## 7. Risks, alternatives, and approval gates

| Risk or gap | Recommended treatment | Gate |
| --- | --- | --- |
| Current app has no post-sync confirmation-email or completion-Slack event. | Implement only the owner-approved Option A contract at a separately authorized M12B implementation gate. Keep approval-time notifications distinct and never call an approval reply a completion email. | The design decision is approved at SHA `90b33e7b041f11796b755e9bd5e9bf0d835d0ae7`; M12B implementation is not authorized by that approval. Independent review must approve transaction, idempotency, failure, retry, and recovery semantics. |
| Sandbox credentials or accounts have expired or are unavailable. | Recreate/re-authorize dedicated accounts and repeat setup from the clean clone. If that is not possible, report a partial demo only. | Explicit authorization before each email/send/write or potentially charged call. |
| Gemini provider-free fake can be mistaken for model output. | Recommend one actual Gemini generation request for stronger demo evidence, separately authorized with a one-request budget and explicit spend ceiling. Put provider mode in the run record and visible capture; a fake remains labeled as a rehearsal. | If unavailable before invocation, stop with zero calls; after timeout/ambiguity, do not retry. Claim review keeps quality, aggregate latency, tokens, and model cost unavailable absent valid separately approved measurement. |
| A live service may retain or expose synthetic message/record data. | Use dedicated accounts, minimal scopes, unique synthetic identities, sanitized captures, and documented cleanup. | Operator confirms account ownership and cleanup target before actions. |
| Independent notification delivery may produce different timing or a failure on either channel. | Under approved Option A, retain independent bounded delivery and durable outcomes. Both successful actual deliveries are required for the full demo, but Gmail does not gate Slack; record each outcome and timestamp without ordering claims. | The M12B implementation gate reviews atomic intent creation, Gmail provenance, stable identities, idempotency, retries, failure outcomes, and at-least-once behavior. No relative delivery-time requirement applies. |
| Public licensing or asset rights are unclear. | Do not add third-party visuals or root license until the owner chooses terms and dependency/asset obligations are reviewed. | Human license decision before final public-ready audit. |
| High development-tree npm advisories remain. | Recheck package paths and current advisory details; fix or record a defensible, approved non-production disposition. | Final audit requires documented disposition, not a silent pass. |

No cloud deployment, public release upload, new provider account write, live
Gemini call, live Gmail send, Slack message, Odoo mutation, HubSpot mutation,
or media capture is authorized by this planning approval.

## 8. Acceptance and definition of done

The Phase 12 implementation is complete only when:

1. The README and linked architecture/setup/evaluation material accurately
   describe the business problem, implemented behavior, operator boundary,
   $0 mandatory-development-cost posture, and limitations.
2. The demo has new evidence from one literal candidate clone and actual
   dedicated sandbox operations for the roadmap's email intake, Odoo,
   HubSpot, post-sync confirmation email, and Slack completion stages. It
   exercises the application document-processing and extraction stages,
   deterministic validation, and human review/approval. Actual provider
   identity and outcomes are recorded; fakes and prior integration evidence
   cannot stand in for claimed live steps. The proposed single live Gemini
   call is a separately authorized strengthening of the roadmap's extraction
   stage; absent authorization it is not called or described as live. Both
   actual post-sync Gmail confirmation and Slack completion deliveries are
   required and causally tied to successful Odoo/HubSpot synchronization with
   durable receipts. Record actual outcomes and timestamps; their relative
   delivery order is not a correctness invariant. Missing or failed delivery
   on either channel makes the full demo incomplete. A second clone verifies
   local setup only.
3. The same-source replay proves one logical order and unchanged actual ERP/CRM
   identity/counts. The case study distinguishes live results, fakes, and
   historical evidence.
4. Every quantitative claim maps to evidence and sample metadata. Model quality,
   usage, latency, cost, manual-step reduction, ROI, savings, and production
   deployment are unavailable unless separately measured and authorized. A
   live extraction shown in the demo is qualitative evidence only.
5. Required media includes sanitized screenshots and a professionally edited
   approximately 90–120 second public demo video captured from the same
   authorized M12C run. It contains only synthetic, sanitized, licensed
   content, clear sandbox disclosures, and no unsupported metrics. Raw source
   footage and inspectable execution records remain private where appropriate;
   owner approves repo or external delivery and storage.
6. A human-approved licensing disposition (including an intentional
   all-rights-reserved/no-license choice) and all dependency/asset obligations
   are recorded; privacy, history, ignored files, security advisories,
   generated artifacts, and secrets receive release-candidate disposition.
7. CI, clean-clone setup, provider-free evaluation, relevant tests, migration,
   dependency checks, documentation links, and full-history secret scanning
   pass at the final candidate SHA.
8. A reviewer independent of the implementation authors a Phase 12 audit with
   no unresolved release-blocking findings; human approval and status closeout
   are recorded only after that PASS.

The repository remains understandable and locally runnable; no cloud host,
new framework, or required paid provider service is introduced. The final
audit reports branch, candidate SHA, audit SHA, commits, clean tree, checks,
manual evidence, limitations, costs, and any accepted residual risks.

## 9. Proposed milestone boundary

The linked [implementation plan](../plans/2026-10-12-phase-12-portfolio-release.md)
decomposes Phase 12 into M12A portfolio framing/onboarding, M12B approved
completion-notification behavior, M12C full sandbox demonstration/local
reproducibility, M12D evidence-backed case study, M12E media/licensing/privacy/
public hygiene, and M12F independent release audit/closeout. It keeps optional
live-Gemini evaluation separate from the proposed one-call qualitative demo
evidence. This design is APPROVED for planning only; implementation remains
NOT STARTED and separately gated.
