# Phase 12 Portfolio Release Implementation Plan

> For agentic workers: use the repository's single-agent, sequential workflow. Execute one approved milestone at a time and stop at its review gate. This draft authorizes no implementation.

**Goal:** Make OpsFlow AI a locally reproducible, evidence-backed portfolio project with a truthful full sandbox demonstration and release-ready documentation.

**Architecture:** Reuse the existing React review app, Python/FastAPI business services, PostgreSQL state and receipts, and n8n provider workflows. M12B is conditional on explicit owner approval of the completion-notification contract. The roadmap's full-demo sequence remains unchanged; use actual dedicated sandbox providers for every step described as live.

**Tech stack:** Existing Python 3.12, uv, FastAPI, PostgreSQL 16, Docker Compose, React/TypeScript/Vite, Node.js 24/npm, n8n 2.40.5, current provider adapters, Make targets, CI, and pinned Gitleaks. No new framework or mandatory paid service.

**Spec:** [Phase 12 Portfolio Release Design Proposal](../specs/2026-10-12-phase-12-portfolio-release-design.md)

## Plan status and execution gates

This plan is DRAFT and awaits human review and approval. The approved starting main SHA is 17c155df3b2635f60f88c6596c1d74b02015fb2d. The planning branch is phase/12-portfolio-release. Phase 12 is IN PROGRESS for planning only; implementation is NOT STARTED.

The work unit is one milestone. The next milestone cannot begin until its prerequisites, acceptance evidence, review, and human approval are recorded. All execution remains on the designated Phase 12 branch with a clean, reviewed diff. Do not use subagents or parallel agents unless the owner separately changes the repository's single-agent instruction.

## Global Constraints

- The Phase 12 roadmap and approved design are authoritative; this plan does not silently relax the required full demo.
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
3. **Notification coupling or false ordering:** Phase 8 channels are independent and at-least-once. Option A reports completed sync independently of email delivery but cannot enforce Gmail-before-Slack. The roadmap sequence remains required unless amended by the owner.
4. **Repeated or ambiguous live operations:** fresh local clone state is reproducibility evidence only. One approved transaction/replay does not authorize new calls, sends, or writes on a second clone or after an uncertain result.
5. **Unsupported metrics, media, or license claims:** every public claim maps to evidence; required video/screens are sanitized and licensed; license terms remain an owner decision.

---

## Milestone M12A — Portfolio framing and onboarding

**Objective:** Make the first README screen, architecture explanation, current status, and clean-checkout setup usable by a client or recruiter without replacing detailed technical guides.

**Prerequisites:** Human approval of the Phase 12 design and this milestone. Keep Phase 12 status IN PROGRESS / planning-only until an implementation milestone is approved. Implementation remains NOT STARTED until authorization.

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

**Review gate:** Human review checks all current-status claims, audience clarity, command accuracy, and links. M12B cannot begin until its independent completion-notification contract decision is recorded.

**Non-goals:** No feature work, demo capture, license selection, dependency changes, new setup framework, or cloud hosting.

## Milestone M12B — Completion-notification decision and conditional path

**Objective:** Resolve the missing post-sync completion events without confusing the roadmap's desired demo chronology with a business rule. Implement only a behavior contract that the owner explicitly selects and approves.

**Prerequisites:** M12A accepted. A separate owner decision on Option A, B, or C in the design proposal is mandatory. Phase 12 roadmap approval does not approve this production behavior change.

**Reuse:** Existing Phase 8 notification intent/outcome contract, stable event/channel/kind uniqueness, five-minute claims, bounded retries and final failure, Gmail sender-only approval reply, independent Slack payload, n8n transport, Phase 9 `complete_order_sync()` receipt checks and transaction, and existing database-safety guards.

**Options requiring a decision:**

- **Option A (recommended):** In the existing successful completion transaction, reuse the `ORDER_SYNC_COMPLETED` audit event identity and insert independently retriable Gmail and Slack completion intents. Gmail is eligible only with persisted Gmail provenance. Slack reports successful Odoo/HubSpot synchronization regardless of email delivery. Reuse stable event/channel/kind uniqueness for replay idempotency. This preserves independent channel outcomes and at-least-once limits. It does not enforce Gmail-before-Slack; the demo must record actual acknowledgement timestamps and fails the roadmap sequence criterion if they are out of order.
- **Option B:** For Gmail-provenance orders, make Slack claim eligibility depend on matching Gmail `DELIVERED`. This provides durable acknowledgement ordering only, not physical exactly-once. Permanent Gmail failure withholds Slack after bounded attempts; timeout or lost acknowledgement can lead to duplicate email before release. The current API has no operator requeue/reconciliation action, so recovery semantics and supported operator controls must be designed explicitly before implementation. For non-Gmail sources, explicitly decide whether Slack is released at sync completion (recommended) because no Gmail row can satisfy the gate, or is withheld indefinitely. The tradeoff is coupling an operations signal for completed sync to customer-email delivery.
- **Option C:** No application behavior change. Any narrower demonstration requires an explicit separate roadmap acceptance amendment; until that amendment is approved, the current full demo is incomplete. Do not relabel approval notifications or historical evidence as post-sync events.

