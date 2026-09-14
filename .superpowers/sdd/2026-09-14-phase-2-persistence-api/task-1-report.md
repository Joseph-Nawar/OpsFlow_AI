# M2B Task 1 Implementation Report

## Status

**Complete.** M2B Task 1 is complete; the parent M2B milestone remains **IN PROGRESS** because its migration and mapping tasks are intentionally outside this slice.

## Scope implemented

- Added one SQLAlchemy declarative base containing exactly the six approved Phase 2 tables: `orders`, `order_lines`, `source_documents`, `validation_issues`, `audit_events`, and `order_creation_idempotency`.
- Added the six named ORM models and the minimal persistence package exports.
- Added PostgreSQL-native UUID, JSONB, TIMESTAMPTZ, and NUMERIC metadata; required primary keys, foreign keys, uniqueness constraints, and current-read indexes; and defense-in-depth checks for states, failure origins, currencies, document types, severities, hashes, positions, numeric bounds, ordered metadata shape, and idempotency values.
- Added database-independent unit metadata tests that inspect SQLAlchemy tables, columns, types, keys, foreign keys, constraints, and indexes.
- Updated only the canonical README and roadmap status text required for the first M2B commit: Phase 2 `IN PROGRESS`, M2A `COMPLETE`, M2B `IN PROGRESS`, and M2C–M2F `NOT STARTED`.
- Did not add migrations, sessions, repositories, mappers, application services, API routes, processing-attempt tables, PostgreSQL custom ENUMs, or M2C+ behavior.

## Files changed

- `README.md`
- `docs/roadmap/project-roadmap.md`
- `src/opsflow/persistence/__init__.py`
- `src/opsflow/persistence/models.py`
- `tests/unit/persistence/test_models.py`
- `.superpowers/sdd/2026-09-14-phase-2-persistence-api/task-1-report.md`

## Key decisions and dependencies

- Used SQLAlchemy 2 typed declarative mappings on the already-declared SQLAlchemy dependency; no dependency was added.
- Stored domain enum values as checked `TEXT`, preserving the approved migration flexibility and avoiding PostgreSQL custom ENUM types.
- Used `gen_random_uuid()` for server-generated entity IDs and `now()` for persistence timestamps where the design defines server metadata.
- Used JSONB for ordered source-document metadata and validation expected/actual values. The database enforces that source metadata's outer value is an array; pair reconstruction remains mapper work for the later M2B mapping task.
- Added only the approved indexes: `order_id` on order lines and source documents, plus `(order_id, occurred_at, id)` on audit events. Primary/unique constraints provide the idempotency access paths.

## Acceptance criteria

| Criterion | Result | Evidence |
| --- | --- | --- |
| Exactly six approved metadata tables | PASS | Focused metadata tests assert the literal table set and PostgreSQL DDL compilation reports six tables. |
| Six required named models and package surface | PASS | Unit test maps each named model to the expected table; package exports all six plus `Base`. |
| Required columns, primary keys, and foreign keys | PASS | Metadata inspection tests cover exact column sets, all primary keys, FK targets, and `CASCADE`/`RESTRICT` actions. |
| Ordered-child identities and idempotency uniqueness | PASS | Tests inspect both `(order_id, position)` unique constraints, validation issue composite PK, idempotency-key PK, and unique `order_id`. |
| Required defense-in-depth checks | PASS | Tests inspect state, failure-origin, currency, document type, severity, SHA-256, position, numeric, JSON-array, and idempotency check constraints. |
| Required PostgreSQL storage types without custom ENUM | PASS | Tests inspect UUID, JSONB, NUMERIC, CHAR(64), and timezone-aware DateTime metadata and reject SQLAlchemy ENUM columns. |
| Minimal current-read indexes only | PASS | Tests assert the exact index column sets on ordered children, audits, validation issues, and idempotency metadata. |
| No processing-attempt table or out-of-scope behavior | PASS | Exact table-set test and explicit absence checks pass; diff review found no migration, repository, session, service, route, or future-phase module. |
| Canonical status update | PASS | README and roadmap show Phase 2/M2B in progress, M2A complete, and M2C–M2F not started. |

