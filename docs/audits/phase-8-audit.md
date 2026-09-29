# Phase 8 Independent Audit

**Status:** PASS — Phase 8 is complete; no CRITICAL, HIGH, MEDIUM, or LOW finding remains open.

## Scope and method

The audit reviewed the full Phase 8 change set from merge base
`407c5fe96063f5790c79747278db98927a3e278a` through the pre-audit head
`6e61848f983f2db6f566030d1e57c1b363e9d892`, then reviewed the M8F remediation
and closeout diff. The review read the repository guidance, approved Phase 8
design and plan, roadmap, README, n8n guide, and Phase 7 audit; inspected all
changed Phase 8 production, persistence, workflow, test, CI, and documentation
files; searched the full test tree for destructive Alembic downgrades; and
challenged claim, lease, retry, provenance, rollback, workflow-routing, and
privacy boundaries. The migration-safety and final consolidated database gates
ran against disposable PostgreSQL databases. One earlier focused TDD
integration invocation without DB overrides is disclosed under final
verification. No live Gmail or Slack provider send was made during M8F.

The binding architecture is that Python/PostgreSQL own business state,
provenance, validation, durable notification intent, claim ownership, retries,
leases, authorization, and outcome recording. n8n 2.40.5 owns provider
transport and bounded routing only. Phase 8 ends at approval-for-processing;
ERP/CRM synchronization, `SYNCING`, and completion claims remain Phase 9 or
later work.

## Frozen findings ledger

Before remediation, the complete discovery pass froze these three findings:

| ID | Initial severity | Finding | Resolution | Status |
| --- | --- | --- | --- | --- |
| M8F-001 | MEDIUM | Delayed `REVIEW_REQUIRED` and `APPROVAL_READY` deliveries used present-tense copy that could suggest an obsolete action remained pending after downtime, restart, provider outage, queue backlog, or lease delay. | Slack summaries now identify the recorded transition: `Order entered NEEDS_REVIEW with {n} validation issue(s).` and `Order entered READY_FOR_APPROVAL.` Regression tests prove delayed copy describes the trigger event. The event-driven outbox remains intact; no cancellation state or migration was added. | RESOLVED |
| M8F-002 | LOW | The roadmap described Phase 8 as sending completion confirmation and handling synchronization failure/completion, although the approved Phase 8 scope ends before ERP/CRM work. | The roadmap now describes Gmail intake, durable notifications, Slack delivery, and sender-only approval replies, and states that Phase 8 has no ERP/CRM sync, `SYNCING`, or completion claim. | RESOLVED |
| M8F-003 | LOW | The system overview and development guide said Phase 8 provider workflows were unimplemented or still planned, contradicting README and roadmap status. | Both guides now describe the completed Phase 8 boundary and link to the audit/roadmap evidence while retaining Phase 9 as unimplemented. | RESOLVED |

Frozen initial severity totals: **CRITICAL 0, HIGH 0, MEDIUM 1, LOW 2**.
Final totals: **CRITICAL 0, HIGH 0, MEDIUM 0, LOW 0**. All three findings are
resolved; there are no accepted open findings.

### Senior-review closeout

| ID | Severity | Finding | Resolution | Status |
| --- | --- | --- | --- | --- |
| SR-001 | LOW | Embedding exact-head GitHub run IDs in this tracked artifact makes them stale when a later commit changes the artifact. | Removed recursive CI-run references. Exact final-head SHA and run IDs belong in PR metadata/conversation and must be checked on the actual PR head immediately before merge. Documentation/evidence only; no implementation impact. | RESOLVED |

### M8F-001 — MEDIUM — RESOLVED

- **Affected files/components:** `src/opsflow/notifications/payloads.py`,
  `tests/unit/notifications/test_payloads.py`, Slack review/approval messages.
- **Requirement/invariant:** A delayed event notification must not state that
  an obsolete review/approval action is currently required.
- **Evidence and impact:** Durable intents remain eligible through n8n downtime,
  restart, provider backoff, backlog, and lease delay. Existing summaries said
  `validation issue(s) require review` and `Order is ready for approval` even
  when the order could already have advanced. Operators could receive a stale
  current-sounding instruction.
