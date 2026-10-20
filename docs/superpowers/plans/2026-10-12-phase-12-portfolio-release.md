# Phase 12 Portfolio Release Implementation Plan

> For agentic workers: use the repository's single-agent, sequential workflow. Execute one separately authorized milestone at a time and stop at its review gate. Planning approval authorizes no implementation.

**Goal:** Make OpsFlow AI a locally reproducible, evidence-backed portfolio project with a truthful sandbox demonstration and release-ready documentation.

**Architecture:** Reuse the existing React review app, Python/FastAPI business services, PostgreSQL state and receipts, and n8n provider workflows. M12B implements the owner-approved Option A completion-notification contract and is COMPLETE after independent review and human approval. The originally planned demonstration uses actual dedicated sandbox providers for every step described as live; the 2026-10-18 owner-approved M12C amendment accepts the specific segmented run and preserves its automated-intake limitation. Gmail and Slack post-sync delivery order is not a correctness invariant.

**Tech stack:** Existing Python 3.12, uv, FastAPI, PostgreSQL 16, Docker Compose, React/TypeScript/Vite, Node.js 24/npm, n8n 2.40.5, current provider adapters, Make targets, CI, and pinned Gitleaks. No new framework or mandatory paid service.

**Spec:** [Phase 12 Portfolio Release Design Proposal](../specs/2026-10-12-phase-12-portfolio-release-design.md)

## Plan status and execution gates

This plan was approved for Phase 12 planning by the human decision referencing planning SHA `90b33e7b041f11796b755e9bd5e9bf0d835d0ae7`. The approved starting main SHA is `17c155df3b2635f60f88c6596c1d74b02015fb2d`; the designated branch is `phase/12-portfolio-release`. Current status: Phases 0–11 are COMPLETE; Phase 12 is IN PROGRESS; M12A–M12C are COMPLETE, with M12C accepted under the owner-approved limited-scope amendment after independent PASS review and human approval; M12D–M12F are NOT STARTED. M12C-3 remains factually PARTIAL for the original uninterrupted automated Gmail intake criterion. See the [M12C review disposition](../../audits/phase-12-m12c-review.md). The original planning gate still governs future work: each next milestone requires its stated review gate and separate authorization.

The work unit is one milestone. The next milestone cannot begin until its prerequisites, acceptance evidence, review, and human approval are recorded. All execution remains on the designated Phase 12 branch with a clean, reviewed diff. Do not use subagents or parallel agents unless the owner separately changes the repository's single-agent instruction.

## Global Constraints

- The Phase 12 roadmap and approved design are authoritative; this plan does not silently relax the original demo contract. The dated owner-approved M12C amendment below is the explicit, narrow exception for the 2026-10-18 run.
- AI output remains untrusted extraction. Deterministic Python code and trusted business data own validation, approval, persistence, and external mutation.
- n8n remains limited to triggers, sequencing, transport, and simple routing.
- Use only synthetic source, customer, product, PO, mailbox, and CRM/ERP records.
- Keep $0 mandatory local development cost; no cloud host or required paid model call.
- All live Gemini calls, email sends, Slack sends, Odoo writes, HubSpot writes, account changes, and potentially charged operations need separate explicit authorization at execution time.
- No provider-free fake, mock, prior integration test, screenshot recreation, or historical evidence may be represented as an actual live provider step.
- Keep the Phase 11 corpus, committed reference results, evidence contract, and NO_OPTIMIZATION outcome unchanged.
- Keep known dependency advisories and public privacy/security qualifications accurately disclosed until their release-candidate disposition is evidenced and approved.
- Do not claim real Gemini accuracy, provider latency, authoritative token usage, model cost, production performance, ROI, savings, customer adoption, or deployment without the corresponding evidence.
- Keep provider credentials, raw messages, attachments, private IDs, execution history, and local state out of tracked files and media.
- Do not change repository visibility, create a release, publish a deployment, or open/merge a PR as part of the milestones unless separately authorized.

## Review Focus

1. **Approval mistaken for completion:** completion mail and final Slack must refer to successful Odoo/HubSpot receipts, not ORDER_APPROVED.
2. **Fake extraction presented as Gemini:** the roadmap requires extraction; this plan recommends one real Gemini request as a stronger demo. Provider identity must be visible; fake output remains rehearsal evidence.
3. **Notification coupling or false ordering:** Phase 8 channels are independent and at-least-once. The owner selected Option A: both post-sync intents depend on successful Odoo/HubSpot completion, but Slack delivery is independent of Gmail delivery. Both actual deliveries are required for the full demo; relative delivery timing is not a correctness criterion.
4. **Repeated or ambiguous live operations:** fresh local clone state is reproducibility evidence only. One approved transaction/replay does not authorize new calls, sends, or writes on a second clone or after an uncertain result.
5. **Unsupported metrics, media, or license claims:** every public claim maps to evidence; required video/screens are sanitized and licensed; license terms remain an owner decision.