## Verification

- RED: `uv run pytest tests/unit/persistence/test_models.py -q --no-cov` — expected collection error, `ModuleNotFoundError: No module named 'opsflow.persistence'`.
- GREEN: `uv run pytest tests/unit/persistence/test_models.py -q --no-cov` — 11 passed.
- `uv run pytest tests/unit -q --no-cov` — 187 passed.
- `uv run ruff check src/opsflow/persistence tests/unit/persistence` — passed.
- `uv run ruff format --check src/opsflow/persistence tests/unit/persistence` — 3 files already formatted.
- `uv run mypy src/opsflow` — success, no issues in 10 source files.
- PostgreSQL-dialect `CreateTable` compilation for all metadata tables — compiled six tables successfully without a database connection.
- `git diff --check` — passed.
- Manual diff/scope review — exact Task 1 source, tests, status documentation, and this report only; no credential or private-data material found.

## Deviations, limitations, security, and cost

- PostgreSQL execution was not performed. `docker compose ps --status running postgres` could not connect to `/Users/nawar/.docker/run/docker.sock` because the Docker daemon is unavailable. Tests remain intentionally database-independent as required; migration/database enforcement belongs to M2B Task 2.
- No migration exists in this slice, so runtime table creation and live constraint behavior are not claimed.
- No credentials, external calls, paid services, or new cost-bearing dependencies were introduced.

## Git state

- Branch: `phase/2-persistence-api`
- Starting HEAD: `2d9fb21` (`docs: complete Phase 2 implementation plan`)
- Commit created: the coherent `feat: add Phase 2 persistence schema` commit containing this report; its exact SHA is reported in the final handoff because a commit cannot embed its own object ID.
- Intended final working-tree state: clean after commit and post-commit verification.

## Review fix report

### Exactly what changed

- Changed `ck_orders_failure_origin` so its failed-state branch explicitly requires `failure_origin IS NOT NULL` before checking membership in `PROCESSING`, `EXTRACTED`, or `SYNCING`. This makes a failed state plus NULL evaluate to FALSE instead of UNKNOWN under PostgreSQL CHECK semantics.
- Replaced fragment-presence assertions for order states, source-document types, and validation severities with named-constraint parsing and exact literal-set comparisons for the required 12/5/3 values.
- Added assertions that all three order-line NUMERIC types have both `precision` and `scale` unset.
- Removed the standalone `order_id` indexes from `order_lines` and `source_documents`. Their required `UNIQUE(order_id, position)` constraints create PostgreSQL indexes with the same leading-column access path, so separate indexes were redundant.
- Changed index tests to require no explicit indexes on ordered-child tables while continuing to require the audit retrieval index `(order_id, occurred_at, id)` and no speculative validation/idempotency indexes.
- Preserved the exact six-table metadata scope, existing Phase 2/M2A–M2F status text, and the absence of migrations, repositories, sessions, services, routes, and M2C+ behavior.

### Tests and command output

- RED: `uv run pytest tests/unit/persistence/test_models.py -q --no-cov` — 2 failed, 9 passed. The failures specifically reported the redundant `order_id` index and missing `failure_origin IS NOT NULL` guard.
- GREEN: `uv run pytest tests/unit/persistence/test_models.py -q --no-cov` — 11 passed in 0.09s.
- `uv run pytest tests/unit -q --no-cov` — 187 passed in 0.78s.
- `uv run ruff check src/opsflow/persistence tests/unit/persistence` — `All checks passed!`
- `uv run ruff format --check src/opsflow/persistence tests/unit/persistence` — `3 files already formatted`.
- `uv run mypy src/opsflow` — `Success: no issues found in 10 source files`.
- `git diff --check` — exited 0 with no output.
- PostgreSQL-dialect `CreateTable` compilation — `compiled PostgreSQL DDL for 6 tables`.

### Remaining limitation

- Live PostgreSQL execution remains unavailable because the local Docker daemon was unavailable during Task 1. This fix round uses database-independent SQLAlchemy metadata inspection and PostgreSQL-dialect DDL compilation; live migration/constraint execution remains M2B Task 2 scope.
