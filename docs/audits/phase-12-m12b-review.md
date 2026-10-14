# Phase 12 M12B Independent Technical Audit

## Audit identity and decision

- **Audit date:** 2026-10-14
- **Decision:** **FAIL — M12B is not eligible for human approval.** One confirmed Medium finding prevents closure.
- **Reviewed branch:** `phase/12-portfolio-release`
- **M12A baseline:** `d2813fdee5bda31779fb99dde89df147438805ad`
- **M12B implementation:** `38ccf424ca08177c523c5e7d787a3f9e39321463`
- **M12B-F01 remediation candidate:** `2a60cdff144d3b92de8252ddbbf3bb0b9ee4bfbd`
- **Audit-start HEAD:** local and `origin/phase/12-portfolio-release` both matched the candidate SHA. The tracked worktree was clean.
- **Status at audit start:** Phase 12 IN PROGRESS; M12A COMPLETE; M12B IN PROGRESS / awaiting independent approval; M12C–M12F NOT STARTED. The audit did not change milestone status.

The reviewed requirements are the approved [Phase 12 design](../superpowers/specs/2026-10-12-phase-12-portfolio-release-design.md) and [implementation plan](../superpowers/plans/2026-10-12-phase-12-portfolio-release.md), the [Phase 8 notification contract](../superpowers/specs/2026-09-25-phase-8-email-notification-integrations-design.md), the [Phase 9 integration contract](../superpowers/specs/2026-09-29-phase-9-erp-crm-integrations-design.md), and the Phase 11 authority/evaluation evidence recorded in the [Phase 11 audit](phase-11-audit.md). No live provider operation was authorized or made.

## Baseline and full change scope

The complete diff from the M12A baseline through the M12B remediation candidate contains 26 paths. The scope is consistent with the approved M12B work:

| Area | Changed paths |
| --- | --- |
| Release and current documentation | `README.md`; `docs/architecture/system-overview.md`; `docs/development/development-guide.md`; `docs/development/phase9-n8n-sync-e2e.md`; `docs/roadmap/project-roadmap.md`; `workflows/n8n/README.md` |
| Persistence and notification behavior | `alembic/versions/0008_phase12_completion_notifications.py`; `src/opsflow/application/order_sync.py`; `src/opsflow/notifications/contracts.py`; `src/opsflow/notifications/payloads.py`; `src/opsflow/notifications/service.py`; `src/opsflow/persistence/models.py` |
| Evaluation migration-head compatibility | `src/opsflow/evaluation/commands.py`; `tests/evaluation/test_evaluation_database.py` |
| Integration tests | `tests/integration/test_phase2_migrations.py`; `tests/integration/test_phase6_commands.py`; `tests/integration/test_phase6_persistence.py`; `tests/integration/test_phase6_reads.py`; `tests/integration/test_phase6_revalidation.py`; `tests/integration/test_phase8_migrations.py`; `tests/integration/test_phase9_order_sync_claims.py`; `tests/integration/test_phase9_order_sync_migrations.py` |
| Unit and workflow contract tests | `tests/unit/notifications/test_contracts.py`; `tests/unit/notifications/test_payloads.py`; `tests/unit/notifications/test_service.py`; `tests/unit/workflows/test_phase8_notification_dispatch_contract.py` |

No dependency manifest or lockfile, exported n8n workflow JSON, Phase 11 corpus/scoring/reference artifact, or unrelated application subsystem changed. The expected model constraint and Alembic migration are the only schema changes. The only evaluation production-source change is the expected Alembic-head constant; the missing completion-event mapping described in M12B-AUD-01 remains in the otherwise unchanged Phase 11 evaluation runner.

## Findings

### M12B-AUD-01 — Medium — Blocking — completion event is not recognized by the provider-free authority probe

