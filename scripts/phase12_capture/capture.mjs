import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm } from "node:fs/promises";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { chromium } from "playwright";

const statePath = process.argv[2];
const appUrl = process.env.PHASE12_DEMO_WEB_URL ?? "http://127.0.0.1:5173";
const outputPath = resolve(
  process.env.PHASE12_DEMO_OUTPUT ?? "../../docs/assets/phase12-synthetic-fakeprovider",
);

if (!statePath) {
  throw new Error("Usage: npm run capture -- /private/path/to/state.json");
}

const state = JSON.parse(await readFile(statePath, "utf8"));
assert.ok(state.order_id, "Submit the synthetic fixture before capturing the application.");
assert.ok(state.reviewer_token && state.approver_token, "Local demo credentials are missing.");
await mkdir(outputPath, { recursive: true });
const rawVideoDirectory = await mkdtemp(join(tmpdir(), "opsflow-phase12-capture-"));

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
  recordVideo: {
    dir: rawVideoDirectory,
    size: { width: 1440, height: 900 },
  },
});
const page = await context.newPage();
const pageErrors = [];
const consoleErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("console", (message) => {
  if (message.type() === "error") consoleErrors.push(message.text());
});
const video = page.video();
const orderUrl = `${appUrl.replace(/\/$/, "")}/review/${encodeURIComponent(state.order_id)}`;

async function connect(token) {
  await page.goto(`${appUrl.replace(/\/$/, "")}/review`, { waitUntil: "networkidle" });
  const accessInput = page.getByLabel("Development bearer credential");
  await accessInput.fill(token);
  await page.getByRole("button", { name: "Connect" }).click();
  await page.getByRole("heading", { name: "Review queue" }).waitFor();
}

await connect(state.reviewer_token);
await page.waitForTimeout(6500);
await page.screenshot({ path: resolve(outputPath, "01-review-queue.png") });

await page.getByRole("link", { name: `Open ${state.order_id}` }).click();
await page.getByRole("heading", { name: `Review case ${state.order_id}` }).waitFor();
await page.getByText("PRICE_OUTSIDE_TOLERANCE", { exact: true }).waitFor();
await page.waitForTimeout(6500);
const issuePanel = page.locator('[aria-labelledby="validation-heading"]');
await issuePanel.scrollIntoViewIfNeeded();
await page.screenshot({ path: resolve(outputPath, "02-validation-exception.png") });
await issuePanel.screenshot({ path: resolve(outputPath, "04-deterministic-validation.png") });
await page.waitForTimeout(6500);

await page.locator(".review-evidence-panel").screenshot({
  path: resolve(outputPath, "03-extraction-evidence.png"),
});
await page.waitForTimeout(6500);

const priceInput = page.locator("#review-line-0-submitted-price");
await priceInput.fill("10.00");
await page.locator(".review-draft-form-panel").screenshot({
  path: resolve(outputPath, "05-human-correction.png"),
});
await page.waitForTimeout(4500);
await page.getByRole("button", { name: "Save & revalidate" }).click();
await page.getByText(
  "Deterministic revalidation passed; the order is ready for approval.",
  { exact: true },
).waitFor();
const persistedPrice = await page
  .locator('[aria-labelledby="effective-heading"] tbody tr td:nth-child(4)')
  .textContent();
assert.equal(persistedPrice?.trim(), "10");
await page.waitForTimeout(6500);
await page.locator(".review-form-success").screenshot({
  path: resolve(outputPath, "06-revalidation-passed.png"),
});
await page.locator('[aria-labelledby="effective-heading"]').screenshot({
  path: resolve(outputPath, "07-corrected-review-draft.png"),
});

await page.getByRole("button", { name: "Sign out" }).click();
await connect(state.approver_token);
await page.getByRole("link", { name: `Open ${state.order_id}` }).click();
await page.getByRole("heading", { name: `Review case ${state.order_id}` }).waitFor();
await page.getByRole("button", { name: "Approve order" }).waitFor();
await page.waitForTimeout(5000);
await page.getByRole("button", { name: "Approve order" }).click();
await page.getByRole("heading", { name: "Review command completed" }).waitFor();
await page.getByText("APPROVED", { exact: true }).waitFor();
await page.waitForTimeout(8000);
await page.locator(".review-command-result").screenshot({
  path: resolve(outputPath, "08-approval-outcome.png"),
});

// Approved orders leave the queue; inspect the existing detail route in the
// same authenticated SPA session to verify its recorded audit history.
await page.locator(".review-command-result").getByRole("link", { name: "Back to review queue" }).click();
await page.getByRole("heading", { name: "Review queue" }).waitFor();
await page.evaluate((url) => {
  window.history.pushState({}, "", url);
  window.dispatchEvent(new PopStateEvent("popstate"));
}, new URL(orderUrl).pathname);
await page.getByRole("heading", { name: `Review case ${state.order_id}` }).waitFor();
await page.getByText("ORDER_APPROVED", { exact: true }).waitFor();
const historyPanels = page.locator(".review-history-list");
await historyPanels.last().screenshot({ path: resolve(outputPath, "09-recorded-audit-history.png") });
await page.waitForTimeout(8000);

await context.close();
await video.saveAs(resolve(outputPath, "opsflow-local-synthetic-review.webm"));
await browser.close();
await rm(rawVideoDirectory, { recursive: true, force: true });
assert.deepEqual(pageErrors, [], "The browser reported uncaught application errors.");
assert.deepEqual(consoleErrors, [], "The browser console reported errors.");

console.log("Capture assertions passed.");
console.log(`Synthetic order: ${state.order_id}`);
console.log("Provider: deterministic FakeProvider fixture; no live provider calls.");
console.log(`Screenshots and browser recording: ${outputPath}`);