---

## Milestone M12A — Portfolio framing and onboarding

**Objective:** Make the first README screen, architecture explanation, current status, and clean-checkout setup usable by a client or recruiter without replacing detailed technical guides.

**Prerequisites:** Human approval of the Phase 12 design and this milestone plan is recorded. This planning approval does not authorize M12A implementation; M12A begins only after separate explicit authorization. Keep Phase 12 status IN PROGRESS / approved planning until an implementation milestone is authorized. Implementation remains NOT STARTED until then.

**Reuse:** README, system overview, domain model, development guide, Makefile, .env.example, Compose, workflow README, Phase 9 E2E, and Phase 8–11 audits.

**Files:**

- Modify: README.md
- Modify: docs/architecture/system-overview.md
- Modify: docs/development/development-guide.md
- Modify: docs/roadmap/project-roadmap.md only for current Phase 12 status and approved closeout facts; preserve historical status paragraphs.

**Required deliverables:** A clear README narrative and valid clean-clone onboarding; accurate architecture, status, and documentation links. Update the roadmap only to reflect already approved current status or final closeout facts.

**Optional enhancements:** A compact architecture diagram if it improves comprehension and can be produced from existing architecture; no new diagram framework or duplicate setup guide.

**Work and acceptance:**

- Reorder the README so business problem, solution, current human authority, demo entry point, and quick start precede the long historical status narrative.
- Keep detailed setup instructions in existing guides; add links instead of copying Phase 8/9 sandbox procedures.
- Correct the architecture guide's current-implementation and target-diagram wording without changing authority boundaries.
- Link the README demo entry to detailed existing provider guides and state that new whole-flow evidence is pending.
- Distinguish current phase status from historical audit snapshots. Phase 12 may say IN PROGRESS (planning or approved implementation) only while work is active; implementation remains NOT STARTED until an approved implementation task begins.
- Every setup command must be runnable from a clean clone without copying ignored files or relying on an existing DB, n8n volume, or developer account state.
- Link to the existing provider-specific procedures; do not copy their full contents into the README.

**Verification:**

- Run the repository's standard-library relative Markdown link check across README.md and docs; expected result: every local target exists.
- Review README commands against Makefile, .env.example, Compose, pinned runtimes, and the linked sandbox guides.
- Run git diff --check; expected result: no whitespace errors.
- No application tests are added for this documentation-only milestone.

**External services and authorization:** None for docs. Do not start services, set up accounts, or invoke provider APIs.

**Review gate:** Human review checks all current-status claims, audience clarity, command accuracy, and links. M12B cannot begin until M12A is accepted and separate M12B implementation authorization is recorded; its Option A behavior contract is already approved at design level.

**Non-goals:** No feature work, demo capture, license selection, dependency changes, new setup framework, or cloud hosting.

## Milestone M12B — Approved completion-notification behavior

**Current status:** M12B is COMPLETE. Its separate implementation authorization, technical remediation at `282a0ae6a7db4ab989f6b2c768142cf34c21098c`, independent PASS audit at `78a05c5f904d94d77f71622164bf252ed7c1c1ad`, and human approval are recorded in the roadmap and [M12B audit](../../audits/phase-12-m12b-review.md). The requirements below are the historical implementation contract; the original planning approval alone did not authorize that work.

**Objective:** Implement the owner-approved Option A post-sync completion-notification contract without adding a Gmail-before-Slack dependency.

**Prerequisites:** M12A accepted. Option A is approved at design level by the human decision referencing SHA `90b33e7b041f11796b755e9bd5e9bf0d835d0ae7`; this does not authorize M12B implementation. A separate explicit implementation authorization and code-review gate are required. Options B and C remain documented alternatives, not approved paths.

**Reuse:** Existing Phase 8 notification intent/outcome contract, stable event/channel/kind uniqueness, five-minute claims, bounded retries and final failure, Gmail sender-only approval reply, independent Slack payload, n8n transport, Phase 9 `complete_order_sync()` receipt checks and transaction, and existing database-safety guards.

