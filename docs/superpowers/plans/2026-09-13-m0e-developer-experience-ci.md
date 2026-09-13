# M0E Developer Experience & CI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Standardize the existing backend, frontend, database, and secret-scan workflows through a concise Makefile and one read-only GitHub Actions workflow.

**Architecture:** The Makefile is a thin command interface over `uv`, npm, Docker Compose, and Alembic. CI has exactly three jobs—backend, frontend, and secret-scan—with PostgreSQL 16 only as the backend service; no application code or deployment infrastructure is added.

**Tech Stack:** GNU Make, Python 3.12, `uv`/`uv.lock`, PostgreSQL 16, Node.js 24/npm, GitHub Actions, and the pinned Gitleaks CLI container.

**Spec:** User-provided M0E — Developer Experience & CI requirements.

## Global Constraints

- Work only on `phase/0-foundation`; M0A–M0D remain complete and M0F/later phases remain unstarted.
- Keep the production-grade portfolio complexity budget; use wrappers rather than a shell framework.
- Quality-check targets must not silently start or destroy infrastructure; document PostgreSQL availability for backend tests.
- CI must use `permissions: contents: read`, no `pull_request_target`, no credentials, and no deployment behavior.
- Backend CI uses Python 3.12, frozen `uv` dependencies, and real PostgreSQL 16.
- Frontend CI uses Node.js 24, `npm ci`, lint, and production build.
- Secret scanning uses a pinned open-source Gitleaks container and scans history where practical.
- No product functionality, future-phase source, custom Skills, nested `AGENTS.md`, or generated artifacts.

---

### Task 1: Add the stable local command interface

**Files:**
- Create: `Makefile`

- [x] **Step 1: Define thin, non-surprising targets**

Add `test`, `test-integration`, `lint`, `format`, `typecheck`, `backend-check`, `frontend-check`, `check`, `up`, `down`, and `migrate`. Use `uv run` for Python, `npm --prefix web` for frontend, and `docker compose` for lifecycle/migration wrappers. Make format a non-mutating Ruff check and keep PostgreSQL requirements explicit in target comments/documentation.

- [x] **Step 2: Confirm target composition**

Ensure `backend-check` calls the existing lint, format, typecheck, full pytest, and `uv build` commands; `frontend-check` calls `npm ci`, lint, and build; and `check` depends on the two aggregate targets without duplicating command bodies.

### Task 2: Add the single CI workflow

**Files:**
- Create: `.github/workflows/ci.yml`

- [x] **Step 1: Configure safe workflow triggers and permissions**

Run on pushes and pull requests with `permissions: contents: read` and no write-capable events or credentials.

- [x] **Step 2: Configure the backend job**

Use Python 3.12, a PostgreSQL 16 service with a `pg_isready` health check, `OPSFLOW_DATABASE_URL`, exact uv installation, `uv sync --frozen --dev`, clean migration/current checks, and all backend quality gates.

- [x] **Step 3: Configure the frontend job**

Use Node.js 24 and `web/package-lock.json`; run `npm ci`, `npm run lint`, and `npm run build`.

- [x] **Step 4: Configure the secret-scan job**

Checkout full history and run a pinned Gitleaks open-source container against repository history without repository secrets.

### Task 3: Update clean-checkout documentation and status

**Files:**
- Modify: `README.md`
- Modify: `docs/development/development-guide.md`
- Modify: `docs/roadmap/project-roadmap.md`

- [x] **Step 1: Document the clean-checkout sequence**

Document prerequisites, uv/npm installation, `.env` setup, `make up`, `make migrate`, backend/frontend development servers, quality gates, and `make down`, while marking only observed commands as verified.

- [x] **Step 2: Update M0E status**

Mark M0E complete, keep M0F not started, keep Phase 0 in progress, and keep Phases 1–12 not started.

### Task 4: Verify locally, from a clean checkout, and remotely

**Files:**
- No additional source files; verification only.

- [x] **Step 1: Run local Make targets and Gitleaks**

Run all required Make targets with PostgreSQL available, verify Docker lifecycle/migration behavior, and run the pinned Gitleaks command locally.

- [x] **Step 2: Verify a fresh clone**

Clone the pushed branch into an isolated temporary directory, run the documented setup and quality commands, and fix any reproducibility defect on the working branch.

- [x] **Step 3: Commit and push one coherent M0E change**

Inspect the complete diff for future leakage, secrets, unpinned tools, generated artifacts, and duplicated command logic; commit once and push `phase/0-foundation`.

- [x] **Step 4: Confirm the GitHub Actions run**

Wait for the pushed workflow, record its run and job identifiers, and do not claim completion until backend, frontend, and secret-scan jobs all succeed.

- [x] **Step 5: Confirm final repository state**

Run `git diff-tree --check -r HEAD`, confirm the remote ref matches HEAD, and confirm the working tree is clean.
