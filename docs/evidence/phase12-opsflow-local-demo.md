# Phase 12 synthetic local review evidence

## Scope and result

This package records one fresh, local transaction against the real OpsFlow API
and existing review application. The source is the fictional purchase order in
[`fixtures/phase12/local-review-order.txt`](../../fixtures/phase12/local-review-order.txt).
The API accepts it as `EMAIL_BODY` text through the authenticated intake route;
there is no customer-facing upload screen. The workflow uses an isolated local
PostgreSQL database, a deterministic `FakeProvider` fixture, and the existing
review UI. The browser recording is a real Playwright capture at 1440×900 and
60.64 seconds, with a caption track and sidecar subtitles.

No live Gemini, Gmail, Slack, Odoo, HubSpot, or n8n service was called. The
audit event's `orchestration:n8n` actor is the application's fixed service
identity for this API boundary; it does not mean an n8n workflow ran in this
capture. No order synchronization or external notification was performed.

## Dependency security disposition

The historical Phase 12 CI failure was the production Python dependency
audit ([run 39577318680](https://github.com/Joseph-Nawar/OpsFlow_AI/actions/runs/39577318680)).
The current frozen lock is updated with the CI-pinned `uv==0.12.2`, without
changing `pyproject.toml` constraints or the lock revision:

| Package | Previous | New | Reason |
| --- | ---: | ---: | --- |
| `certifi` | 2026.7.22 | 2026.10.23 | Beyond the fix floor in [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2). |
| `pyasn1` | 0.6.4 | 0.6.5 | First release fixing the audited advisories, including [GHSA-2qm8-x737-gmw5](https://github.com/advisories/GHSA-2qm8-x737-gmw5). |
| `pypdf` | 6.19.0 | 6.21.4 | Highest fix version required by the audited findings, within the existing `<7` constraint; see [6.21.4 release notes](https://github.com/py-pdf/pypdf/releases/tag/6.21.4). |

After the update, `make dependency-audit` and the production frontend audit
(`npm audit --omit=dev --audit-level=high --prefix web`) reported zero known
vulnerabilities. A separate, broader `npm audit` of frontend build/test
development dependencies reports 16 findings (11 moderate, 5 high); CI's
production audit intentionally omits those packages. No frontend dependency
changes are included in this focused PR. The current exact `vitest` pin
(`5.0.1`) requires an out-of-range update to `5.1.1` for its reported finding;
remaining development-tool findings should be handled in a separately tested
dependency update rather than hidden by the production-only audit.

## What the transaction proves

| Claim | Evidence and source | Qualification |
| --- | --- | --- |
| The application processes supported text input and creates an order through its authenticated HTTP intake. | `scripts/phase12_demo.py` submits multipart data to `/v1/orchestration/intakes`; `src/opsflow/api/orchestration.py`; `src/opsflow/documents/processor.py`; `src/opsflow/documents/text.py`; integration coverage in `tests/integration/test_phase7_orchestration_api.py` and `tests/integration/test_phase7_pipeline.py`. | The capture is API intake, not a Gmail flow or a customer upload UI. This transaction uses one synthetic text document. |
| Extraction is structured and has source-linked evidence. | `scripts/phase12_demo.py` supplies fixed fields and quotes for the fixture; `src/opsflow/extraction/extractor.py` verifies each quote against the exact canonical source segment. | Values came from deterministic `FakeProvider` output. This is not model inference or an extraction-quality result. |
| Business validation is deterministic and separate from extraction. | `src/opsflow/review/composition.py` defines the synthetic trusted customer/product data and a 5% price tolerance; `src/opsflow/validation/engine.py` emits `PRICE_OUTSIDE_TOLERANCE`. | The fixture's $15.00 unit price differs from trusted `SKU-001` catalogue price $10.00 by $5.00, above the $0.50 allowance. These are fictional sandbox values. |
| A reviewer can correct the untrusted draft and ask the server to revalidate it. | `web/src/components/review/ReviewDraftForm.tsx`; `src/opsflow/application/review_revalidation.py`; existing tests in `tests/integration/test_phase6_revalidation.py`. The capture records a change to $10.00 and the successful revalidation state. | This demonstrates one correction path, not a broad usability evaluation. The reviewer role uses local development bearer authentication. |
| A distinct approver can authorize the ready order and leave an audit record. | `src/opsflow/review/auth.py`; `src/opsflow/application/review_commands.py`; `src/opsflow/application/review_reads.py`; tests in `tests/integration/test_phase6_commands.py` and `tests/integration/test_phase6_persistence.py`. | The resulting state is `APPROVED`. Approval is not evidence of Odoo/HubSpot synchronization, customer delivery, or production identity controls. |

The demo provider refuses any canonical source that differs from the checked-in
fixture. Demo startup refuses configured provider, integration, or database
environment variables, explicitly builds `Settings` without `.env` loading,
sets all external adapters to `None`, and binds the API to loopback. The seed
command uses the application's authenticated HTTP intake; it does not insert
orders directly into the database or bypass review authorization.

## Captured application views

All screenshots are unretouched browser captures of the running application.
The data, customer name, identifiers, timestamps, and order are synthetic.

| Asset | View | Source/test mapping |
| --- | --- | --- |
| [`01-review-queue.png`](../../docs/assets/phase12-synthetic-fakeprovider/01-review-queue.png) | Local review queue with the intake waiting for review. | `web/src/pages/ReviewQueuePage.tsx`; `web/src/pages/ReviewQueuePage.test.tsx`. |
| [`02-validation-exception.png`](../../docs/assets/phase12-synthetic-fakeprovider/02-validation-exception.png) | Existing detail page scrolled to the deterministic exception and reference data. | `web/src/pages/ReviewDetailPage.tsx`; `src/opsflow/validation/engine.py`. |
| [`03-extraction-evidence.png`](../../docs/assets/phase12-synthetic-fakeprovider/03-extraction-evidence.png) | Original structured values and source-grounded quotes. | `web/src/components/review/ReviewEvidencePanel.tsx`; `src/opsflow/extraction/extractor.py`. |
| [`04-deterministic-validation.png`](../../docs/assets/phase12-synthetic-fakeprovider/04-deterministic-validation.png) | The catalogue-price exception generated by backend rules. | `web/src/pages/ReviewDetailPage.tsx`; `tests/integration/test_phase5_application.py`. |
| [`05-human-correction.png`](../../docs/assets/phase12-synthetic-fakeprovider/05-human-correction.png) | Reviewer edits the candidate unit price to $10.00 before submission. | `web/src/components/review/ReviewDraftForm.tsx`. |
| [`06-revalidation-passed.png`](../../docs/assets/phase12-synthetic-fakeprovider/06-revalidation-passed.png) | Backend success status after save and revalidation. | `src/opsflow/application/review_revalidation.py`; `tests/integration/test_phase6_revalidation.py`. |
| [`07-corrected-review-draft.png`](../../docs/assets/phase12-synthetic-fakeprovider/07-corrected-review-draft.png) | Persisted human-reviewed line value after revalidation. | `web/src/pages/ReviewDetailPage.tsx`; `src/opsflow/application/review_revalidation.py`. |
| [`08-approval-outcome.png`](../../docs/assets/phase12-synthetic-fakeprovider/08-approval-outcome.png) | Server result with state `APPROVED`. | `web/src/components/review/ReviewActions.tsx`; `src/opsflow/application/review_commands.py`. |
| [`09-recorded-audit-history.png`](../../docs/assets/phase12-synthetic-fakeprovider/09-recorded-audit-history.png) | Persisted intake, extraction, validation, reviewer revision, revalidation, and distinct approval events. | `web/src/components/review/ReviewHistoryPanel.tsx`; `tests/integration/test_phase6_persistence.py`. |

The Playwright capture script asserts the exception, correction, revalidation,
approval, audit event, and absence of browser console/page errors:
[`scripts/phase12_capture/capture.mjs`](../../scripts/phase12_capture/capture.mjs).
It uses the existing UI routes and does not create mock screens.

## Recording

- [`opsflow-local-synthetic-review.mp4`](../../docs/assets/phase12-synthetic-fakeprovider/opsflow-local-synthetic-review.mp4) is H.264 video with an embedded `mov_text` caption track, title and synthetic-provider metadata.
- [`opsflow-local-synthetic-review.webm`](../../docs/assets/phase12-synthetic-fakeprovider/opsflow-local-synthetic-review.webm) is the original Chromium recording.
- [`opsflow-local-synthetic-review.srt`](../../docs/assets/phase12-synthetic-fakeprovider/opsflow-local-synthetic-review.srt) contains the same captions separately.

The silent recording shows the local queue, the existing order detail and
source evidence, deterministic exception, reviewer edit and revalidation,
separate approver session, approval result, and audit inspection. The MP4
duration, 1440×900 dimensions, H.264 stream, subtitle stream, and metadata were
verified with `ffprobe`. The SRT explicitly identifies FakeProvider, synthetic
input, API intake, and integrations not exercised.

## Frozen Phase 11 evaluation evidence

The existing provider-free evaluation result is
[`docs/evaluation/reference/phase-11-provider-free-baseline.md`](../evaluation/reference/phase-11-provider-free-baseline.md), with machine-readable
results in
[`docs/evaluation/reference/phase-11-provider-free-baseline.json`](../evaluation/reference/phase-11-provider-free-baseline.json).
It is run `a50b6256-9f56-462d-8f12-5e01651e3c85`, corpus `3.0.0`, at source
SHA `7b67e6e32a2c7f7c44894dcf38eb68968ce1195b`. Its 36 of 36 cases passed and
all five release gates passed. Recorded routing and safety evidence includes
14/14 full routing, 0/13 invalid pass-through, 4/4 duplicate blocking, 3/3
retry recovery, 4/4 malformed/security safety, and 14/14 execution safety.

This frozen provider-free result is not live model accuracy: extraction
quality is `NOT_APPLICABLE`, the run made zero Gemini calls, and token usage,
model cost, live latency, customer outcomes, and production reliability were
not established. This local one-order rehearsal is not a new benchmark run and
adds no quantitative evaluation claim.

## Architecture decisions and trade-offs worth explaining

- The provider returns a structured interpretation; its values remain
  untrusted until Python validates them against trusted reference data and
  deterministic policy.
- Each displayed evidence quote is checked against the canonical source
  segment. The review UI keeps the original extraction, editable candidate,
  trusted persisted order, and audit history distinct.
- Server-resolved operator roles and version validators protect review
  commands. A reviewer cannot perform the approver's action in this scenario.
- The capture exercises text intake because it is simple to reproduce and
  keeps the source synthetic and inspectable. It does not prove OCR or PDF
  visual rendering.
- Python owns order state, validation, review decisions, and audit events. An
  external orchestrator or business-platform side effect is outside this
  run's scope.

## Reproduction

From a clean checkout on a machine with Docker, Python 3.12/`uv`, Node 24/npm,
and Playwright Chromium:

```sh
docker compose -p opsflow-phase2-demo up -d postgres
docker exec opsflow-phase2-demo-postgres-1 createdb -U opsflow opsflow_phase12_demo
OPSFLOW_DATABASE_URL='postgresql+asyncpg://opsflow:opsflow@127.0.0.1:5432/opsflow_phase12_demo' uv run alembic upgrade head
uv run python scripts/phase12_demo.py --state /tmp/opsflow-phase12-demo/state.json init
```

In separate terminals, start the API and web app, then seed through HTTP:

```sh
uv run python scripts/phase12_demo.py --state /tmp/opsflow-phase12-demo/state.json serve
npm --prefix web run dev -- --host 127.0.0.1 --port 5173 --strictPort
uv run python scripts/phase12_demo.py --state /tmp/opsflow-phase12-demo/state.json seed
```

Install the isolated browser-capture dependency and run the authenticated
workflow:

```sh
npm ci --prefix scripts/phase12_capture
npm exec --prefix scripts/phase12_capture -- playwright install chromium
npm run capture --prefix scripts/phase12_capture -- /tmp/opsflow-phase12-demo/state.json
```

The capture script creates the original WebM and PNGs. To recreate the
captioned MP4, with `ffmpeg` installed, run:

```sh
ffmpeg -hide_banner -loglevel error -y \
  -i docs/assets/phase12-synthetic-fakeprovider/opsflow-local-synthetic-review.webm \
  -i docs/assets/phase12-synthetic-fakeprovider/opsflow-local-synthetic-review.srt \
  -map 0:v:0 -map 1:0 -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p \
  -c:s mov_text \
  -metadata title='OpsFlow AI synthetic local review workflow' \
  -metadata comment='Synthetic input and deterministic FakeProvider only. No live Gemini, Gmail, Odoo, HubSpot, or Slack calls.' \
  -movflags +faststart -shortest \
  docs/assets/phase12-synthetic-fakeprovider/opsflow-local-synthetic-review.mp4
```

`init` creates random local-only operator and intake credentials in a `0600`
state file under a `0700` directory. It never prints the credential values.
The state file is not part of the repository. A fresh database is required to
replay the whole transaction; `seed` refuses to create a second one in the
same state. To stop and remove only this isolated database volume after the
capture, use `docker compose -p opsflow-phase2-demo down --volumes`.

## Limitations and public-use disposition

- One fictional text document and one deterministic mismatch exercise the
  review path. No live model output or population-level result is shown.
- No Gmail intake, customer upload screen, OCR, Gmail/Slack notification,
  Odoo/HubSpot write, n8n workflow, or production identity service is proved.
- Real-provider accuracy, latency, token usage, and cost remain unmeasured.
- The OpsFlow repository has no root `LICENSE` and no separate media license
  decision. These synthetic captures contain no third-party illustration,
  customer record, personal identifier, or real credential, but their presence
  in this review PR does not select a project or media license.
- The repository's `.github/workflows/ci.yml` uses Gitleaks for full Git
  history. The PR CI result remains the authoritative secret scan for the
  committed evidence.
