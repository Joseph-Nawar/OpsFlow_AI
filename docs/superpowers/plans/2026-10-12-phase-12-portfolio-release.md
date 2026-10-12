# Phase 12 Portfolio Release Implementation Plan

> For agentic workers: use the repository's single-agent, sequential workflow. Execute one approved milestone at a time and stop at its review gate. This draft authorizes no implementation.

**Goal:** Make OpsFlow AI a locally reproducible, evidence-backed portfolio project with a truthful full sandbox demonstration and release-ready documentation.

**Architecture:** Reuse the existing React review app, Python/FastAPI business services, PostgreSQL state and receipts, and n8n provider workflows. Close the missing post-sync notification path only if the owner approves that narrow behavior change; use real dedicated sandbox providers for the required full demo.

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
- Do not claim real Gemini accuracy, provider latency, authoritative token usage, model cost, production performance, ROI, savings, customer adoption, or deployment without the corresponding evidence.
- Keep provider credentials, raw messages, attachments, private IDs, execution history, and local state out of tracked files and media.
- Do not change repository visibility, create a release, publish a deployment, or open/merge a PR as part of the milestones unless separately authorized.

## Review Focus

1. **Approval mistaken for completion:** completion mail and final Slack must be tied to successful Odoo and HubSpot receipts, not ORDER_APPROVED.
2. **Fake extraction presented as Gemini:** provider identity must be visible in captured evidence; fake output remains scripted.
3. **Cross-channel order and duplicate send:** Slack completion must not become eligible before Gmail completion is acknowledged; delivery remains at-least-once.
4. **Reused or shared sandbox state:** every live rehearsal must verify fresh local project/database identity and dedicated external accounts before writes.
5. **Unsupported metrics or license claims:** every claim must link to evidence and every license/media obligation must be owner-approved and verified.

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

**Work and acceptance:**

- Reorder the README so business problem, solution, current human authority, demo entry point, and quick start precede the long historical status narrative.
- Keep detailed setup instructions in existing guides; add links instead of copying Phase 8/9 sandbox procedures.
- Correct the architecture guide's current-implementation and target-diagram wording without changing authority boundaries.
- Link the README demo entry to detailed existing provider guides and state that new whole-flow evidence is pending.
- Distinguish current phase status from historical audit snapshots. Phase 12 may say IN PROGRESS (planning or approved implementation) only while work is active; implementation remains NOT STARTED until an approved implementation task begins.
- Every setup command must be runnable from a clean clone without copying ignored files or relying on an existing DB, n8n volume, or developer account state.

**Verification:**

- Run the repository's standard-library relative Markdown link check across README.md and docs; expected result: every local target exists.
- Review README commands against Makefile, .env.example, Compose, pinned runtimes, and the linked sandbox guides.
- Run git diff --check; expected result: no whitespace errors.
- No application tests are added for this documentation-only milestone.

**External services and authorization:** None for docs. Do not start services, set up accounts, or invoke provider APIs.

**Review gate:** Human review checks all current-status claims, audience clarity, command accuracy, and links. M12B cannot begin until the completion-notification behavior decision is recorded.

**Non-goals:** No feature work, demo capture, license selection, dependency changes, new setup framework, or cloud hosting.

## Milestone M12B — Completion-notification path

**Objective:** If approved, satisfy the roadmap's post-sync confirmation-email-then-Slack sequence by extending the existing durable notification path, not by simulating or relabeling approval notifications.

**Prerequisites:** Separate human approval of the exact behavior in the design proposal, including email copy, Gmail provenance eligibility, ordered Slack gating, and failure/duplicate semantics. If declined, record the full demo acceptance as unsatisfied or obtain explicit approval for a roadmap amendment; do not proceed as if the gap were closed.

**Reuse:** Existing order-sync completion transaction and receipts, AuditEvent, notification outbox, Gmail sender-only reply, Slack payload, authenticated notification claim/outcome API, n8n notification dispatcher, and existing database-safety test guards.

**Files:**

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

**Required contract:** Only after both Odoo and HubSpot receipts commit and the order enters COMPLETED may the backend create a completion audit event and Gmail completion intent. Only a persisted GMAIL-provenance source may receive a reply. The backend must make the final Slack completion intent eligible only after Gmail's completion intent records DELIVERED. If Gmail is unavailable or permanently fails, do not send a Slack success message. Existing approval-time notifications remain separate and retain their event meaning. Same-event replay must not create another logical completion intent. Provider success followed by lost acknowledgement may still cause a duplicate email under the existing at-least-once contract.

**Acceptance and verification:**