**Approved behavior contract:** In the existing successful completion transaction, reuse the `ORDER_SYNC_COMPLETED` audit event identity and durable notification outbox to insert independent Gmail and Slack completion intents only after Odoo and HubSpot durable receipts pass and the order is completed. Gmail is eligible only with persisted Gmail-source provenance and replies to the original sender/thread. Slack reports successful synchronization regardless of Gmail delivery. Preserve stable event/channel/kind uniqueness for logical-intent idempotency, independent durable outcomes and bounded retries, and at-least-once external delivery semantics. Existing approval-time notifications remain separate. Do not introduce channel-priority scheduling, new operator APIs, or a generalized notification framework solely to order the demo.

**Alternatives assessed, not selected:** Option B would gate Slack eligibility on durable Gmail `DELIVERED`, withholding an operational sync signal on permanent Gmail failure and requiring recovery for timeout or lost acknowledgement; it adds coupling and does not prevent duplicate email after an ambiguous send. Option C would leave the application unchanged and cannot meet the approved full-demo requirement. The owner selected Option A and clarified that delivery order is not a correctness invariant, so neither B nor a roadmap amendment is needed.

**Required deliverables:** Implement only the approved contract. Record actual independent provider outcomes and preserve the Phase 8/9 transaction, stable identities, idempotency, retries, and at-least-once limits. Acceptance must prove that neither notification intent can exist before successful sync with both durable receipts; both channel outcomes remain independent. No test or acceptance criterion asserts relative Gmail/Slack delivery order.

**Anticipated implementation files for approved Option A (not authorized to modify yet):**

- Modify: src/opsflow/application/order_sync.py
- Modify: src/opsflow/notifications/contracts.py
- Modify: src/opsflow/notifications/payloads.py
- Modify: src/opsflow/notifications/service.py
- Modify: src/opsflow/persistence/models.py
- Create: alembic/versions/0008_phase12_completion_notifications.py
- Modify: tests/unit/notifications/test_contracts.py
- Modify: tests/unit/notifications/test_payloads.py
- Modify: tests/unit/notifications/test_service.py
- Modify: tests/unit/workflows/test_phase8_notification_dispatch_contract.py
- Modify: tests/integration/test_phase9_order_sync_claims.py
- Modify: tests/integration/test_phase9_order_sync_atomicity.py
- Modify: tests/integration/test_phase8_notification_persistence.py
- Modify: tests/integration/test_phase8_notification_migrations.py
- Modify: workflows/n8n/README.md
- Modify: docs/development/phase9-n8n-sync-e2e.md

**Acceptance and verification after separate M12B implementation authorization:**

- Add failing tests first for non-completed state, missing Odoo/HubSpot receipts, Gmail provenance and original sender/thread routing, non-Gmail behavior (Slack intent remains eligible; Gmail reply is absent), same-transaction creation, reuse of `ORDER_SYNC_COMPLETED` identity, replay uniqueness, independent provider outcomes, bounded retries/final failure, Gmail permanent failure, Slack independence, and lost outcome acknowledgement.
- Confirm expected failures, then implement only the approved narrow contract and a forward-only migration for the new notification kind.
- Run focused notification and sync tests: `uv run pytest tests/unit/notifications tests/unit/workflows/test_phase8_notification_dispatch_contract.py -q --no-cov`.
- Run isolated Phase 8/9 integration suites, including migration and transaction/claim tests, against fresh guarded disposable databases; all focused tests pass and no live-provider suite runs.
- Run `uv run alembic upgrade head` and `uv run alembic current` against a fresh disposable database; expected head is `0008_phase12_completion_notifications`.
- Run `docker compose config --quiet` and `make check` with newly identified disposable databases; expected configured quality gates pass.
- Verify n8n transports backend-owned notification payloads and does not decide business eligibility. Tests must not assert channel delivery order. Test that Slack reports successful sync independently of Gmail delivery while each channel retains its own retry and durable outcome.

**External services and authorization:** Local fakes and disposable PostgreSQL only for implementation verification. No real email, Slack, Odoo, HubSpot, Gemini, or potentially charged operation. Any later live demo calls/writes/sends need separate explicit authorization listing the provider, target, operation count/retry bound, and spend ceiling where applicable.

**Review gate:** The design decision is already recorded, but it is not implementation authorization. Coding begins only after M12A acceptance and a separate explicit M12B implementation authorization. After implementation, independent code review approves transaction safety, migration, Gmail provenance, stable/replay identity, notification meanings, independent outcomes/retries, failure semantics, and the at-least-once limitation. M12C requires accepted M12B implementation. Relative external delivery order is not reviewed as a correctness requirement.

