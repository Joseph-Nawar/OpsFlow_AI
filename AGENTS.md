# OpsFlow AI Repository Guidance

## Purpose and complexity budget

OpsFlow AI is a production-grade portfolio project that demonstrates reliable B2B purchase-order and operations automation. It is not an enterprise platform and must remain understandable, demonstrable, and locally runnable.

Prefer the smallest design that satisfies the current milestone or phase. Do not add speculative abstractions, generalized frameworks, microservices, Kubernetes, Kafka, elaborate event buses, or cloud infrastructure without a concrete current requirement. Do not create future-phase modules early.

## Architecture invariants

1. AI interprets unstructured information; deterministic software controls business decisions and side effects.
2. n8n orchestrates workflows; Python owns business logic.

LLM output may extract fields and evidence, but it must not approve orders, validate trusted business data, choose execution, or cause external mutations. n8n may trigger, sequence, integrate, notify, and route simply; Python owns document processing, extraction, validation, policy, persistence, state transitions, auditability, and integration contracts.

## Sources of truth

- `docs/roadmap/project-roadmap.md` is the durable product and engineering roadmap.
- `docs/architecture/system-overview.md` is the durable architecture boundary reference.
- `docs/architecture/domain-model.md` is the authoritative Phase 1 domain contract.
- `docs/development/development-guide.md` is the current development workflow and convention reference.
- The current milestone or phase brief and user request define the active scope.
- Code, tests, and committed configuration are authoritative for behavior that has already been implemented.

If sources conflict, stop and resolve the conflict explicitly in the relevant milestone or phase brief. Do not silently reinterpret the roadmap.
Canonical project status must reflect work already underway: when a milestone within a parent phase begins, that parent phase is `IN PROGRESS`, not `NOT STARTED`.

## Scope discipline

- Work only on the requested milestone or phase and its stated acceptance criteria.
- Do not implement future-phase functionality, create speculative source directories, or add placeholder modules.
- Keep external side effects behind explicit adapters, test doubles, sandbox accounts, or configuration controls once those integrations exist.
- Never introduce credentials, API keys, private business data, or secrets into the repository.

## Testing principles

- Follow test-driven development where practical for deterministic behavior: failing test, confirmed failure, minimal implementation, passing test, justified refactor.
- Tests must not weaken expected behavior to make a change pass. Do not remove assertions, silently skip tests, or change expected results to match broken behavior.
- Automated tests must not unexpectedly call live AI providers, create ERP orders, send email, or mutate CRM records.
- Do not invent tests for a documentation-only milestone when no application behavior exists. Verify documentation, links, scope, and repository state instead.

## Git expectations

- Work on the branch designated by the current milestone or phase.
- Make coherent, focused commits with clear messages.
- Inspect the diff before committing and keep unrelated changes out.
- Do not rewrite or discard existing user work without explicit instruction.
- A milestone is not complete until the working tree is clean and the commit state is reported.

## Definition of Done

A milestone or phase is done only when its acceptance criteria are met, documented scope is respected, relevant checks are run, no known secrets are present, and the result is reviewable as a coherent commit. Implementation milestones or phases additionally require applicable tests, lint, type checks, builds, and integration or manual checks from the milestone or phase brief. Documentation-only milestones or phases require content, link, consistency, secret, and scope verification instead of invented application tests.

## Required Codex closeout report

Every milestone or phase closeout must include:

- Status: Complete, Partial, or Blocked.
- Scope implemented.
- Files changed.
- Key decisions and dependencies introduced.
- Acceptance criteria with PASS/FAIL and concrete evidence.
- Verification commands and results, including manual checks where relevant.
- Deviations, known limitations, and security/cost notes.
- Git branch, HEAD commit, commits created, and working-tree state.