- Add focused failing tests first for wrong state, missing Odoo/HubSpot receipt, non-Gmail provenance, successful completion, Gmail failure, lost outcome acknowledgement, repeated sync/replay, and ordering.
- Confirm failures before implementation, then implement the smallest extension and a forward-only migration for the notification-kind constraint.
- Run focused notification and sync tests: uv run pytest tests/unit/notifications tests/unit/workflows/test_phase8_notification_dispatch_contract.py -q --no-cov.
- Run the isolated Phase 8/9 integration suites, including migration and transaction/claim tests, against fresh guarded disposable databases; expected: all focused tests pass and only approved optional live-provider suites remain skipped.
- Run uv run alembic upgrade head and uv run alembic current against a fresh disposable database; expected: head 0008_phase12_completion_notifications.
- Run docker compose config --quiet and the full repository make check with newly identified disposable integration, migration, evaluation, and M11C databases; expected: all configured quality gates pass.
- Review that n8n only transports backend-owned payloads and does not decide eligibility or sequence.

**External services and authorization:** Tests use fakes and disposable local PostgreSQL only. No real email, Slack, Odoo, HubSpot, Gemini, or billable call during implementation checks. Live integration operations require a later, separate authorization.

**Review gate:** Independent code review must approve the transaction boundary, migration, sender provenance, notification order, retry behavior, audit semantics, and at-least-once limitation. Human approval is required before M12C.

**Non-goals:** No new email/Slack provider, no generalized notification framework, no change to approval authority, no direct provider call from the API, no exactly-once delivery claim, and no extra workflow engine.

## Milestone M12C — Full sandbox demonstration and clean clone

**Objective:** Verify and record one uninterrupted, reproducible whole-flow run from Gmail to post-sync completion notification using actual dedicated sandbox services.

**Prerequisites:** M12A and approved M12B complete; the completion-sequence, sandbox, and demo-Gemini decisions accepted; a literal clean clone at the exact candidate SHA; separate explicit authorization for the actual Gemini extraction call, real Gmail send/reply, Slack message, Odoo/HubSpot sandbox writes, and any potentially charged operation.

**Reuse:** Existing clean-clone steps and provider-specific setup from docs/development/phase9-n8n-sync-e2e.md, docs/development/odoo-m9c-sandbox.md, docs/development/hubspot-m9d-sandbox.md, and workflows/n8n/README.md.

**Files:**

- Modify: docs/development/phase9-n8n-sync-e2e.md to add the whole-flow runbook after M12B's behavior is approved and implemented. Include prerequisites, fresh project identity, ordered operator actions, expected evidence, cleanup, replay, safe stop conditions, and clean-clone instructions.
- Modify: workflows/n8n/README.md
- Modify: README.md for the tested demo instructions and actual outcomes
- No separate demo subsystem or durable raw-response artifact; sanitized live evidence belongs in the final Phase 12 audit.

**Manual acceptance:**

- Verify fresh clone SHA and clean tree before configuration.
- Create a uniquely named OpsFlow Compose project, fresh PostgreSQL/n8n volumes, and a separate disposable Odoo database; verify identities before migrations or writes.
- Configure unique orchestration, reviewer, and approver credentials locally, configure the actual Gemini provider using the documented ignored local setting, and manually relink the sanitized n8n workflow exports.
- Verify dedicated Gmail/Slack accounts, minimal scopes, HubSpot developer-test identity, Odoo database identity, synthetic customer/product/stock, and local API readiness.
- Receive one synthetic Gmail PO, verify the document processor parsed it before the actual Gemini provider extracted the draft, inspect provider identity and deterministic route, review/revalidate, and approve using distinct roles. A fake-provider run is rehearsal evidence only and leaves full-demo acceptance FAIL/INCOMPLETE.
- Verify actual Odoo order, HubSpot Company/Deal/association, COMPLETED state and receipts, then Gmail completion reply, then final Slack completion signal.
- Replay the exact same source/event identity. Verify no second logical OpsFlow order or Odoo/HubSpot object and no new completion intent. Record provider delivery counts truthfully and retain the at-least-once limitation.
- Capture only sanitized stage evidence. Disable workflow execution-data saving. Clean up only synthetic records, dedicated inbox/channel content, temporary keys, and the named local services according to the runbook.
- Repeat the documented onboarding in a literal second clone with fresh local state. No hidden local files, reused n8n state, copied .env, or prior database may be required.

**Verification:** The runbook contains the exact operator commands and manual checks. Evidence reports candidate SHA, tool versions, real provider identity types, states/receipts, record counts before/after replay, and cleanup results. Do not count Phase 8/9 historical runs or fake-adapter tests as this acceptance.