**Optional enhancement:** None proposed. Do not add channel scheduling or operator APIs unless a separately reviewed design proves necessary for an approved contract.

**Non-goals:** No new provider, generalized notification framework, changed approval authority, direct API provider call, exactly-once claim, workflow engine, silent roadmap relaxation, or implementation before owner approval.

## Milestone M12C — Sandbox demonstration and local reproducibility

**Objective:** Verify clean-clone local infrastructure/configuration reproducibility separately from the authorized real sandbox transaction and its exact-source replay; retain evidence for later M12D/M12E review without repeating provider operations.

**Prerequisites:** M12A accepted and M12B implementation completed and independently accepted under its separate implementation authorization. The Option A behavior contract and delivery-order clarification are approved. Live operations require explicit owner authorization. For the M12C-3 run, the owner selected FakeProvider and prohibited Gemini; this is scripted extraction evidence, not live model evidence. Any later model request requires separate authorization and is outside the accepted M12C-3 run.

**Reuse:** Existing clean-clone setup and provider-specific procedures in `docs/development/phase9-n8n-sync-e2e.md`, `docs/development/odoo-m9c-sandbox.md`, `docs/development/hubspot-m9d-sandbox.md`, and `workflows/n8n/README.md`.

**Required deliverables:**

- Modify `docs/development/phase9-n8n-sync-e2e.md` with the concise M12C runbook and accurately recorded scope. Include preparation, target verification, exact operator actions, evidence, replay, cleanup, stop conditions, and local clean-clone checks.
- Modify `workflows/n8n/README.md` and `README.md` to link the tested procedure and report actual outcomes.
- Retain the sanitized run record for independent review. The authorized transaction was not recorded on video and no valid screenshot was retained at run time; under the owner-approved amendment below, authenticated read-only post-run captures may document genuine persisted state.

**Evidence/media amendment:** On 2026-10-18, the owner approved acceptance of this transaction as a **segmented integration demonstration** and approved authenticated, read-only post-run captures of genuine persisted sandbox state. The run remains factually **PARTIAL**: the original Gmail Trigger detected the source, but its intake POST returned HTTP 401; the same original source was then submitted through owner-assisted recovery. Automated end-to-end Gmail-to-OpsFlow intake is **NOT DEMONSTRATED**. Preserve the failure and recovery record; do not call this an uninterrupted automated pass. The same owner decision permits an evidence-backed narrated/captioned 90–120-second walkthrough using genuine persisted state, with each post-run view labeled **POST-RUN INSPECTION**. No live operation may be repeated to obtain footage.

Historical Phase 8 evidence may be cited separately and only for its recorded scope: `workflows/n8n/README.md` documents M8C Gmail sandbox cases A–I and M8E live primary/clean-clone Gmail intake through review/approval with Slack and original-thread approval reply; `docs/audits/phase-8-audit.md` records that M8F reused those records and made no live provider sends. Phase 8 predates Odoo/HubSpot synchronization and M12B post-sync completion notifications. It cannot be combined with M12C-3 to claim uninterrupted Phase 12 Gmail automation.

**Optional enhancements:** No second live run, provider call, or mutation for capture. The already completed transaction may be represented with read-only post-run captures and an evidence-backed narrated/captioned walkthrough after the owner collects and reviews usable sanitized images.

**Acceptance — local setup reproducibility:**

- In a literal second clean clone at the candidate SHA, verify a clean tracked tree, documented commands, fresh local Compose project, new PostgreSQL/n8n volumes, and configuration from `.env.example`/documented ignored settings.
- This check may verify local readiness and provider-free workflow configuration. Keep external integrations inactive and do not make live provider calls, sends, writes, account changes, or charges. A second clone proves local reproducibility only.

**Acceptance — owner-approved segmented sandbox transaction and exact replay:**

