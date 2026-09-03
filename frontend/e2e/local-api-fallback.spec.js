import { expect, test } from "@playwright/test";
import fs from "node:fs";

const snapshot = JSON.parse(fs.readFileSync(new URL("../src/data/bundledMarketSnapshot.json", import.meta.url), "utf8"));
const hostedGateway = "https://fintrack-market-gateway.onrender.com";

test("company discovery falls back to the hosted read-only API when local services are offline", async ({ page }) => {
  await page.route("http://localhost:8081/market/**", (route) => route.abort("connectionrefused"));
  await page.route(`${hostedGateway}/market/**`, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/market/companies")) return json({
      items: [{ symbol: "CSCO", name: "Cisco Systems, Inc.", exchange: "NASDAQ", sector: "Technology" }],
      count: 1,
      mode: "live"
    });
    if (path.endsWith("/market/analysis")) return json({ ...snapshot.analysis["^NSEI"], symbol: "CSCO", name: "Cisco Systems, Inc." });
    if (path.endsWith("/market/overview")) return json(snapshot.overview);
    if (path.endsWith("/market/model-status")) return json({});
    if (path.endsWith("/market/experiments")) return json({ runs: [], count: 0 });
    if (path.endsWith("/market/peer-comparison")) return json({ data: null });
    if (path.endsWith("/market/company")) return json({ data: null });
    if (path.endsWith("/market/documents")) return json({ items: [], preparation: { supported: false } });
    if (path.endsWith("/market/operations-status")) return json({ status: "ready" });
    return json({});
  });

  await page.goto("/");
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  const search = page.getByRole("textbox", { name: "Company name or market ticker" });
  await search.fill("cis");
  await page.getByRole("button", { name: "Run research" }).click();

  await expect(search).toHaveValue("CSCO");
  await expect(page.getByText("Resolved to")).toBeVisible();
  await expect(page.getByText("Cisco Systems, Inc.").first()).toBeVisible();
  await expect(page.locator(".notice.error")).toHaveCount(0);
});

test("an explicit NSE or BSE ticker shows research before slow monitoring finishes", async ({ page }) => {
  let companyDirectoryRequests = 0;
  await page.route("http://localhost:8081/market/**", (route) => route.abort("connectionrefused"));
  await page.route(`${hostedGateway}/market/**`, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const json = (body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    if (path.endsWith("/market/companies")) {
      companyDirectoryRequests += 1;
      await new Promise((resolve) => setTimeout(resolve, 4_000));
      return json({ items: [{ symbol: "SPICEJET.BO", name: "SpiceJet Limited", exchange: "BSE" }] });
    }
    if (path.endsWith("/market/analysis")) {
      const symbol = url.searchParams.get("symbol") || "^NSEI";
      return json({ ...snapshot.analysis["^NSEI"], symbol, name: symbol });
    }
    if (path.endsWith("/market/model-status")) {
      await new Promise((resolve) => setTimeout(resolve, 4_000));
      return json({ servingMode: "runtime_fallback" });
    }
    if (path.endsWith("/market/overview")) return json(snapshot.overview);
    if (path.endsWith("/market/experiments")) return json({ runs: [], count: 0 });
    if (path.endsWith("/market/peer-comparison")) return json({ data: null });
    if (path.endsWith("/market/company")) return json({ data: null });
    if (path.endsWith("/market/documents")) return json({ items: [], preparation: { supported: false } });
    if (path.endsWith("/market/operations-status")) return json({ status: "ready" });
    return json({});
  });

  await page.goto("/");
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  const search = page.getByRole("textbox", { name: "Company name or market ticker" });
  await search.fill("SPICEJET.BO");
  await page.getByRole("button", { name: "Run research" }).click();

  await expect(page.locator(".analysis-hero")).toContainText("SPICEJET.BO");
  await expect(page.getByRole("button", { name: "Run research" })).toBeEnabled();
  await expect(page.getByText("Resolved to")).toBeVisible();
  await expect(page.getByText("SpiceJet Limited").first()).toBeVisible();
  expect(companyDirectoryRequests).toBe(1);
});
