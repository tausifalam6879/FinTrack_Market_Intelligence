import { expect, test } from "@playwright/test";
import fs from "node:fs";

const snapshot = JSON.parse(fs.readFileSync(new URL("../src/data/bundledMarketSnapshot.json", import.meta.url), "utf8"));

const analysisFor = (symbol) => snapshot.analysis?.[symbol] || {
  ...snapshot.analysis["^NSEI"], symbol, name: symbol, dataAsOf: new Date().toISOString()
};

async function mockMarketApi(page) {
  await page.route("**/market/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const json = (body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/market/overview")) return json(snapshot.overview);
    if (path.endsWith("/market/currencies")) return json(snapshot.currencies);
    if (path.endsWith("/market/news-feed")) return json(snapshot.newsFeed);
    if (path.endsWith("/market/operations-status")) return json({
      status: "ready",
      telemetry: { privacy: "aggregate-only; no questions, symbols, IP addresses or personal data stored", api: { totalRequests: 12, serverErrors: 0, errorRatePercent: 0, averageLatencyMs: 42, p95LatencyMs: 90, routes: [] }, languageModel: { acceptedRatePercent: 100, fallbackRatePercent: 0 } },
      dependencies: { database: { backend: "postgresql", status: "ready" }, languageModel: { provider: "gemini", status: "configured" } }
    });
    if (path.endsWith("/market/compare")) {
      const payload = request.postDataJSON();
      return json({ symbols: payload.symbols, items: payload.symbols.map(analysisFor), errors: [], partial: false, execution: "parallel-spring-webclient" });
    }
    if (path.endsWith("/market/analysis")) return json(analysisFor(url.searchParams.get("symbol") || "^NSEI"));
    if (path.endsWith("/market/model-status")) return json({
      servingMode: "runtime_fallback", predictionMonitoring: { totalStored: 3, evaluated: 2, observedAccuracy: 50, records: [] },
      dataOperations: { storedBars: 252, freshness: "fresh", storage: { durableAcrossDeploys: true, schema: { currentVersion: 4, expectedVersion: 4 } } },
      driftMonitoring: { status: "collecting_evidence", features: [] }, retrainingPolicy: { automaticRetraining: false, decision: "collecting_evidence" }
    });
    if (path.endsWith("/market/experiments")) return json({ runs: [], count: 0, configuration: { experimentName: "FinTrack", backend: "MLflow" } });
    if (path.endsWith("/market/agent")) return json({
      answer: "Probability up model ke available evidence mein agle session ke upward scenario ka estimate hai. Yeh guarantee nahi hai.",
      llmStatus: "connected", llmAnswerAccepted: true, agentPlan: { intents: ["model_and_technical_analysis"] }, toolTrace: [], citations: []
    });
    if (path.endsWith("/market/companies")) return json({ items: [] });
    if (path.endsWith("/market/documents")) return json({ items: [], preparation: { supported: false } });
    return json({});
  });
}

test.beforeEach(async ({ page }) => {
  await mockMarketApi(page);
  await page.goto("/");
});

test("research, browser watchlist, batch comparison and PDF action work together", async ({ page }) => {
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  await expect(page.getByRole("heading", { name: "Research an index or company" })).toBeVisible();

  await page.getByRole("button", { name: "+ Save company" }).click();
  await page.getByRole("button", { name: "Sensex", exact: true }).click();
  await expect(page.locator(".analysis-hero")).toContainText("Sensex");
  await page.getByRole("button", { name: "+ Save company" }).click();

  await page.getByRole("button", { name: /Compare saved \(2\)/ }).click();
  await page.getByRole("button", { name: "Compare", exact: true }).first().click();
  await page.getByRole("button", { name: "Compare", exact: true }).first().click();
  await expect(page.locator(".comparison-table tbody tr")).toHaveCount(2);
  await expect(page.locator(".comparison-table")).toContainText("Probability up");

  await page.evaluate(() => { window.print = () => { window.__fintrackPrinted = true; }; });
  await page.getByRole("button", { name: "Print / Save PDF" }).click();
  await expect.poll(() => page.evaluate(() => window.__fintrackPrinted)).toBe(true);
});

test("metric explanation is grounded and concise", async ({ page }) => {
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  await page.getByRole("button", { name: "Explain Probability up" }).click();
  await expect(page.locator(".agent-panel")).toHaveClass(/open/);
  await expect(page.locator(".chat-message.assistant")).toContainText("upward scenario");
  await expect(page.locator(".chat-message.assistant small")).toHaveText("Gemini grounded");
});

test("operations observability is visible in MLOps without page overflow", async ({ page }) => {
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  await page.getByRole("button", { name: "Model & MLOps" }).click();
  await expect(page.getByText("Latency, failures and Gemini fallback evidence")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});