- In one literal clean candidate clone at the frozen SHA, verify the clean tracked tree and fresh local state. Before any provider operation, positively verify the dedicated Gmail mailbox, Slack workspace/channel, disposable Odoo database, and HubSpot developer-test portal. Confirm unique synthetic identities and no conflicting records. Do not reset shared or whole accounts.
- Configure distinct local orchestration, reviewer, and approver credentials; bind only approved external credentials. Disable n8n execution-data saving. Keep all secrets and raw provider data outside Git.
- Record the original source transaction accurately: the Gmail Trigger detected the one synthetic message, but its intake POST returned HTTP 401. The owner then recovered the same source from the downloaded original `.eml`, used the tracked normalization/intake path and original Gmail API message identity, and made one authenticated intake submission. The retained evidence supports HTTP 201 and one order/source. The body bytes of the failed 401 request were not retained; do not claim byte-for-byte equality with that failed request. Automated Gmail Trigger-to-OpsFlow intake is NOT DEMONSTRATED. This owner-approved recovery permits a segmented demonstration for this portfolio release only.
- Show application document processing and extraction with provider mode truthfully identified. The M12C-3 run used scripted FakeProvider output and no live Gemini extraction; do not call this model inference, model quality, or accuracy evidence. Deterministic validation remains authoritative; distinct human review and approval are persisted.
- Verify actual Odoo and HubSpot sandbox synchronization with durable receipts; only then is order completion confirmed. The run reused the existing synthetic HubSpot Company, created/reconciled one Deal and association, and produced one Odoo sale order. Verify four actual Slack and two actual Gmail notification outcomes, including post-sync completion intents causally tied to the completion audit event and receipts. All six intents were reported delivered in the retained run evidence. Record actual provider outcomes and timestamps; their relative delivery order is not a correctness invariant. Never stage provider success or claim physical exactly-once delivery.
- Replay the exact same retained canonical synthetic bytes through the authenticated intake with the original Gmail API message ID and idempotency key; do not re-fetch Gmail. Confirm no second logical order, Odoo/HubSpot object, or new logical completion intent, and no additional provider read, send, or write. Record actual delivery counts honestly, retaining the at-least-once limitation. The retained evidence reports an idempotent HTTP 200 replay with unchanged logical counts.
- Deactivate relevant workflows. Delete/archive uniquely identified synthetic ERP/CRM records, Gmail messages, or Slack posts, and revoke temporary keys, only under separate explicit authorization for those exact cleanup actions; otherwise preserve the state and report it. Remove only named disposable local volumes after verifying ownership. On timeout, ambiguous acknowledgement, or unexpected state, stop and reconcile before any fresh authorization.

**Evidence record:** Candidate SHA, tool/runtime versions, local state identity, provider sandbox identities by type (never private IDs in public artifacts), each approved operation and outcome count, durable states/receipts, provider acknowledgement timestamps, replay counts, cleanup disposition, and deviations. Preserve the original HTTP 401 record, owner-assisted recovery record, downstream outcomes, and replay record privately under suitable access controls. Clearly distinguish the failed automatic intake, successful assisted intake, FakeProvider mode, and actual downstream provider evidence. Raw MIME/source and unedited inspection captures remain private. Sanitized public captures contain no credentials, private identifiers, account details, or non-synthetic information and are labeled POST-RUN INSPECTION where applicable.

**Verification:** The runbook provides exact local commands and observable manual checks. Test local reproducibility independently from the one live transaction. Historical Phase 8/9 integration tests and provider-free demonstrations do not substitute for this run. The second clone must not be used to repeat external operations.

**External services and authorization:** The M12C-3 Gmail source, approval notifications, Odoo/HubSpot synchronization, completion notifications, and replay were separately authorized and executed on 2026-10-18; no further live operation is authorized by this amendment. Any future provider read, send, write, cleanup/deletion, key revocation, or potentially charged operation requires separate explicit authorization naming provider, target, operation/retry ceiling, and spend cap where applicable. Existing provider retry limits may repeat an attempt and must be included in the authorization. If a future target, credential, isolation control, or spend rule is unavailable, stop safely and report incomplete evidence.

**Review gate:** The owner-approved amended evidence record and sanitized post-run captures received independent PASS review and human acceptance on 2026-10-20. M12C is COMPLETE under that limited scope; the M12C-3 run itself remains factually PARTIAL because uninterrupted automated Gmail-to-OpsFlow intake was NOT DEMONSTRATED after the initial HTTP 401 and owner-assisted recovery. Review confirmed the amended claims for completed order, deterministic validation, distinct reviewer and approver, actual Odoo/HubSpot evidence, four Slack and two Gmail deliveries, causally linked post-sync notifications, and exact-source replay. All screenshots are POST-RUN INSPECTION captures. The concise disposition records accepted limitations and two Low findings covering the private artifact and public-media handling. M12D, M12E, and M12F remain NOT STARTED and require their own authorization and review gates.

**Non-goals:** No production/customer account, shared Odoo database, production HubSpot portal, bulk live evaluation, second live run for capture, forced provider outage, lost-acknowledgement exercise, global reset, or mutation outside named synthetic records.

## Milestone M12D — Case study and evidence-backed claims

**Objective:** Publish a concise technical case study grounded in Phase 11 reference evidence and the new live sandbox run.