**Evidence:** `src/opsflow/evaluation/runner.py:144-152` maps approval/review/failure event types to notification kinds but omits `ORDER_SYNC_COMPLETED`. `_notification_authority_observation()` at [lines 576–615](../../src/opsflow/evaluation/runner.py#L576) treats every persisted notification intent as requiring a matching mapped transition. The full-corpus integration assertion is [test_real_provider_free_corpus_has_all_cases_and_all_gates_pass](../../tests/evaluation/test_release_gates.py#L308).

**Reproduction:** A fresh provider-free 36-case execution against Alembic head `0008_phase12_completion_notifications` produced 36/36 case statuses PASS, but `retry-csv-002` had two mapped notification transitions and three persisted intents. Its CSV origin correctly received Slack completion notification after synchronization. Because the event-to-kind map had no `ORDER_SYNC_COMPLETED` entry, the probe returned FAIL and `direct_authority_violation_count` became 1. The `direct_llm_side_effects_zero` gate therefore failed 1/36. The same result was reproduced by the PostgreSQL-backed full-corpus test in the clean final `make check` run.

**Interpretation:** This is not evidence of an actual direct LLM side effect or an unapproved provider call. The completion event and Slack intent are the approved M12B behavior. It is an evaluator compatibility defect that makes the required existing safety gate reject the newly valid notification. Nevertheless, the fresh evaluation and its mandatory gate did not pass; the prior frozen Phase 11 reference cannot substitute for a new-head result.

**Required disposition:** Update the authority observation and focused tests to recognize and validate the `ORDER_SYNC_COMPLETED` → `ORDER_SYNC_COMPLETED` relationship, without changing the Phase 11 corpus, scoring intent, frozen reference artifacts, or M12B notification behavior. Rerun the provider-free 36-case evaluation and full relevant checks at the new head. This audit did not make that change. **Blocks M12B approval.**

### M12B-F01 — Medium — Resolved and independently verified

The prior finding concerned disagreement between completion eligibility and Gmail target selection when the first Gmail-marked persisted source lacked an ID but a later Gmail source had one. The candidate now uses [`gmail_completion_message_id`](../../src/opsflow/notifications/service.py#L225), whose deterministic selector continues after an ineligible Gmail source for completion replies while requiring Gmail provenance for every selected ID. Source documents are loaded in persisted `position` order in [`_load_order`](../../src/opsflow/persistence/repositories.py#L342).

The PostgreSQL-backed regression at [`test_completion_skips_gmail_source_without_id_and_uses_next_eligible_source`](../../tests/integration/test_phase9_order_sync_claims.py#L644) passed independently (**1 passed**). It asserts the order completes, creates one event, creates one intent per eligible channel linked to that event, and targets the second valid Gmail source. The Phase 8 approval-time selector remains intentionally first-Gmail-source-only; [the characterization test](../../tests/unit/notifications/test_service.py#L182) and Phase 8 notification tests passed. The original behavior is preserved without widening the approval-reply contract.

### M12B-AUD-02 — Low — Non-blocking — migration downgrade requires completion-row cleanup

[Migration `0008`](../../alembic/versions/0008_phase12_completion_notifications.py#L29) documents that downgrade restores the prior allowlist “after completion rows are removed.” On the isolated migration database, an `ORDER_SYNC_COMPLETED` row made the downgrade fail while restoring the old CHECK constraint; Alembic remained at `0008` and the row was not silently removed. After deleting the seeded test order (cascading its audit/notification rows), downgrade to `0007` and upgrade back to `0008` both succeeded.

The precondition is explicit in the migration docstring and the migration is forward-compatible for existing rows. Operators must remove completion notification rows before downgrading; this audit found no separate operator-facing rollback procedure. The failure is safe and does not block the approved forward migration. Preserve this limitation in any future rollback guidance.

No other Critical, High, or Medium source-review finding was confirmed. The required evaluation gate failure above is the sole blocking finding.

## Transaction and behavior acceptance matrix

| Acceptance | Result | Evidence reviewed |
| --- | --- | --- |
| Current unexpired sync claim and lock order fence completion | PASS | [`complete_order_sync`](../../src/opsflow/application/order_sync.py#L333) enters one transaction; [`_require_current_claim`](../../src/opsflow/application/order_sync.py#L578) locks the order then sync row and checks `clock_timestamp()`, state, token, and lease. Stale/expired completion test: [lines 833–864](../../tests/integration/test_phase9_order_sync_claims.py#L833). |
| All Odoo/HubSpot receipts already persisted | PASS | The completion guard checks Odoo ID/name and HubSpot company, deal, and association receipt fields at [`_has_all_receipts`](../../src/opsflow/application/order_sync.py#L746). Missing-receipt cases assert no completion event or intent at [lines 483–533](../../tests/integration/test_phase9_order_sync_claims.py#L483). |
| Completion state, original audit event, and eligible intents are atomic | PASS | [`complete_order_sync`](../../src/opsflow/application/order_sync.py#L340) transitions, inserts one event and intents, and flushes under one transaction. [Rollback test](../../tests/integration/test_phase9_order_sync_claims.py#L900) injects failure after Gmail intent insertion and verifies state remains SYNCING, the claim remains current, and neither event nor intent commits. |
| Both intents reuse the exact same persisted event | PASS | `_insert_sync_audit` returns the event inserted/flushed by the existing persistence operation at [lines 769–785](../../src/opsflow/application/order_sync.py#L769). Gmail-origin integration assertion: [lines 594–637](../../tests/integration/test_phase9_order_sync_claims.py#L594). |
| Replay/racing workers do not duplicate logical completion events/intents | PASS | [Racing completion test](../../tests/integration/test_phase9_order_sync_claims.py#L952) uses two PostgreSQL sessions and asserts one success, one stale claim, one event, and one intent for each eligible channel. Existing database uniqueness remains `(trigger_audit_event_id, channel, kind)` at [models.py:376–380](../../src/opsflow/persistence/models.py#L376). |
| Gmail provenance is authoritative, persisted, and deterministic | PASS | [Service selector](../../src/opsflow/notifications/service.py#L218) requires `source_system=GMAIL` and a nonblank ID; persisted sources are ordered by position. Tests cover valid Gmail, missing ID, M12B-F01, non-Gmail source before Gmail, and multiple qualifying sources ([claims tests](../../tests/integration/test_phase9_order_sync_claims.py#L594)). An arbitrary non-Gmail message ID is ineligible. |
| Non-Gmail completion remains Slack-eligible; Gmail cannot suppress Slack | PASS | [Non-Gmail completion test](../../tests/integration/test_phase9_order_sync_claims.py#L719), [delayed Gmail test](../../tests/integration/test_phase9_order_sync_claims.py#L1000), and [Gmail retry-exhaustion test](../../tests/integration/test_phase9_order_sync_claims.py#L996) pass. |
| Provider acknowledgment loss retains at-least-once semantics | PASS | [Lost-ack test](../../tests/integration/test_phase9_order_sync_claims.py#L1125) reclaims the same logical intent under a new claim token; it does not claim physically exactly-once delivery. |
| Existing dispatcher supports both channels without cross-channel ordering | PASS | The workflow JSON is unchanged. [Workflow contract tests](../../tests/unit/workflows/test_phase8_notification_dispatch_contract.py#L202) verify channel-only routing, no cross-delivery prerequisite, Gmail replies to the backend-provided message ID with sender-only targeting, and Slack sends pre-rendered text. |
| Fixed completion payloads are truthful and low disclosure | PASS | [Payload builders](../../src/opsflow/notifications/payloads.py#L11) report completed processing/synchronization without shipment, payment, or fulfillment claims; completion payloads require `COMPLETED` state and a nonblank Gmail target. |
| Migration preserves prior rows and restricts kind values | PASS | [Phase 8 migration integration test](../../tests/integration/test_phase8_migrations.py#L142) verifies the existing `ORDER_APPROVED` row and payload after upgrade, accepts `ORDER_SYNC_COMPLETED`, and rejects `SYNC_FAILED`. The forward migration changes only the kind CHECK. |
| Fresh provider-free 36-case gate compatibility | **FAIL** | Detailed in M12B-AUD-01. Cases are 36/36 PASS; four gates pass; `direct_llm_side_effects_zero` fails 1/36 on `retry-csv-002`. |

The completion service creates only database intents; provider operations are performed later through the unchanged dispatcher and separate claim/outcome transactions. No live Gmail, Slack, Odoo, HubSpot, or Gemini operation occurred in this audit.

## Migration, database, and Phase 11 evidence

All database work used a dedicated PostgreSQL 16 container and databases owned by the audit Compose project `opsflow-m12b-audit-20261014`. Compose exposed only loopback `127.0.0.1:5432`. Before migration/reset, connected identity and port were checked and fresh databases had zero public tables. Repository guards passed for the integration and exact-name migration targets. The ordinary `opsflow` database was not used as a test, migration, reset, or evaluation target.

| Purpose | Verified database identity | Evidence |
| --- | --- | --- |
| Phase 8/9 integration and M12B tests | `opsflow_integration_m12b_audit_fresh`; focused rerun `opsflow_integration_m12b_audit_focus` | Both were fresh and empty before migration; connected DB/user/port verified; Alembic upgrade/current reported `0008_phase12_completion_notifications (head)`. |
| Migration preservation and downgrade test | `opsflow_migration_test` | Exact repository-allowlisted target; owner verified as `opsflow`. Clean upgrade reached `0008`; downgrade precondition was exercised, cleanup permitted `0007` downgrade, then upgrade returned to `0008`. |
| Phase 11 full-corpus compatibility | `opsflow_m11c_m12b_audit` | Separately named disposable database, initially empty, migrated to `0008` before the full suite; fixture cleanup is guarded by the `opsflow_m11c_` prefix. |
| Provider-free evaluation | `opsflow_evaluation` | Dedicated allowlisted evaluation database; host/port/database identity and migration head were checked before evaluation reset. Invoked `opsflow.evaluation.commands.run_evaluation(EvaluationMode.PROVIDER_FREE, results_directory=<temporary directory>)`; results were written outside the repository. |

The provider-free execution used corpus `3.0.0` and made zero Gemini calls. Its 36 synthetic case statuses passed, extraction quality and model cost were `NOT_APPLICABLE`, and the four non-authority gates passed. This audit invoked the evaluation function through Python with a temporary results directory; it did not execute the shell command `make evaluate`. The artifact’s `run.command` field contains the function’s default label `make evaluate` and is not treated as proof of a CLI invocation. It is not live extraction-accuracy evidence. Its latency figures are local diagnostics only and do not establish an SLA. The frozen Phase 11 reference, corpus, scoring, and results were not modified; the [Phase 11 audit](phase-11-audit.md) still records its approved 36/36 and five-gate reference. The approved `NO_OPTIMIZATION` outcome remains unchanged.

## Verification record

The definitive full-suite run used fresh dedicated integration/migration databases and a migrated dedicated M11C database. Initial audit setup attempts are retained here for transparency: one full run used a fresh but unmigrated M11C test database and produced 17 setup errors (`notification_deliveries` was absent); after migration, a second run reused databases already mutated by that run and produced unrelated integration-state failures. Those runs were not treated as product evidence. The targets were then positively reidentified, the integration database was recreated under a fresh unique name, the exact migration database was recreated, both were verified, and the integration/M11C targets were upgraded before the definitive run. The clean run below is the authoritative result.

| Command/check | Result |
| --- | --- |
| Focused PostgreSQL M12B-F01 regression: `uv run pytest tests/integration/test_phase9_order_sync_claims.py::test_completion_skips_gmail_source_without_id_and_uses_next_eligible_source -q --no-cov` | **PASS — 1 passed in 1.54s.** |
| `uv run pytest tests/unit/notifications tests/unit/workflows/test_phase8_notification_dispatch_contract.py -q --no-cov` | **PASS — 51 passed in 0.86s.** |
| `uv run pytest tests/integration/test_phase8_gmail_provenance.py tests/integration/test_phase8_migrations.py tests/integration/test_phase8_notification_api.py tests/integration/test_phase8_notification_atomicity.py tests/integration/test_phase8_notification_persistence.py tests/integration/test_phase9_order_sync_atomicity.py tests/integration/test_phase9_order_sync_claims.py tests/integration/test_phase9_order_sync_migrations.py -q --no-cov` | **PASS — 84 passed in 27.43s** on fresh database `opsflow_integration_m12b_audit_focus`, with migration tests constrained to `opsflow_migration_test`. |
| Definitive full `make check` | **FAIL — 2,141 passed, 6 skipped, 1 failed in 221.87s.** Ruff check, format check (321 files), and mypy (100 source files) passed before tests. Sole failure: `tests/evaluation/test_release_gates.py::test_real_provider_free_corpus_has_all_cases_and_all_gates_pass`, due to M12B-AUD-01. |
| `uv build` | **PASS — source distribution and wheel built.** |
| `make frontend-check` | **PASS — 68 tests, ESLint, TypeScript, and Vite production build.** `npm ci` reported two high-severity full-tree advisories, described below. |
| `docker compose config --quiet` | **PASS.** |
| `make security-audit` | **PASS — no known Python production vulnerabilities; frontend production audit found 0 vulnerabilities.** |
| `npm audit --json --prefix web` | **Exit 1 — two high-severity transitive development-tree advisories: `brace-expansion@5.0.9` (GHSA-q2hr-2g5m-vwhr, GHSA-qhr7-859c-m2p7, GHSA-6j4f-fj2g-mc7p) and `source-map-js@1.2.1` (GHSA-68fv-2mgg-jv7q); 0 critical.** This matches the known Phase 11 limitation; no dependency change was made. |
| Pinned full-history Gitleaks | **PASS — `zricethezav/gitleaks:v8.28.0` scanned 337 commits, no leaks found.** The final audit document receives an additional current-content scan before commit. |
| Migration downgrade behavior | **PASS as a documented precondition:** downgrade with a completion row failed on the CHECK constraint and stayed at head; after removing the synthetic order, downgrade to `0007` and re-upgrade to `0008` succeeded. |
| `git diff --check` and audit-document Markdown-link validation | **PASS.** 33 relative Markdown links and line anchors resolve. |

The full-tree npm advisory result is limited to the development dependency tree; the production-only audit is clean. It is not represented as a resolved advisory. No production dependency, frontend dependency, or lockfile was changed by M12B.

## Final disposition

**FAIL — M12B remains IN PROGRESS and requires remediation of M12B-AUD-01, a new clean provider-free evaluation, and fresh independent review.** M12B-F01 is resolved. The migration downgrade precondition is documented and safe but should remain visible in future operator guidance.

M12A remains COMPLETE. M12C–M12F remain NOT STARTED. This audit did not mark M12B complete, modify implementation/evaluation code, change historical Phase 11 evidence, call a live provider, or perform external mutations.