**Required deliverables for every option:** Record the selected option, owner approval, exact email/Slack meaning, Gmail provenance rule, retry/idempotency semantics, failure/recovery behavior, and impact on M12C acceptance in the M12B closeout. If C is selected, no application files change; route the proposed roadmap amendment for approval in the appropriate future planning task.

**Decision record:** Update this plan with the owner-approved selection and its approval reference before any conditional implementation begins. Do not treat the current recommendation as approval.

**Conditional implementation files for A or B only:**

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

**Acceptance and verification if A or B is explicitly approved:**

- Add failing tests first for non-completed state, missing Odoo/HubSpot receipts, non-Gmail provenance, same-transaction creation, replay uniqueness, independent provider outcomes, bounded retries/final failure, and lost outcome acknowledgement. For B, also test that Slack is withheld on Gmail permanent/ambiguous failure and released only after durable Gmail `DELIVERED`, plus the approved recovery path.
- Confirm expected failures, then implement only the approved narrow contract and a forward-only migration for the new notification kind.
- Run focused notification and sync tests: `uv run pytest tests/unit/notifications tests/unit/workflows/test_phase8_notification_dispatch_contract.py -q --no-cov`.
- Run isolated Phase 8/9 integration suites, including migration and transaction/claim tests, against fresh guarded disposable databases; all focused tests pass and no live-provider suite runs.
- Run `uv run alembic upgrade head` and `uv run alembic current` against a fresh disposable database; expected head is `0008_phase12_completion_notifications`.
- Run `docker compose config --quiet` and `make check` with newly identified disposable databases; expected configured quality gates pass.
- Verify n8n transports backend-owned notification payloads and does not decide business eligibility. Under A, do not assert channel order in backend tests. Under B, test the backend eligibility prerequisite and recovery behavior.

**External services and authorization:** Local fakes and disposable PostgreSQL only for implementation verification. No real email, Slack, Odoo, HubSpot, Gemini, or potentially charged operation. Any later live demo calls/writes/sends need separate explicit authorization listing the provider, target, operation count/retry bound, and spend ceiling where applicable.

**Review gate:** Before coding, the owner approves A/B/C and, for A/B, the exact behavior contract; this is an explicit M12B gate. After implementation, independent code review approves transaction safety, migration, Gmail provenance, replay identity, notification meanings, retry/failure semantics, and the at-least-once limitation. M12C requires both gates. Option A is not deemed to satisfy the observed demo order unless M12C evidence shows Gmail delivery before Slack delivery.

**Optional enhancement:** None proposed. Do not add channel scheduling or operator APIs unless a separately reviewed design proves necessary for an approved contract.

**Non-goals:** No new provider, generalized notification framework, changed approval authority, direct API provider call, exactly-once claim, workflow engine, silent roadmap relaxation, or implementation before owner approval.

## Milestone M12C — Live sandbox demonstration and local reproducibility

**Objective:** Verify clean-clone local infrastructure/configuration reproducibility separately from one newly authorized real sandbox transaction and its exact-source replay; gather the evidence once for M12D and M12E.

**Prerequisites:** M12A accepted. The owner must approve the M12B completion-notification contract before any behavior implementation or live run. Separately approve the demo environment and each live operation. The proposed Gemini call requires its own explicit one-request and spend-ceiling authorization. Verify the candidate SHA and all disposable targets before use.

**Reuse:** Existing clean-clone setup and provider-specific procedures in `docs/development/phase9-n8n-sync-e2e.md`, `docs/development/odoo-m9c-sandbox.md`, `docs/development/hubspot-m9d-sandbox.md`, and `workflows/n8n/README.md`.

**Required deliverables:**

- Modify `docs/development/phase9-n8n-sync-e2e.md` with the concise whole-flow runbook after the approved M12B contract is implemented. Include preparation, target verification, exact operator actions, evidence, replay, cleanup, stop conditions, and local clean-clone checks.
- Modify `workflows/n8n/README.md` and `README.md` to link the tested procedure and report actual outcomes.
- Retain a sanitized run record for the independent audit; capture readable evidence from the actual run only.

**Optional enhancements:** None for repeat external runs. The single authorized run's video footage is gathered during M12C only if capture was explicitly approved; M12E edits that footage into the public deliverable. No repeat run solely for screenshots or video.

**Acceptance — local setup reproducibility:**