**Prerequisites:** M12A complete; provider-free reference unchanged; M12C evidence and its owner-approved limited-scope disposition available. Any case-study account of the M12C-3 run must disclose the initial HTTP 401, owner-assisted recovery, FakeProvider mode, and the fact that automated Gmail Trigger-to-OpsFlow intake was not demonstrated. Live Gemini metrics remain unavailable/optional.

**Reuse:** docs/evaluation/reference/phase-11-provider-free-baseline.md, phase-11-baseline-decision.md, phase-11-live-gemini-unavailable.md, the unchanged reference JSON, Phase 8–11 audits, and the sanitized Phase 12 demo record.

**Files:**

- Create: docs/case-study.md
- Modify: README.md to summarize and link to the case study
- Modify: docs/development/development-guide.md only for durable command/limitation updates

**Required deliverable:** One concise, evidence-linked case study that distinguishes existing provider-free evidence, historical integration evidence, and the new M12C run. If live M12C evidence is unavailable, report that gap plainly while continuing documentation work that does not depend on it.

**Optional enhancement:** A separately approved limited live measurement may be planned later, but it is not needed to publish the unavailable-evidence statement and cannot silently block this milestone.

**Acceptance:**

- Map every claim to a specific source, run SHA, mode, population, count, and environment near the claim.
- Report 36/36 PASS as provider-free correctness/safety evidence, never Gemini accuracy.
- Report deterministic violation routing 7/7, duplicate blocking 4/4, malformed/security 4/4, invalid execution 0/13, and direct LLM side effects 0/36 with the synthetic corpus qualifier.
- If showing local timing, preserve sample counts and call it diagnostic; state Phase 11 NO_OPTIMIZATION and no production SLA.
- State Gemini quality, authoritative tokens, live provider latency, and model cost as unmeasured unless a separately approved valid run produces evidence.
- State manual-step reduction, ROI, savings, customer adoption, and production deployment as not measured/not claimed.
- Manual-step reduction may only be described as a count of observed operator actions in the recorded demo, with the observation method stated; no before/after or time-saving inference.
- Distinguish the live Phase 12 sandbox run from prior tests and the provider-free evaluation.
- Leave the Phase 11 corpus, reference JSON/Markdown, audits, and NO_OPTIMIZATION outcome untouched.

**Verification:** Run the exact provider-free make evaluate only in the guarded dedicated evaluation database when refreshing evidence; otherwise link the immutable existing reference. Validate JSON/Markdown reference consistency if a new reference is explicitly approved. Do not overwrite reference artifacts as part of ordinary documentation edits. Run the documentation link check and git diff --check.

**Optional live measurement:** The existing `make evaluate-live` command executes the complete 36-case evaluation and is not a strictly limited subset. Do not run it for Phase 12. The recommended demo's one Gemini extraction is qualitative evidence only and is not an evaluation. Keep real Gemini quality, aggregate provider latency, authoritative tokens, and model cost unavailable unless a valid separately approved measurement produces evidence. This optional path does not block M12D when its unavailability is explicit.

**External services and authorization:** Provider-free evidence requires no live model. No full live evaluation is authorized. Any future bounded live measurement, new evaluation mode, or changed pricing input requires a separate design approval and explicit call/spend authorization.

**Review gate:** A technically literate human checks the case-study evidence map and all public claims before media production.

**Non-goals:** No ROI assumptions, synthetic results presented as customer data, new evaluation framework, baseline rewrite, or optimization.

## Milestone M12E — Media, licensing, privacy, and public hygiene

**Objective:** Produce a polished, concise public portfolio video and sanitized screenshots from genuine M12C run evidence, then perform the required licensing, security, and privacy checks on the public repository candidate.

**Prerequisites:** M12C has been human-accepted under the dated limited-scope amendment; the owner has reviewed usable sanitized captures of authentic persisted state and chosen license terms and media delivery/storage. The 2026-10-18 transaction was not recorded contemporaneously. The approved evidence-backed narrated/captioned walkthrough may use authenticated read-only post-run captures labeled **POST-RUN INSPECTION**; it must not imply uninterrupted footage. Any public file uses only synthetic and sanitized content. This milestone does not repeat the demo.

**Files:**

- Create: docs/media/portfolio-demo-overview.png
- Create: docs/media/portfolio-demo-review.png
- Create: docs/media/portfolio-demo-integrations.png
- Create: docs/media/portfolio-demo.mp4, if repository storage is selected by the owner
- Create: docs/media/portfolio-demo.vtt with captions
- Create: docs/media/ASSET-LICENSES.md for authorship/provenance and third-party notices
- Create: docs/security/privacy.md
- Modify: README.md to link to media and privacy/security information
- Modify: docs/development/dependency-security.md with current advisory disposition
- Create: LICENSE only after the owner selects the terms; create NOTICE only if the selected license and reviewed assets require it

