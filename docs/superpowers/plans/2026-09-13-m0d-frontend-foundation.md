# M0D Frontend Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish the smallest conventional React, TypeScript, Vite, and ESLint frontend foundation under `web/`.

**Architecture:** Use the standard Vite React/TypeScript layout with a single `App` component, a single entry point, and one stylesheet. Keep the page static and local: it must not call the backend, introduce routing, or create future UI folders.

**Tech Stack:** Node.js 24, npm, React, TypeScript, Vite, ESLint.

**Spec:** User-provided M0D — Frontend Foundation requirements.

## Global Constraints

- The active branch is `phase/0-foundation`.
- M0A, M0B, and M0C remain complete; M0D is the only milestone implemented here.
- Use npm only and commit `web/package-lock.json`.
- Do not add React Router, styling/component/state/data libraries, frontend tests, Docker frontend infrastructure, API calls, business UI, or future-phase folders.
- Verify installation with `npm ci`, lint with `npm run lint`, and build with `npm run build`.
- Keep Node.js 24 support explicit in frontend package metadata.

---

### Task 1: Create frontend package and Vite configuration

**Files:**
- Create: `web/package.json`
- Create: `web/package-lock.json`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.app.json`
- Create: `web/tsconfig.node.json`
- Create: `web/vite.config.ts`
- Create: `web/eslint.config.js`
- Create: `web/index.html`

- [x] **Step 1: Add the minimal package metadata and scripts**

Use `engines.node` to require Node 24 and define only `dev`, `lint`, and `build` scripts. Use React, React DOM, and Vite/TypeScript/ESLint packages required by the standard Vite template.

- [x] **Step 2: Generate and inspect the lockfile**

Run `npm install` only to create the lockfile if needed, then use `npm ci` for all verification. Confirm no package manager metadata other than npm’s lockfile is added.

- [x] **Step 3: Verify configuration scope**

Confirm the Vite config has no proxy, API client, plugin, or future application configuration.

### Task 2: Add the minimal foundation page

**Files:**
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/index.css`

- [x] **Step 1: Define the intended rendered content**

The page must render only the heading `OpsFlow AI` and the message `Development environment ready.` with small, readable, intentional styling.

- [x] **Step 2: Run the development server smoke check**

Run `npm run dev -- --host 127.0.0.1`, request the served page, and confirm the expected foundation text is present with no runtime error output.

### Task 3: Verify and document M0D

**Files:**
- Modify: `README.md`
- Modify: `docs/development/development-guide.md`
- Modify: `docs/roadmap/project-roadmap.md`

- [x] **Step 1: Run frontend quality gates**

From `web/`, run `node --version`, `npm --version`, `npm ci`, `npm run lint`, and `npm run build`.

- [x] **Step 2: Run existing backend quality gates**

From the repository root, run Ruff, formatting, mypy, pytest with PostgreSQL available, and `uv build`.

- [x] **Step 3: Inspect the rendered page**

Use available browser tooling for a visual smoke check; otherwise record that browser tooling was unavailable without adding a browser framework.

- [x] **Step 4: Update durable status and command documentation**

Mark M0D complete while keeping M0E/M0F and Phases 1–12 not started. Move only successfully executed frontend commands into the verified section and keep future workflows explicitly planned/unverified.

- [x] **Step 5: Review scope and repository state**

Inspect the complete diff for starter leftovers, unnecessary packages, generated files, secrets, future functionality, broken links, and status contradictions. Commit once, push the branch, and verify a clean working tree.
