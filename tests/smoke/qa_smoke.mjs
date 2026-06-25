#!/usr/bin/env node
// QA post-deploy smoke test. Standalone Playwright script that loads a target
// URL in a headless chromium, waits for the SPA to finish bootstrapping, and
// asserts there are no unexpected console errors or network failures.
//
// Why this exists: on 2026-06-01 the QA bring-up "passed" three layers of
// HTTP-level checks (curl /healthz 200, curl / 200, curl /api/v1/account 401)
// but the SPA was actually broken in browsers — /assets/*.js was served as
// text/html because of a stale import-time check in webapp/main.py + a
// Cloudflare cache hit. A real browser fetch of subresources catches this
// class of bug that curl can't.
//
// Usage (manual):
//   npm i -g playwright && npx playwright install chromium    # one-time
//   node tests/smoke/qa_smoke.mjs                              # defaults to QA
//   node tests/smoke/qa_smoke.mjs --url=https://qa.qongsystems.com/
//   node tests/smoke/qa_smoke.mjs --url=http://localhost:8000/ # local stack
//
// Usage (CI — when .github/workflows/deploy-qa.yml lands):
//   - name: Smoke test
//     run: |
//       npm i @playwright/test
//       npx playwright install --with-deps chromium
//       node tests/smoke/qa_smoke.mjs --url=https://qa.qongsystems.com/
//
// Exit codes:
//   0 — all assertions passed
//   1 — assertion failed (console error, bad MIME, failed request, etc.)
//   2 — runtime error (couldn't reach target, browser failed to launch, etc.)

import { chromium } from "playwright";

const args = Object.fromEntries(
  process.argv.slice(2).map((a) => {
    const [k, ...v] = a.replace(/^--/, "").split("=");
    return [k, v.join("=") || true];
  })
);
const targetUrl = args.url || "https://qa.qongsystems.com/";

// Console messages we *expect* and shouldn't fail on. The /api/v1/account 401
// is what the SPA sends to detect "is there a session?" — for anonymous users
// it's correct behavior, not a bug.
const EXPECTED_PATTERNS = [/\/api\/v1\/account.*401/];

const log = (...m) => console.log("[smoke]", ...m);
const fail = (msg) => {
  console.error("[smoke] FAIL:", msg);
  process.exit(1);
};

const browser = await chromium.launch({ headless: true }).catch((e) => {
  console.error("[smoke] couldn't launch chromium:", e.message);
  process.exit(2);
});

try {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();

  const consoleErrors = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  const failedRequests = [];
  page.on("requestfailed", (req) => {
    failedRequests.push(`${req.method()} ${req.url()} — ${req.failure()?.errorText}`);
  });

  const badMime = [];
  page.on("response", (resp) => {
    const url = resp.url();
    const ct = (resp.headers()["content-type"] || "").toLowerCase();
    if (url.endsWith(".js") && !ct.includes("javascript") && !ct.includes("module")) {
      badMime.push(`${url} → ${ct}`);
    }
    if (url.endsWith(".css") && !ct.includes("css")) {
      badMime.push(`${url} → ${ct}`);
    }
  });

  log(`navigating to ${targetUrl}`);
  const resp = await page.goto(targetUrl, { waitUntil: "networkidle", timeout: 30_000 });
  if (!resp) fail(`no response object for ${targetUrl}`);
  if (resp.status() >= 400) fail(`${targetUrl} returned HTTP ${resp.status()}`);
  log(`HTTP ${resp.status()} — page loaded`);

  // Give the SPA a moment to make its initial API calls + render.
  await page.waitForTimeout(2000);

  const unexpected = consoleErrors.filter(
    (e) => !EXPECTED_PATTERNS.some((p) => p.test(e))
  );

  if (badMime.length) {
    fail(`bad asset MIME types:\n  - ${badMime.join("\n  - ")}`);
  }
  if (failedRequests.length) {
    fail(`failed network requests:\n  - ${failedRequests.join("\n  - ")}`);
  }
  if (unexpected.length) {
    fail(`unexpected console errors:\n  - ${unexpected.join("\n  - ")}`);
  }

  // Light sanity check on the rendered DOM — the page title should be set
  // (proves the SPA actually mounted, not just an empty index.html shell).
  const title = await page.title();
  if (!title || title === "") fail("page has no <title> after load");
  log(`title: ${title}`);

  // Check the body has *some* content (catches the "blank page, no errors" case).
  const bodyText = (await page.locator("body").innerText()).trim();
  if (bodyText.length < 50) fail(`body has only ${bodyText.length} chars — SPA likely didn't render`);
  log(`body: ${bodyText.length} chars of visible text`);

  log("OK — all assertions passed");
  process.exit(0);
} finally {
  await browser.close();
}