- In a literal second clean clone at the candidate SHA, verify a clean tracked tree, documented commands, fresh local Compose project, new PostgreSQL/n8n volumes, and configuration from `.env.example`/documented ignored settings.
- This check may verify local readiness and provider-free workflow configuration. Keep external integrations inactive and do not make live provider calls, sends, writes, account changes, or charges. A second clone proves local reproducibility only.

**Acceptance — one actual sandbox transaction and exact replay:**

- In one literal clean candidate clone at the frozen SHA, verify the clean tracked tree and fresh local state. Before any provider operation, positively verify the dedicated Gmail mailbox, Slack workspace/channel, disposable Odoo database, and HubSpot developer-test portal. Confirm unique synthetic identities and no conflicting records. Do not reset shared or whole accounts.
- Configure distinct local orchestration, reviewer, and approver credentials; bind only approved external credentials. Disable n8n execution-data saving. Keep all secrets and raw provider data outside Git.
- Process one synthetic email through the existing Gmail intake path: `POST /v1/orchestration/intakes` via `workflows/n8n/opsflow-gmail-intake.json`, preserving Gmail source/message identity and original bytes. Python document processing must run before extraction; deterministic validation remains authoritative; separate human review and approval are visible.
- The roadmap requires an extraction stage but does not name a live Gemini request or count. Recommended stronger evidence is exactly one actual `GeminiProvider` generation request through this application path. Its authorization must state provider/model, at most one provider invocation, and a concrete maximum spend in currency; with no approved spend ceiling, make zero calls. Before invocation, verify that the existing n8n HTTP retry branches, idempotent redelivery, lease recovery, and human Retry action cannot cause a second provider invocation. If that bound cannot be established, stop and request a separately approved minimal control before any live call. If provider/credentials are unavailable at preflight, stop with zero calls. If timed out or ambiguous, deactivate/stop the intake and treat the budget as consumed. No fallback, manual retry, replay-triggered call, or additional call without fresh explicit authorization. If not authorized, label provider-free extraction as rehearsal evidence and leave live-Gemini evidence unavailable; never label it Gemini.
- Verify actual Odoo and HubSpot sandbox records and durable receipts; completion requires all expected receipts. Then capture actual post-sync Gmail and Slack provider outcomes. The roadmap's observed sequence requires Gmail completion delivery before Slack completion delivery; with Option A this is an observed-run gate, not a backend guarantee. If timestamps fail or cannot be verified, mark that roadmap criterion incomplete. A manual timing workaround cannot be called automated sequencing.
- Replay the exact same retained synthetic bytes through the authenticated intake with the original Gmail message ID and idempotency key; do not re-fetch Gmail. Confirm no second logical order, Odoo/HubSpot object, Gemini call, or new logical completion intent, and no additional provider read, send, or write. Record actual delivery counts honestly, retaining the at-least-once limitation.
- Deactivate relevant workflows. Delete/archive uniquely identified synthetic ERP/CRM records, Gmail messages, or Slack posts, and revoke temporary keys, only under separate explicit authorization for those exact cleanup actions; otherwise preserve the state and report it. Remove only named disposable local volumes after verifying ownership. On timeout, ambiguous acknowledgement, or unexpected state, stop and reconcile before any fresh authorization.

**Evidence record:** Candidate SHA, tool/runtime versions, local state identity, provider sandbox identities by type (never private IDs in public artifacts), each approved operation and outcome count, durable states/receipts, provider acknowledgement timestamps, replay counts, cleanup disposition, and deviations. Preserve an inspectable unedited run record privately under suitable access controls. Sanitized public captures contain no credentials, private identifiers, account details, or non-synthetic information.

**Verification:** The runbook provides exact local commands and observable manual checks. Test local reproducibility independently from the one live transaction. Historical Phase 8/9 integration tests and provider-free demonstrations do not substitute for this run. The second clone must not be used to repeat external operations.

**External services and authorization:** Live Gmail source retrieval, one proposed Gemini extraction, pre-sync approval and post-sync completion sends, Odoo/HubSpot lookups and mutations, cleanup/deletion, key revocation, and any potentially charged operation each need separate explicit authorization naming provider, target, operation/retry ceiling, and spend cap where applicable. Existing provider retry limits may repeat an attempt and must be included in the authorization. No operation is authorized by this draft. If the provider, credentials, target isolation, or spend rule is unavailable, stop safely and report incomplete evidence.

**Review gate:** Human reviews target verification and operation authorization before the live run, then reviews sanitized evidence, replay, cleanup, and actual notification timestamps before M12D. M12E uses this same recorded run; no new live operation is needed to produce media.

**Non-goals:** No production/customer account, shared Odoo database, production HubSpot portal, bulk live evaluation, second live run for capture, forced provider outage, lost-acknowledgement exercise, global reset, or mutation outside named synthetic records.

## Milestone M12D — Case study and evidence-backed claims

**Objective:** Publish a concise technical case study grounded in Phase 11 reference evidence and the new live sandbox run.