**External services and authorization:** This milestone performs an actual Gemini extraction from synthetic input, live sandbox mutations, and sends real test email/Slack messages. Each requires separate explicit authorization before execution; Gemini may incur charges. If a required service cannot be safely accessed or the Gemini call is not authorized, mark full-demo acceptance FAIL/INCOMPLETE and report the evidence gap; do not substitute a fake result.

**Review gate:** Human reviews the sanitized run evidence and verifies provider identities and the actual required sequence before M12D.

**Non-goals:** No production/customer account, shared Odoo database, production HubSpot portal, public deployment, forced provider outage, lost-acknowledgement exercise, or mutation outside the dedicated synthetic records.

## Milestone M12D — Case study and evidence-backed claims

**Objective:** Publish a concise technical case study grounded in Phase 11 reference evidence and the new live sandbox run.

**Prerequisites:** M12A complete; provider-free reference unchanged; M12C evidence if the full-demo claim is to be included. Live Gemini metrics remain optional.

**Reuse:** docs/evaluation/reference/phase-11-provider-free-baseline.md, phase-11-baseline-decision.md, phase-11-live-gemini-unavailable.md, the unchanged reference JSON, Phase 8–11 audits, and the sanitized Phase 12 demo record.

**Files:**

- Create: docs/case-study.md
- Modify: README.md to summarize and link to the case study
- Modify: docs/development/development-guide.md only for durable command/limitation updates

**Acceptance:**

- Map every claim to a specific source, run SHA, mode, population, count, and environment near the claim.
- Report 36/36 PASS as provider-free correctness/safety evidence, never Gemini accuracy.
- Report deterministic violation routing 7/7, duplicate blocking 4/4, malformed/security 4/4, invalid execution 0/13, and direct LLM side effects 0/36 with the synthetic corpus qualifier.
- If showing local timing, preserve sample counts and call it diagnostic; state Phase 11 NO_OPTIMIZATION and no production SLA.
- State Gemini quality, authoritative tokens, live provider latency, and model cost as unmeasured unless a separately approved valid run produces evidence.
- State manual-step reduction, ROI, savings, customer adoption, and production deployment as not measured/not claimed.
- Distinguish the live Phase 12 sandbox run from prior tests and the provider-free evaluation.

**Verification:** Run the exact provider-free make evaluate only in the guarded dedicated evaluation database when refreshing evidence; otherwise link the immutable existing reference. Validate JSON/Markdown reference consistency if a new reference is explicitly approved. Do not overwrite reference artifacts as part of ordinary documentation edits. Run the documentation link check and git diff --check.

**Optional live measurement:** The existing make evaluate-live command executes the complete 36-case evaluation and is not a strictly limited subset. Do not run it as a limited measurement. Default to retaining the unavailable evidence record. If the owner requests a strict cap, define a separately reviewed measurement contract with an explicit case/call limit and spend cap before implementing or calling a live provider. This optional path does not block the case study if the case study plainly reports the metric unavailable.

**External services and authorization:** Provider-free evidence requires no live model. Any full live evaluation, limited evaluation mode, or changed pricing input requires separate design approval and explicit call/spend authorization.

**Review gate:** A technically literate human checks the case-study evidence map and all public claims before media production.

**Non-goals:** No ROI assumptions, synthetic results presented as customer data, new evaluation framework, baseline rewrite, or optimization.

## Milestone M12E — Media, licensing, privacy, and public hygiene

**Objective:** Prepare a small, original, legally reviewed visual evidence pack and perform the required security/privacy checks on the public repository candidate.

**Prerequisites:** M12C complete; media/source-asset and license choices approved; any new files use only synthetic and sanitized content.

**Files:**

- Create: docs/media/portfolio-demo-overview.png
- Create: docs/media/portfolio-demo-review.png
- Create: docs/media/portfolio-demo-integrations.png
- Create: docs/media/portfolio-demo.mp4, only if the owner selects repository storage and the file is at most 20 MiB
- Create: docs/media/portfolio-demo.vtt when a recording is made
- Create: docs/media/ASSET-LICENSES.md for authorship/provenance and third-party notices
- Create: docs/security/privacy.md
- Modify: README.md to link to media and privacy/security information
- Modify: docs/development/dependency-security.md with current advisory disposition
- Create: LICENSE only after the owner selects the terms; create NOTICE only if the selected license and reviewed assets require it

**Acceptance:**

