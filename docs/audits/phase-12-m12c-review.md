# M12C limited-scope independent review and human acceptance

## Decision

**Verdict: PASS against the owner-approved limited-scope M12C acceptance amendment.**
The independent technical review on 2026-10-20 reported zero Critical, High,
or Medium findings. The human owner accepted M12C and authorized its
documentation closeout on 2026-10-20. This decision closes M12C under the
amended scope; it does not close Phase 12 or change the original M12C-3 run
result.

The reviewed candidate was branch `phase/12-portfolio-release` at technical
HEAD `fc70d37fd004847fab0a4c42499e75afe1d6198b`, with the six documentation
files later carried forward in the closeout. Protected transaction evidence
and screenshot files remain outside Git.

## Supported claims and evidence limits

The independent review cross-checked the retained run, database cross-check,
provider outcomes, replay record, screenshot inventory, and sanitized images.
It independently verified the recorded screenshot hashes and inspected all
12 sanitized images at full resolution. The source and derivative sets remain
separate in the private evidence area; the captures are labeled **POST-RUN
INSPECTION**. They document genuine persisted views, not the earlier
transaction sequence.

Within the amended scope, retained evidence supports one logical order at
`COMPLETED`, scripted FakeProvider extraction with deterministic validation,
revision 1 by `m12c3-local-reviewer`, and approval by a distinct
`m12c3-local-approver`. It supports actual Odoo sale order `S00001`, a HubSpot
Deal associated with the reused synthetic Company, four delivered Slack
notifications and two delivered Gmail replies, and post-sync notification
intents tied to the completion event and successful sync receipts. Exact-source
replay returned HTTP 200 with `idempotent_replay=true` and unchanged logical
counts. Screenshots corroborate only the states visible in each capture;
provider receipts alone are not treated as proof of every external side effect.

The original M12C-3 uninterrupted demonstration criterion remains **PARTIAL**.
The Gmail Trigger intake POST returned HTTP 401. Intake then succeeded through
owner-assisted recovery of the original source. The failed POST's exact
request bytes were not retained, and uninterrupted automated Gmail
Trigger-to-OpsFlow intake was **NOT DEMONSTRATED**. Extraction used scripted
FakeProvider output, not live Gemini; live Gemini quality, token usage, and
cost are not established. The screenshots were captured after the
transaction. Gmail and Slack delivery remain at-least-once; no physical
exactly-once claim is made. Historical Phase 8 evidence remains separate and
does not fill the M12C intake gap.

## Findings and handoff

No Critical, High, or Medium findings remain open. The independent review
recorded two Low findings for the private evidence and any future public-media
handoff:

- A private `.DS_Store` file is present in the protected evidence area. Its
  containing directory is mode `0700`, and the file is outside Git. Keep that
  directory private.
- Before any public use, redact the HubSpot **Sales Hub Enterprise** label and
  explicitly caption that the extraction shown is scripted FakeProvider
  output. Do not present it as live Gemini inference.

These are handoff requirements, not blockers to the limited-scope M12C
acceptance. Media creation or publication remains outside this closeout.

## Status boundary

M12C is **COMPLETE under the approved limited-scope amendment**. M12C-3 remains
**PARTIAL** against its original uninterrupted demonstration criterion.
Automated Gmail Trigger-to-OpsFlow intake remains **NOT DEMONSTRATED**.
M12D, M12E, and M12F remain **NOT STARTED**. No new provider operation, replay,
synchronization, database mutation, workflow activation, media publication,
or cleanup is authorized by this disposition.