**Prerequisites:** M12A complete; provider-free reference unchanged; M12C evidence if the full-demo claim is to be included. Live Gemini metrics remain optional.

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

**Objective:** Produce a polished, concise public portfolio video and sanitized screenshots from the M12C run, then perform the required licensing, security, and privacy checks on the public repository candidate.

**Prerequisites:** M12C complete; M12C footage was explicitly authorized and captured during the same live run; the owner has chosen license terms and media delivery/storage. Any public file uses only synthetic and sanitized content. This milestone does not repeat the demo.

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

**Required deliverables:** Professionally edited approximately 90–120 second H.264 1080p overview video with captions and readable capture of the actual user workflow and provider evidence, plus sanitized screenshots. Include explicit synthetic-data and sandbox disclosures. Use only footage from the already authorized M12C run. No unsupported metrics, real-world performance claims, or live-provider claims beyond verified evidence.

**Optional enhancement:** None required beyond the evidence pack. An external video host may be proposed if repo storage harms practical delivery or legibility, but it requires owner approval after reviewing privacy, terms, availability, and cost. Do not publish/upload through an external host in this plan.

**Acceptance:**

- Keep raw source footage and provider responses outside Git; retain an inspectable unedited run record privately under appropriate access controls. Review each selected image and video frame at full size for credentials, private identifiers, account details, browser secrets, execution data, and non-synthetic content.
- Do not impose an arbitrary file-size cap that materially harms legibility. Optimize with an appropriate codec/resolution and review actual playback. If repository size or hosting constraints make repo storage impractical, pause for owner selection of a suitable external delivery option.
- Capture the actual application workflow and provider evidence legibly; clearly identify synthetic data and sandbox accounts. Do not stage, recreate, or replace live provider results with simulations.
- Keep attribution and license provenance for every added visual/recorded asset. Vendor names/logos are used only as needed to identify integrations and carry no endorsement claim.
- Owner-selected code and documentation/media licenses are stated accurately. Dependency, Odoo addon, and asset notices are reviewed; public visibility is not described as permission to reuse.
- Run pinned full-history Gitleaks with redaction, current-content scan of docs and media metadata, check-ignore and tracked-file checks for .env and local Odoo configuration, and complete/production-only dependency audits.
- Confirm `git ls-files -- .env integrations/odoo/.env.m9c-sandbox` and `git log --all --format=%H -- .env integrations/odoo/.env.m9c-sandbox` return no tracked paths or commits for either credential file.
- Reconcile the current development-tree npm advisories; remediate or document a narrow approved disposition and verify the production exposure analysis. No security finding is described as fixed without evidence.
- Remove or ignore generated/private outputs while retaining synthetic fixtures and selected deliverables.

**Verification commands:** Run the exact pinned Gitleaks v8.28.0 full-history scan documented in docs/development/dependency-security.md / prior Phase 9 audit; run its redacted current-directory scan over docs and docs/media; run make security-audit and npm --prefix web audit --json for full-tree disposition; run git check-ignore -v .env integrations/odoo/.env.m9c-sandbox and confirm those files are not tracked; run git diff --check and the docs link checker.

**External services and authorization:** This milestone makes no provider call, send, write, or account change. Footage must have been captured during the separately authorized M12C run; this is not authorization to capture it. External hosting or upload requires separate explicit approval.

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
- M12B owner-selected completion contract and approval record; any implementation review. Option A's independent channel semantics and its lack of ordered-delivery guarantee remain explicit.
- Clean-clone local infrastructure/configuration reproducibility separately from the one actual sandbox transaction and exact-source replay; verified sandbox identities, downstream provider records, actual Gmail/Slack acknowledgement order, replay counts, cleanup, and deviations.
- Verify that no second clone, replay, or media edit is represented as authorization for additional Gemini calls, emails, Slack messages, or Odoo/HubSpot mutations.
- Case-study metric-to-source mapping; provider-free/live distinction; limitations; pricing/token provenance; manual-step claim disposition.
- License owner approval; dependency and media licenses; privacy, source assets, public Git history, ignored files, and current dependency advisories.
- README/setup/architecture/evaluation coherence; links; required 90–120 second video and sanitized screenshots; selected storage/delivery; workflows; migrations; CI and applicable test results.
- Open Critical/High/Medium/Low findings, accepted exceptions, and remediation proof.

**Verification:** Independent reviewer validates the frozen source SHA, runs required docs/security checks, inspects actual demo evidence, provider outcomes/timestamps, video/screenshots, and privately retained audit record as authorized, and records exact commands/results. A failed required criterion remains FAIL/INCOMPLETE; it cannot be replaced with historical tests or simulated providers. Remediation is a separate approved implementation task followed by independent re-review. No status closeout is committed before human approval of the final audit PASS.

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