- **Existing detection:** Tests checked exact templates but did not test
  delayed dispatch wording.
- **Smallest remediation:** Keep the event-driven outbox; render the triggering
  state entry historically and add a delayed-notification regression. No
  supersession status, cancellation logic, or migration.
- **Verification:** Payload tests (including the delayed-event regression),
  full Phase 8 persistence/API/workflow gate, and full backend suite passed.

### M8F-002 — LOW — RESOLVED

- **Affected file:** `docs/roadmap/project-roadmap.md`.
- **Requirement/invariant:** Phase 8 must not claim ERP/CRM synchronization,
  `SYNCING`, completion, or completion email; these are outside approved Phase
  8 scope.
- **Evidence and impact:** The prior roadmap objective mentioned
  approved/completed email, synchronization-failure Slack notifications, and
  avoiding duplicate ERP actions. Readers could attribute Phase 9 behavior to
  Phase 8.
- **Existing detection:** No automated prose/scope check.
- **Smallest remediation:** Rewrite the Phase 8 objective and exit criteria to
  match the implemented Gmail intake, durable notifications, Slack delivery,
  and sender-only approval reply boundary.
- **Verification:** Roadmap reviewed against approved design, README, and audit
  artifact; no Phase 9 behavior appears in implementation or claims.

### M8F-003 — LOW — RESOLVED

- **Affected files:** `docs/architecture/system-overview.md`,
  `docs/development/development-guide.md`.
- **Requirement/invariant:** Current implementation/status guidance must say
  which components exist and distinguish Phase 8 from future integrations.
- **Evidence and impact:** These guides said Phase 8 provider workflows were
  unimplemented or next planned, contradicting README and roadmap and obscuring
  the credential/import and operator boundaries already implemented.
- **Existing detection:** No automated cross-document status check.
- **Smallest remediation:** Update current implementation/status paragraphs,
  link the audit evidence, and retain ERP/CRM as unimplemented Phase 9 scope.
- **Verification:** README, roadmap, architecture, development guide, and this
  artifact now agree on Phase 8 complete and Phases 9–12 not started.

The M8F-001 wording change intentionally differs from the M8A plan's exact
present-tense summary strings. The design requires safe event-derived
notifications but does not require copy to imply that a past state remains
current. Event-historical copy is the smallest deterministic correction: it
keeps one durable intent per approved event, preserves retry and audit
boundaries, and avoids a new cancellation/supersession state machine.

## Whole-phase results