- Keep raw capture sources and provider responses outside Git. Each screenshot is at most 1 MiB and the optional optimized video is at most 20 MiB; use no background music or unlicensed assets.
- Review each image/frame at full size for names, mailbox addresses, browser secrets, API keys, execution data, private IDs, and non-synthetic content.
- Keep attribution and license provenance for every added visual/recorded asset. Vendor names/logos are used only as needed to identify integrations and carry no endorsement claim.
- Owner-selected code and documentation/media licenses are stated accurately. Dependency, Odoo addon, and asset notices are reviewed; public visibility is not described as permission to reuse.
- Run pinned full-history Gitleaks with redaction, current-content scan of docs and media metadata, check-ignore and tracked-file checks for .env and local Odoo configuration, and complete/production-only dependency audits.
- Confirm `git ls-files -- .env integrations/odoo/.env.m9c-sandbox` and `git log --all --format=%H -- .env integrations/odoo/.env.m9c-sandbox` return no tracked paths or commits for either credential file.
- Reconcile the current development-tree npm advisories; remediate or document a narrow approved disposition and verify the production exposure analysis. No security finding is described as fixed without evidence.
- Remove or ignore generated/private outputs while retaining synthetic fixtures and selected deliverables.

**Verification commands:** Run the exact pinned Gitleaks v8.28.0 full-history scan documented in docs/development/dependency-security.md / prior Phase 9 audit; run its redacted current-directory scan over docs and docs/media; run make security-audit and npm --prefix web audit --json for full-tree disposition; run git check-ignore -v .env integrations/odoo/.env.m9c-sandbox and confirm those files are not tracked; run git diff --check and the docs link checker.

**External services and authorization:** No provider operation. Media capture uses the already approved synthetic rehearsal only. Any external hosting/publishing requires separate approval.

**Review gate:** Human approves license and residual advisory/asset dispositions. An independent reviewer checks privacy, scan coverage, and media before the final audit.

**Non-goals:** No license selection by the implementer, no third-party stock imagery, no repository visibility change, no upload or hosting, no oversized raw media, and no credentials in assets.

## Milestone M12F — Independent Phase 12 release audit and closeout

**Objective:** Independently decide whether the portfolio release meets the approved roadmap and close Phase 12 only after all required evidence passes.

**Prerequisites:** M12A–M12E complete; exact frozen candidate SHA; clean tree; all decisions and external-operation authorizations/dispositions recorded.

**Files:**

- Create: docs/audits/phase-12-audit.md
- Modify only at final PASS: README.md, docs/roadmap/project-roadmap.md, and docs/development/development-guide.md with Phase 12/M12 statuses and the audit link

**Audit coverage:**

- Scope and roadmap traceability; status truth; no future product scope or unsupported claim.
- Whole-flow live demo, sandbox identities, clean-clone repeatability, actual downstream provider records, Gmail/Slack order, replay counts, cleanup, and deviations.
- Case-study metric-to-source mapping; provider-free/live distinction; limitations; pricing/token provenance; manual-step claim disposition.
- License owner approval; dependency and media licenses; privacy, source assets, public Git history, ignored files, and current dependency advisories.
- README/setup/architecture/evaluation coherence; links; media sizes; workflows; migrations; CI and applicable test results.
- Open Critical/High/Medium/Low findings, accepted exceptions, and remediation proof.

**Verification:** Independent reviewer validates the frozen source SHA, runs required docs/security checks, inspects actual demo evidence and outputs, and records exact commands/results. A failed required criterion remains FAIL/INCOMPLETE; it cannot be replaced with historical tests or simulated providers. Remediation is a separate approved implementation task followed by independent re-review. No status closeout is committed before human approval of the final audit PASS.

**Independence:** Follow the repository's single-agent workflow; the final audit reviewer must not be the implementation author. Arrange a human/senior reviewer for this gate rather than silently self-certifying or dispatching an agent contrary to repository instructions.

**External services and authorization:** The audit itself should inspect retained evidence and avoid repeating live mutations. Any needed rerun requires the same separate approvals as M12C.

**Review gate:** Human accepts the final audit and the exact closeout commit. Then update current status to Phase 12 COMPLETE. Historical Phase 8–11 audits remain unchanged.

**Non-goals:** No implementation remediation inside the independent audit, no live re-test without approval, no merge, release upload, visibility change, or cloud deployment.

## Verification hierarchy

1. Review the selected milestone diff, scope, generated artifacts, and branch status.
2. For behavior changes, use focused TDD, then guarded migration/integration checks.
3. Run make check and make security-audit using fresh disposable database identities where required.
4. Run exact clean-clone setup, provider-free evaluation, and only the separately approved real sandbox demonstration.
5. Validate relative Markdown links, workflow JSON/Compose configuration, media metadata/size, git diff --check, ignore/tracked-file rules, and pinned full-history Gitleaks.
6. Complete the independent release audit and human approval.

The final audit must not call tests that can mutate live accounts, send email, contact Gemini, or incur charges. Such operations require separate explicit authorization before their execution.
