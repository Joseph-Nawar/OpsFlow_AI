# Architecture Decision Records

This directory will hold durable records for decisions that materially affect OpsFlow AI’s architecture, interfaces, dependencies, security, cost, or operational behavior.

## When to add a decision record

Add a record when a choice is difficult to reverse, affects multiple phases, establishes a boundary, or would otherwise be easy to lose in chat history. Do not create records for routine implementation details.

## Suggested format

Use a numbered Markdown file such as `0001-short-decision-name.md` with:

```markdown
# ADR-0001: Decision title

- Status: proposed | accepted | superseded | deprecated
- Date: YYYY-MM-DD

## Context

What problem or constraint requires a decision?

## Decision

What is being chosen?

## Consequences

What becomes easier, harder, or constrained?

## Alternatives considered

What credible alternatives were rejected and why?
```

Decision records must preserve the two architecture invariants: AI interprets unstructured information while deterministic software controls decisions and side effects; n8n orchestrates while Python owns business logic. They must also respect the portfolio complexity budget and the roadmap’s $0 mandatory development-cost constraint.

No ADRs are required for this documentation-only bootstrap; the roadmap and system overview are the current durable sources of truth.