| Boundary | Result and evidence |
| --- | --- |
| Authority and scope | PASS. Python owns state and policy; n8n performs transport. No Phase 9 ERP/CRM path, `SYNCING` transition, or `COMPLETED` claim was introduced. Automated tests use fakes or local PostgreSQL; no ordinary test sends provider traffic. |
| Durable notification contract | PASS. One `notification_deliveries` table enforces event/channel/kind uniqueness, valid channel/kind/status, object payload, attempt cap, claim-token/lease invariant, bounded provider reference, allowlisted failure, FKs, and eligibility index. Payload serialization is bounded to 16 KiB in the application. Event and intent share a transaction; forced persistence failures roll back state and audit event. |
| Claim/outcome ownership | PASS. PostgreSQL `SKIP LOCKED` claims one row; independent-session concurrency tests prove a single active claim generation. Database time controls eligibility and the five-minute lease. Tokens rotate after reclaim; stale, wrong, expired, and terminal-generation outcomes do not mutate rows. Attempts are capped at three, with backend 30/120 second retry delays and third-attempt finalization. No fourth claim is possible. |
| API and authorization | PASS. Claim/outcome APIs reuse the orchestration bearer, use strict bounded schemas, and return fixed 401/404/409/422/503 bodies without provider diagnostics. Orchestration and review credentials are distinct; server-side constant-time bearer comparisons are used; the browser never receives the orchestration token. |
| Atomicity and review isolation | PASS. All approved event/intent insertion paths use the actual audit-event ID in their existing transaction. Notification lifecycle updates only notification rows; PostgreSQL regressions prove order state, audit history, review revision count, and ETag generation remain unchanged. |
| Gmail provenance/intake | PASS. Generic `/v1/orders` clients cannot write reserved `source_system`; ordinary metadata remains supported. Only guarded `source_system=GMAIL`, nonblank raw Gmail `message_id`, and exact `gmail:<message_id>` identity establish provenance. Intake reuses the existing endpoint. The sanitized n8n 2.40.5 graph uses its single authorized transport-envelope Code node only for deterministic attachment selection/canonicalization; body normalization remains standard-node processing. |
| Gmail source and retries | PASS. The contract covers PDF/XLSX/CSV suffix/MIME mapping, `image/*` exclusion, unsupported files, body fallback, ambiguity/no-source terminals before HTTP, byte preservation, replay/conflict identity, and maximum three total API attempts. Only connection/node transport failure and exact 503 retry; lifecycle 2xx and 401/409/422/500 do not. |
| Slack delivery | PASS. Only `channel=SLACK` reaches one native Slack 2.7 send. Backend `payload.text` is forwarded unchanged, the workflow footer and provider retries are disabled, provider failure is normalized to an allowlisted code, and success persists only the confirmed timestamp/reference. Review URLs continue to require OpsFlow operator authentication. |
| Gmail approval reply | PASS. Only a genuine Gmail-provenance `ORDER_APPROVED` claim reaches one native Gmail 2.2 sender-only Reply to the original persisted message ID. The exact plain-text body is `Your purchase order has been approved for processing.`; there is no attachment, attribution, or footer. Only the confirmed reply reference is persisted. Generic `message_id` alone cannot create a Gmail intent. |
| Cross-channel behavior | PASS. Generic approval creates Slack only; Gmail-origin approval creates separate Slack and Gmail rows for the same approval event. Channel delivery rows have independent outcomes. Ordering and exactly-once provider delivery are not promised. |
| Export and privacy | PASS. Both Phase 8 n8n exports are inactive, disable execution saving, and contain named credential references only—no credential IDs, OAuth values, Slack token/channel, mailbox address/content, attachment data, or execution history. Provider response bodies and raw source bytes are not persisted. |

## Notification-freshness ruling

The paused clean-clone run exposed pending pre-approval Slack intents after the
order advanced. This was not only an artificial test condition: n8n downtime,
restart, provider failure/backoff, queue backlog, or expired leases can delay
event delivery. The old present-tense review/approval wording could therefore
be misread as a current instruction. M8F-001 resolves that correctness risk by
making those summaries explicitly historical. Intents remain event-driven and
may be delivered after a later state transition; the message states the
recorded transition and its review link opens the current authenticated UI.
No business state, notification schema, cancellation policy, or delivery audit
was added. The `PROCESSING_FAILED` summary is explicitly phrased as a failure
event and qualified as possibly requiring operator review.

## Migration-test incident and safety ruling

After the M8E clean-clone acceptance had passed, the M8E migration test was
accidentally run against the primary local development database. At the time,
it used the ordinary application database URL while executing `alembic
downgrade base`. The local data was synthetic development state, not customer
or production data: the recorded pre-incident database had 82 orders and 23
notification rows; the destructive test left 13 orders and 6 notification
rows. There was no known usable pre-incident backup, and no missing synthetic
history was fabricated. The primary database was deliberately reset to a fresh
development baseline at migration head.

The permanent remediation requires `OPSFLOW_MIGRATION_TEST_DATABASE_URL` for
every destructive downgrade path found in Phases 2, 5, 6, and 8. The fixture
skips explicitly when that URL is absent, requires PostgreSQL, and rejects a
database name matching the configured development database even when host or
role aliases differ. Each Alembic subprocess and its SQLAlchemy assertions use
the same isolated URL. CI creates a separate migration-test database. A
regression covers missing configuration and same-database aliases. The full
test-tree search found no other destructive Alembic path. Isolated migration
verification passed 24 tests; application and migration test databases were
ephemeral, and the primary development tables remained empty at revision
`0005_phase8_notification_deliveries` before and after verification.