**Required deliverables:** Professionally edited approximately 90–120 second H.264 1080p evidence-backed overview video with captions and readable visuals of the actual user workflow and provider evidence, plus sanitized screenshots. It may use authentic authenticated read-only post-run captures of persisted sandbox state and a truthful narration/caption sequence; label post-run views **POST-RUN INSPECTION**. Explicitly disclose synthetic data, sandbox use, the initial Gmail Trigger HTTP 401, owner-assisted source recovery, FakeProvider extraction, and that automated end-to-end Gmail-to-OpsFlow intake was not demonstrated. Do not claim uninterrupted contemporaneous footage. No unsupported metrics, real-world performance claims, or live-provider claims beyond verified evidence.

**Optional enhancement:** None required beyond the evidence pack. An external video host may be proposed if repo storage harms practical delivery or legibility, but it requires owner approval after reviewing privacy, terms, availability, and cost. Do not publish/upload through an external host in this plan.

**Acceptance:**

- Keep raw captures and provider responses outside Git; retain an inspectable unedited run record privately under appropriate access controls. Review each selected image and video frame at full size for credentials, private identifiers, account details, browser secrets, execution data, and non-synthetic content. Preserve raw post-run screenshots privately; create clearly labeled sanitized derivatives only for review/public use.
- Do not impose an arbitrary file-size cap that materially harms legibility. Optimize with an appropriate codec/resolution and review actual playback. If repository size or hosting constraints make repo storage impractical, pause for owner selection of a suitable external delivery option.
- Show genuine persisted application and provider state legibly; clearly identify synthetic data and sandbox accounts. Authenticated read-only post-run inspection is allowed by the approved amendment, but do not stage, recreate earlier states, or replace actual provider results with simulations. The final walkthrough may use narration/captions and explanatory graphics only when each claim is traceable to the run record; distinguish graphics from captured UI and label post-run views.
- Keep attribution and license provenance for every added visual/recorded asset. Vendor names/logos are used only as needed to identify integrations and carry no endorsement claim.
- Owner-selected code and documentation/media licenses are stated accurately. Dependency, Odoo addon, and asset notices are reviewed; public visibility is not described as permission to reuse.
- Run pinned full-history Gitleaks with redaction, current-content scan of docs and media metadata, check-ignore and tracked-file checks for .env and local Odoo configuration, and complete/production-only dependency audits.
- Confirm `git ls-files -- .env integrations/odoo/.env.m9c-sandbox` and `git log --all --format=%H -- .env integrations/odoo/.env.m9c-sandbox` return no tracked paths or commits for either credential file.
- Reconcile the current development-tree npm advisories; remediate or document a narrow approved disposition and verify the production exposure analysis. No security finding is described as fixed without evidence.
- Remove or ignore generated/private outputs while retaining synthetic fixtures and selected deliverables.

**Verification commands:** Run the exact pinned Gitleaks v8.28.0 full-history scan documented in docs/development/dependency-security.md / prior Phase 9 audit; run its redacted current-directory scan over docs and docs/media; run make security-audit and npm --prefix web audit --json for full-tree disposition; run git check-ignore -v .env integrations/odoo/.env.m9c-sandbox and confirm those files are not tracked; run git diff --check and the docs link checker.

**External services and authorization:** This milestone makes no provider-side send, write, or account change. Authenticated read-only inspection needed to capture the existing synthetic records is permitted under the owner-approved amendment; no workflow execution, replay, or renewed business operation is permitted. External hosting or upload requires separate explicit approval.

**Review gate:** Human approves license and residual advisory/asset dispositions. An independent reviewer checks privacy, scan coverage, and media before the final audit.

**Non-goals:** No license selection by the implementer, no unlicensed third-party media/music, no repository visibility change, no unapproved upload/hosting, no raw source video in Git, and no credentials or private account information in assets.

## Milestone M12F — Independent Phase 12 release audit and closeout

**Objective:** Independently decide whether the portfolio release meets the approved roadmap and close Phase 12 only after all required evidence passes.

**Prerequisites:** M12A–M12E complete; exact frozen candidate SHA; clean tree; all decisions and external-operation authorizations/dispositions recorded.

**Files:**

