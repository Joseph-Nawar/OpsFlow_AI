# Phase 12 Portfolio Release Design Proposal

## Status and authority

**Status: DRAFT — awaiting human review and approval.** This is a planning
artifact only. It does not authorize implementation, live provider calls,
external mutations, media production, licensing changes, publication, or
deployment.

The approved starting baseline is main SHA
17c155df3b2635f60f88c6596c1d74b02015fb2d. Local main, origin/main, and the
remote main ref agreed at that SHA; the tracked and untracked worktree was
clean. PR #13 is merged at the same SHA. Its post-merge push CI run completed
successfully at [GitHub Actions run 38294788043](https://github.com/Joseph-Nawar/OpsFlow_AI/actions/runs/38294788043).
The PR check rollup also reports successful Backend, Frontend, production
dependency security, and Secret scan jobs.

The Phase 12 planning branch is phase/12-portfolio-release. The canonical
Phase 12 status is IN PROGRESS for planning only; implementation remains NOT
STARTED. Phases 0–11 remain COMPLETE. Historical audit and milestone records
are not rewritten.

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
| Gmail and Slack | Phase 8 documents live dedicated-sandbox Gmail intake, approval reply, Slack delivery, and a clean-clone review-to-approval run. | Separate the existing approval reply and approval Slack event from any post-sync confirmation. | A final Gmail confirmation and final Slack completion signal after successful Odoo and HubSpot synchronization are not implemented. | Requires dedicated test mailbox/workspace, credentials, and separate send authorization; the narrow application behavior change needs human approval. |
| Odoo and HubSpot | Phase 9 adapters, sandbox instructions, synthetic data setup, stable identities, receipts, recovery, and live sandbox evidence exist. | Reuse the full Phase 9 clean-clone procedure while joining it to the real Gmail intake and Phase 8 notification paths. | One captured run that proves all required systems in the requested sequence. Prior separate integration evidence does not satisfy this. | Requires disposable Odoo database, HubSpot developer-test portal, credentials, and separate write authorization. |
| Evaluation and reliability | The provider-free reference records 36/36 passing cases and all five hard gates. Phase 8–11 audits preserve findings, limitations, clean-clone work, and final dispositions. | Summarize selected metrics with their population, mode, source SHA, environment, and evidence links. | Real Gemini quality, latency, authoritative token usage, and model cost remain unmeasured. | A live Gemini demo call and a live evaluation are separately authorized; the full 36-case live evaluator has no bounded-subset/cost-cap option today. |
| Public security and privacy | .gitignore, sanitized workflow exports, credential guidance, production dependency audit, and pinned Gitleaks CI exist. | Recheck full Git history, ignored artifacts, public claims, asset provenance, and current advisories at the release candidate. | A clear public-facing privacy/security note and a documented release disposition for the existing development-only advisories. | Resolve or explicitly approve disposition of current advisories; scan Git history and current files before public-ready acceptance. |
| License and media | Synthetic document fixtures and workflow JSON are tracked. There are no tracked screenshots, demo video, or root LICENSE file. | Keep future screenshots and recordings synthetic, sanitized, small, and provenance-tracked. | Human-selected project license, licensed asset inventory, screenshots, and optional short recorded demo. | Owner chooses code/docs/media license and repository-vs-external media storage; external hosting is optional and separately approved. |
| Independent release audit | Independent phase audits exist through Phase 11. | Reuse their frozen-baseline, evidence-matrix, findings, remediation, and approval conventions. | Final independent Phase 12 audit and documentation closeout. | Must be conducted by a reviewer other than the implementation author and accepted by the human owner. |

The complete-flow gap is substantive. Current Gmail replies are only sent at
ORDER_APPROVED and state that the order was approved for processing. Current
Slack events include approval/review/failure events, not a post-sync completion
event. Phase 8 explicitly says it makes no synchronization or completion claim.
The Phase 9 sync coordinator writes Odoo, then HubSpot, then completes, but it
does not create a completion email or completion Slack event. The existing
approval notification rows are independent, and their delivery order is not
guaranteed. Therefore a runbook alone cannot truthfully satisfy the roadmap's
post-Odoo/HubSpot confirmation-email-then-Slack sequence.

The smallest candidate gap closure reuses the existing notification outbox
and provider workflows: after both Odoo and HubSpot receipts are durably
committed and the order reaches COMPLETED, Python creates a Gmail-provenance
completion reply. A Slack completion intent becomes eligible only after the
Gmail completion reply has a delivered outcome. n8n continues to transport
the backend-owned payloads. This requires a new notification kind, persistence
constraint migration, atomicity/replay tests, and a failure policy for a
failed or unacknowledged email. It is a narrow but real behavior change and
requires human approval before implementation. Existing approval-time Slack
and Gmail messages remain distinct, earlier events and must be identified as
such in the demonstration.

If that behavior change is declined, the full required demo remains NOT
SATISFIED. The project may show a clearly labeled partial demo or prior
Phase 8/9 evidence, but must not relabel the approval reply as a completion
confirmation or claim that the requested ordered workflow was demonstrated.
Changing the roadmap to remove that requirement is an alternative that also
requires explicit human approval.

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

The mandatory portfolio demo uses actual sandbox integrations for every
provider step it claims as live:

1. A synthetic PO arrives in a dedicated Gmail test mailbox and is selected
   by the existing labeled Gmail intake workflow.
2. The workflow forwards the original synthetic source identity and bytes to
   the OpsFlow API. Python's document processor parses the supported source
   and produces canonical content for extraction.
3. A full Applied AI demo requires the actual Gemini provider to extract an
   untrusted structured draft from that processed synthetic document, with a
   separately authorized live call. A fake provider may support local
   rehearsal, but that run is partial and cannot pass the full-demo gate.
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
7. Subject to the approved gap-closure design, Python creates a sender-only
   completion reply for the original Gmail message. Python then enables the
   final Slack completion notification only after Gmail reports delivery.
   Both sends use existing provider transports, fixed backend-owned content,
   durable attempts, and the existing bounded failure handling.

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
portal with the documented synthetic schema, and a configured Gemini account.
The full Applied AI demo additionally requires a separately approved Gemini
call. Without it, label the run partial and do not pass the full-demo gate.

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
| Completion email and Slack | Original sender receives the post-sync confirmation; final Slack message follows its successful delivery acknowledgement; durable delivery outcomes and live UI corroborate the sequence. | Existing approval reply, approval Slack message, a local printout, or an execution-test double. |
| Replay | Re-submit the exact same original message identity and source; show no second logical order or CRM/ERP object and no new completion intent. | A fresh event ID or changed document bytes treated as a replay. |

Evidence should retain only a synthetic demo run identifier, source and order
identities approved for public display, state/event sequence, provider receipt
presence, actual provider record counts, and sanitized screenshots. No raw
mailbox bodies, attachments, access tokens, provider response bodies, personal
addresses, workflow execution history, or private account IDs go into Git.
n8n successful/failed/manual execution-data saving remains disabled.

### Setup, reset, cleanup, replay, and failures

Start from a literal fresh clone at the committed candidate SHA. Use a unique
Compose project name for new PostgreSQL and n8n volumes; create a separate
disposable Odoo database; use the dedicated HubSpot developer-test portal,
Gmail inbox, and Slack channel. Manually relink local credentials. Never copy
an existing .env, n8n volume, database, ignored file, or provider credential
from another checkout. The demo requires no cloud host.

Prepare trusted synthetic Odoo customer/product/inventory and HubSpot
properties before intake. Start the local services, apply migrations, verify
API readiness, import the sanitized workflows inactive, bind credentials,
and then publish/activate only the workflow being rehearsed. Use one fresh
synthetic message and one event identity for the first run; retain the exact
identity only in the local operator notes for the replay check.

On success, verify order and provider record counts before replay, replay the
same source/event, and verify counts and receipts did not increase. On a
preflight, authorization, service, or unexpected-state failure, stop before
approval or business writes and record a bounded failure. Use provider-free
tests for injected timeouts and retry-recovery scenarios; do not induce an
outage or lost acknowledgement in real email/ERP/CRM accounts to make video.

Deactivate workflows after the run. Archive/delete only uniquely identified
synthetic Odoo/HubSpot records according to their provider guides; retain no
Gmail messages beyond the dedicated test mailbox cleanup policy; preserve or
archive Slack evidence only in the dedicated test channel. Remove only the
named disposable local Compose project and volumes after confirming ownership.
Revoke temporary keys after evidence capture. Never use a global volume reset.

Repeatability requires a second literal clean clone, clean tracked tree before
setup, fresh local DB and n8n state, no copied developer files, and manual
credential relinking. Record candidate SHA, tool versions, provider sandbox
types, successful outcome, replay result, cleanup disposition, and deviations.
Historical Phase 8 and Phase 9 clean-clone evidence remains useful context but
does not replace a new whole-flow Phase 12 run.

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
NO_OPTIMIZATION disposition unchanged.

## 6. Human decision register

All entries below are recommendations for review, not approvals.

| Decision | Recommended default | Tradeoff and downstream effect |
| --- | --- | --- |
| Project license | Choose explicitly between a permissive software license such as MIT or Apache-2.0, or intentionally keep the source unlicensed/all-rights-reserved while it remains publicly viewable. Use a separate documentation/media license only if the owner wants those assets reusable under different terms. Review the [MIT text](https://opensource.org/license/mit), [Apache-2.0 text](https://www.apache.org/licenses/LICENSE-2.0), and [GitHub licensing guidance](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository); do not select terms in this plan. | MIT grants broad use subject to retaining its notice; Apache-2.0 provides an express patent license and requires preserving applicable notices; without a license, default copyright generally grants no reuse permission. The owner must choose. Review the Python/npm dependency licenses, Odoo bridge's declared LGPL-3, and all third-party assets/notices before adding a root LICENSE. |
| Demo Gemini call | Require the actual Gemini provider for a full Applied AI demo and authorize its synthetic-data call separately at execution time. | A fake provider supports rehearsal only and leaves the mandatory full demo incomplete. A live call has provider data-handling and possible-cost implications; it is qualitative evidence, not a model-quality evaluation. |
| Completion sequence gap | Approve the narrow existing-outbox completion notification extension described in Section 2, with Gmail delivery success gating final Slack completion. | Satisfies the roadmap sequence through current transports but changes application behavior and requires schema/test work. Declining it leaves the mandatory ordered demo unfulfilled unless the roadmap is explicitly amended. |
| Demo environment | Prefer a full synthetic sandbox run: local Compose services, dedicated test Gmail/Slack, actual Gemini extraction, disposable Odoo Community database, and HubSpot developer-test portal. Use no production/customer accounts. | Gives actual integration evidence and preserves $0 mandatory local development infrastructure, but requires multiple accounts, manual credentials, setup time, separately authorized provider calls/writes/sends, and may incur model spend. Alternatives are a local provider-free walkthrough (local tools only, no provider spend, partial), historical Phase 8/9 evidence (no new spend or credential activity, separately labeled by original date/scope/SHA, partial), or deferring the demo (no service activity, acceptance incomplete). None passes the full-demo gate. |
| Live Gemini evaluation | Retain the documented unavailable evidence by default. | The existing make evaluate-live command is explicitly gated but executes the complete 36-case evaluation corpus; it has no strict small-subset/cost-cap option. It must not be described as a limited measurement. If desired, first approve a separate bounded measurement design and hard call/spend cap; then authorize the live run separately. A single Gemini call in a demo is qualitative evidence, not evaluation. |
| Media | Capture only original application/provider screens with synthetic records; make a concise 60–90 second H.264 screen recording, readable screenshots, and captions. Avoid music and external imagery. Keep raw recordings outside Git and commit optimized deliverables only if each file meets a proposed 20 MiB video / 1 MiB per image cap. | A local-media option avoids new hosting/services but adds repo bytes. An external video host is optional, may introduce privacy/terms/cost dependencies, and requires separate approval. Track authorship/license for any added asset and do not imply vendor endorsement. |
| Public security and privacy | Run pinned full-history Gitleaks and current-content checks, ignored-file checks, production and complete dependency advisory review, workflow/media/license review, and a final privacy/claims audit at the release candidate. Resolve findings or record a narrowly scoped, human-approved disposition. | The repository is already public, so review cannot make past visibility private. The current full npm audit has known High development-tree findings while the production-only audit is documented clean; recheck exact advisories and production exposure rather than claiming they are fixed. |

## 7. Risks, alternatives, and approval gates

| Risk or gap | Recommended treatment | Gate |
| --- | --- | --- |
| Current app has no post-sync confirmation-email or completion-Slack event. | Resolve with the narrowly scoped ordered outbox extension or stop with the mandatory demo marked FAIL. Never call an approval reply a completion email. | Human approves behavior and failure semantics before any code change. |
| Sandbox credentials or accounts have expired or are unavailable. | Recreate/re-authorize dedicated accounts and repeat setup from the clean clone. If that is not possible, report a partial demo only. | Explicit authorization before each email/send/write or potentially charged call. |
| Gemini provider-free fake can be mistaken for model output. | Require actual Gemini for full-demo status; put provider mode in the run record and visible capture; keep quality NOT_APPLICABLE absent an authorized live evaluation. | Claim review checks the provider identity and evidence. |
| A live service may retain or expose synthetic message/record data. | Use dedicated accounts, minimal scopes, unique synthetic identities, sanitized captures, and documented cleanup. | Operator confirms account ownership and cleanup target before actions. |
| New completion notification could duplicate an email after lost acknowledgement. | Keep backend durable retry semantics, document at-least-once behavior, test uncertain outcomes with fakes, and never promise exactly-once delivery. | Independent review of transaction, claims, retry, replay, and provider boundaries. |
| Public licensing or asset rights are unclear. | Do not add third-party visuals or root license until the owner chooses terms and dependency/asset obligations are reviewed. | Human license decision before final public-ready audit. |
| High development-tree npm advisories remain. | Recheck package paths and current advisory details; fix or record a defensible, approved non-production disposition. | Final audit requires documented disposition, not a silent pass. |

No cloud deployment, public release upload, new provider account write, live
Gemini call, live Gmail send, Slack message, Odoo mutation, HubSpot mutation,
or media capture is part of this design task.

## 8. Acceptance and definition of done

The Phase 12 implementation is complete only when:

1. The README and linked architecture/setup/evaluation material accurately
   describe the business problem, implemented behavior, operator boundary,
   $0 mandatory-development-cost posture, and limitations.
2. The clean-clone full demo has evidence from one literal candidate clone and
   real dedicated sandbox providers for Gmail, Gemini extraction, Odoo,
   HubSpot, the final confirmation email, and final Slack completion
   notification in the approved sequence. If any provider step is simulated
   or unavailable, this criterion is FAIL, not silently downgraded.
3. The same-source replay proves one logical order and unchanged actual ERP/CRM
   identity/counts. The case study distinguishes live results, fakes, and
   historical evidence.
4. Every quantitative claim maps to evidence and sample metadata. Model quality,
   usage, latency, cost, manual-step reduction, ROI, savings, and production
   deployment are unavailable unless separately measured and authorized. A
   live extraction shown in the demo is qualitative evidence only.
5. Media contains only synthetic, sanitized, licensed content and follows the
   owner-approved size/storage policy.
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
decomposes Phase 12 into sequential documentation, completion-path,
clean-clone demo, evidence/case-study, media/public-hygiene, and independent
audit milestones. It keeps optional live-Gemini measurement separate from the
mandatory provider-free and actual sandbox gates. This proposal remains a
draft until human review and approval.