## Reused sandbox evidence and limitations

M8F reused the synthetic provider evidence recorded in
[`workflows/n8n/README.md`](../../workflows/n8n/README.md):

- M8C Gmail cases A–I, including label routing, PDF/XLSX/CSV, body fallback,
  unsupported/ambiguous/no-source outcomes, byte-hash parity, provenance,
  replay, and changed-byte conflict.
- M8D Slack no-work, `REVIEW_REQUIRED`, second-kind success, bounded provider
  failure, lost-outcome acknowledgement, lease recovery, and order/audit
  isolation.
- M8E primary live Gmail approval/reply and the clean-clone end-to-end path
  through fresh PostgreSQL/n8n, manual credential relinking, real React review,
  approval, Slack delivery, and sender-only original-thread Gmail reply.

M8F made no live provider sends. The following limits are intentional and
remain explicit:

- A provider may accept a message while OpsFlow loses the outcome acknowledgement;
  lease recovery can later produce a duplicate external send/reply. Delivery is
  at-least-once, not exactly-once.
- Phase 8 Slack/Gmail summaries describe persisted events. A delayed event may
  arrive after the order advances, but review/approval copy identifies the
  transition rather than asserting that it is still pending.
- Pinned provider nodes do not safely expose a Retry-After hint; the backend
  fixed retry schedule remains authoritative where no bounded hint is passed.
- The Gmail label/filter routes the dedicated sandbox workflow but does not
  narrow the OAuth grant. Dedicated mailbox authorization and local credential
  relinking remain operational setup steps.
- The approval reply confirms approval for processing only. No ERP/CRM
  synchronization or completion claim is made.

## Final verification

The destructive migration tests and the final focused/full database-backed
gates used separate disposable `opsflow_test` and `opsflow_migration_test`
databases in an ephemeral PostgreSQL 16 container. During the first focused TDD
green check, the notification-persistence integration module was invoked once
without those URL overrides and therefore used the primary database. Its seeded
order graphs are deleted by test teardown; the subsequent primary-table
snapshot showed zero rows in every application table. All destructive tests
and all final focused/full gates were explicitly isolated, and primary counts
were checked before and after those final gates. Primary Postgres/API/n8n
containers and primary Docker volumes were not changed.

| Gate | Result |
| --- | --- |
| Destructive migration safety and Phase 2/5/6/8 migration tests | PASS — 24 passed; isolated URL required. |
| Focused Phase 2/5/6/7/8 integration and workflow gate | PASS — 277 passed. |
| Full backend suite | PASS — 1,455 passed; 92.61% coverage (80% project gate). |
| Frontend tests | PASS — 68 tests in 12 files. |
| Frontend lint/build | PASS — ESLint and Vite production build. |
| Ruff / format / mypy | PASS — lint clean; 204 files formatted; 71 source files type-checked. |
| Python package build | PASS — source distribution and wheel built. |
| Compose config / workflow JSON | PASS — Compose configuration valid; all three tracked n8n JSON files parse. |
| Diff whitespace check | PASS — `git diff --check`. |
| Primary DB safety | PASS for final gates — migration head `0005_phase8_notification_deliveries`; orders, lines, sources, idempotency, audits, snapshots, review revisions, and notification rows were zero before and after targeted/full suites. The initial TDD-run deviation and post-run zero-row check are disclosed above. |
| Gitleaks / GitHub CI | PASS. Full-history Gitleaks is a required CI check and passed with zero leaks. Backend, Frontend, and Secret Scan must all be green on the actual PR head before merge. Exact final-head SHA and run IDs are intentionally not embedded here because changing this tracked artifact creates a new commit; record those values in PR metadata/conversation and independently recheck them immediately before merge. |

Final repository status is Phase 8 `COMPLETE` with M8A–M8F `COMPLETE`;
Phases 9–12 remain `NOT STARTED`. Pull request #8 is open for independent
review and remains unmerged. M8F does not begin Phase 9.