- Create: docs/audits/phase-12-audit.md
- Modify only at final PASS: README.md, docs/roadmap/project-roadmap.md, and docs/development/development-guide.md with Phase 12/M12 statuses and the audit link

**Required deliverable:** An independently authored `docs/audits/phase-12-audit.md` recording roadmap gates, evidence, reviewer identity/independence, exact checks, findings and dispositions, limitations, costs, frozen candidate/audit SHAs, and human approval status. Closeout status edits occur only after audit PASS and owner approval.

**Optional enhancements:** None. The final audit cannot replace missing mandatory demo evidence with historical tests, simulated providers, or presentation materials.

**Audit coverage:**

- Scope and roadmap traceability; status truth; no future product scope or unsupported claim.
- M12B owner-approved Option A contract and separate implementation authorization/review; verify that both notification intents follow successful sync with durable Odoo/HubSpot receipts, Gmail provenance is enforced, Slack reports successful sync independently of Gmail, and each channel retains idempotent logical intents, bounded retries, durable outcomes, and at-least-once semantics.
- Clean-clone local infrastructure/configuration reproducibility separately from the actual M12C-3 sandbox transaction and exact-source replay; verified sandbox identities, downstream provider records, durable completion evidence, both actual post-sync notification outcomes and their causal tie to sync completion, actual provider timestamps without relative-order gating, replay counts, cleanup, and deviations. Assess this run against the human-approved limited-scope amendment: preserve the Gmail Trigger HTTP 401 and owner-assisted recovery, and confirm that automated Gmail Trigger-to-OpsFlow intake is explicitly NOT DEMONSTRATED. Do not issue an uninterrupted end-to-end PASS.
- Verify that no second clone, replay, or media edit is represented as authorization for additional Gemini calls, emails, Slack messages, or Odoo/HubSpot mutations.
- Case-study metric-to-source mapping; provider-free/live distinction; limitations; pricing/token provenance; manual-step claim disposition.
- License owner approval; dependency and media licenses; privacy, source assets, public Git history, ignored files, and current dependency advisories.
- README/setup/architecture/evaluation coherence; links; required 90–120 second evidence-backed video and sanitized screenshots; visible POST-RUN INSPECTION labels where applicable; selected storage/delivery; workflows; migrations; CI and applicable test results.
- Open Critical/High/Medium/Low findings, accepted exceptions, and remediation proof.

**Verification:** Independent reviewer validates the frozen source SHA, runs required docs/security checks, inspects actual demo evidence, both provider outcomes and their durable causal relationship to completed sync, timestamps, replay proof, video/screenshots, and privately retained audit record as authorized, and records exact commands/results. The M12C-3 record is evaluated under the owner-approved segmented-scope amendment and remains factually PARTIAL for automated Gmail intake; disclosure is mandatory. Either missing or failed required post-sync notification would fail the accepted downstream transaction evidence; relative delivery timing does not. Historical Phase 8 evidence may be separately attributed only to its documented Gmail intake, review/approval, Slack, and approval-reply scope. It cannot substitute for or be merged into the M12C-3 run. Simulated providers cannot replace claimed live downstream results. Remediation is a separate approved implementation task followed by independent re-review. No status closeout is committed before human approval of the final audit PASS.

**Independence:** Follow the repository's single-agent workflow; the final audit reviewer must not be the implementation author. Arrange a human/senior reviewer for this gate rather than silently self-certifying or dispatching an agent contrary to repository instructions.

**External services and authorization:** The audit itself should inspect retained evidence and avoid repeating live mutations. Any needed rerun requires the same separate approvals as M12C.

**Review gate:** Human accepts the final audit and the exact closeout commit. Then update current status to Phase 12 COMPLETE. Historical Phase 8–11 audits remain unchanged.

**Non-goals:** No implementation remediation inside the independent audit, no live re-test without approval, no merge, release upload, visibility change, or cloud deployment.

## Verification hierarchy

1. Review the selected milestone diff, scope, generated artifacts, and branch status.
2. For behavior changes, use focused TDD, then guarded migration/integration checks.
3. Run make check and make security-audit using fresh disposable database identities where required.
4. Verify fresh local clean-clone setup and provider-free evaluation separately from the single separately authorized real sandbox demonstration and exact-source replay.
5. Validate relative Markdown links, workflow JSON/Compose configuration, media privacy/licensing/playback, git diff --check, ignore/tracked-file rules, public Git history, and pinned full-history Gitleaks.
6. Complete the independent release audit and human approval.

The final audit must not call tests that can mutate live accounts, send email, contact Gemini, or incur charges. Such operations require separate explicit authorization before their execution.
