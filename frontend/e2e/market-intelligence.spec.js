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
      dependencies: { database: { backend: "mysql", status: "ready" }, languageModel: { provider: "gemini", status: "configured" } }
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
    if (path.endsWith("/market/agent")) {
      const preferLocal = Boolean(request.postDataJSON()?.preferLocal);
      return json({
        answer: "Probability up model ke available evidence mein agle session ke upward scenario ka estimate hai. Yeh guarantee nahi hai.",
        llmStatus: "connected", llmAnswerAccepted: true, llmProvider: preferLocal ? "ollama" : "gemini", agentPlan: { intents: ["model_and_technical_analysis"] }, toolTrace: [], citations: []
      });
    }
    if (path.endsWith("/market/companies")) return json({ items: [] });
    if (path.endsWith("/market/documents")) return json({ items: [], preparation: { supported: false } });
    return json({});
  });
}

test.beforeEach(async ({ page }) => {
  await mockMarketApi(page);
  await page.goto("/");
});

test("portfolio holdings persist, update without duplication and can be removed", async ({ page }) => {
  await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Reliance',exact:true}).click();
  await page.getByRole('button',{name:'My portfolio',exact:true}).click();
  const panel=page.getByRole('region',{name:'My portfolio',exact:true});
  await panel.getByLabel('Quantity',{exact:true}).fill('10');
  await panel.getByLabel('Average buy price',{exact:true}).fill('1200');
  await panel.getByRole('button',{name:'Save holding'}).click();
  await expect(panel.getByRole('button',{name:'Remove holding RELIANCE.NS'})).toBeVisible();
  await panel.getByLabel('Quantity',{exact:true}).fill('20');
  await panel.getByRole('button',{name:'Save holding'}).click();
  await expect(panel.getByRole('button',{name:'Remove holding RELIANCE.NS',exact:true})).toHaveCount(1);
  await expect(panel).toContainText('What-if price scenario');
  await panel.getByLabel('Price change (%)',{exact:true}).fill('-10');
  await expect(panel).toContainText('Scenario value:');
  await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem('fintrack.portfolio.v1'))[0].quantity)).toBe(20);
  await page.reload();
  await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'My portfolio',exact:true}).click();
  await expect(panel.getByRole('button',{name:'Remove holding RELIANCE.NS'})).toBeVisible();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await panel.getByRole('button',{name:'Remove holding RELIANCE.NS'}).click();
  await expect(panel).toContainText('No holdings saved yet');
});

test('smart alert rules evaluate, reject duplicates and can be removed',async({page})=>{
  await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Smart alerts',exact:true}).click();
  const panel=page.getByRole('region',{name:'Smart research alerts'});
  await panel.getByLabel('Alert threshold',{exact:true}).fill('999999');
  await panel.getByRole('button',{name:'Add alert rule'}).click();
  await expect(panel).toContainText('Condition met');
  await panel.getByRole('button',{name:'Add alert rule'}).click();
  await expect(panel).toContainText('This rule already exists');
  await expect(panel.getByRole('button',{name:/Remove alert/})).toHaveCount(1);
  await panel.getByRole('button',{name:/Remove alert/}).click();
  await expect(panel.getByRole('button',{name:/Remove alert/})).toHaveCount(0);
});

test('event study shows returned windows without inventing missing benchmark data',async({page})=>{
  await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  await page.route('**/market/event-impact?*',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({eventDate:'2024-02-01',baselineDate:'2024-01-31',baselinePrice:100,benchmarkSymbol:null,windows:[{sessions:1,status:'available',date:'2024-02-01',price:110,returnPercent:10,benchmarkReturnPercent:null,excessReturnPoints:null}],method:'Matched dates',limitations:'No causal claim'})}));
  const panel=page.getByRole('region',{name:'Event impact analysis'});
  await panel.getByLabel('Event date',{exact:true}).fill('2024-02-01');
  await panel.getByRole('button',{name:'Analyze event window'}).click();
  await expect(panel).toContainText('Benchmark: Unavailable');
  await expect(panel).toContainText('10%');
  await panel.getByLabel('Event date',{exact:true}).fill('2024-03-01');
  await expect(panel).not.toContainText('Baseline session:');
});

test('structured report explains missing evidence and prints only the report',async({page})=>{
  await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Research report',exact:true}).click();
  const report=page.getByRole('region',{name:'Structured research report'});
  await expect(report.getByRole('heading',{name:'13. Sources and dates'})).toBeVisible();
  await expect(report).toContainText('Company profile unavailable');
  await report.getByRole('button',{name:'Generate AI explanation'}).click();
  await expect(report).toContainText('Explanation provider: gemini');
  await page.evaluate(()=>{window.print=()=>{};});
  await report.getByRole('button',{name:'Print / Save report PDF'}).click();
  await page.emulateMedia({media:'print'});
  await expect(page.locator('#root')).toBeHidden();
  await expect(page.locator('.fintrack-report-print-copy')).toBeVisible();
  await expect(page.locator('.fintrack-report-print-copy button')).toHaveCount(0);
  await page.evaluate(()=>window.dispatchEvent(new Event('afterprint')));
  await expect(page.locator('.fintrack-report-print-copy')).toHaveCount(0);
});

test('backtest displays returned metrics and recovers from API errors',async({page})=>{
  await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  const panel=page.getByRole('region',{name:'Historical backtest'});
  await page.route('**/market/backtest?*',r=>r.fulfill({status:503,body:'unavailable'}));
  await panel.getByRole('button',{name:'Run backtest'}).click();
  await expect(panel.getByRole('alert')).toContainText('Backtest unavailable');
  await page.route('**/market/backtest?*',r=>r.fulfill({status:200,contentType:'application/json',body:JSON.stringify({symbol:'^NSEI',model:'Fixed logistic regression',observations:80,from:'2025-01-01',through:'2025-05-01',strategyReturnPercent:4,benchmarkReturnPercent:6,maximumDrawdownPercent:-3,sharpeZeroRiskFree:0.4,accuracyPercent:52,exposurePercent:40,audit:[],method:'Chronological training',limitations:'Research simulation'})}));
  await panel.getByRole('button',{name:'Run backtest'}).click();
  await expect(panel).toContainText('80 evaluated intervals');
  await expect(panel).toContainText('Fixed logistic regression');
});

test("market pulse opens with a clean live ribbon and an inspectable daily chart", async ({ page }) => {
  await expect(page.locator(".brand-mark")).toHaveAttribute("src", "./fintrack-mark.svg");
  await expect(page.locator(".public-chip")).toBeVisible();
  const ribbon = page.getByRole("region", { name: "Live rotating market quotes" });
  await expect(ribbon).toBeVisible();
  await expect(ribbon.getByRole("button", { name: /Nifty 50/ })).toBeVisible();
  if (page.viewportSize().width > 540) await expect(page.locator(".navbar-quote")).toBeVisible();
  else await expect(page.locator(".navbar-quote")).toBeHidden();
  await expect(page.getByLabel("Verified gold market move")).toContainText("GOLD MOVE");
  await expect(page.getByLabel("Verified US dollar to Indian rupee rate")).toContainText("USD/INR");
  await expect(page.locator(".topbar .topbar-tabs")).toBeVisible();
  await expect(page.locator("main > .tabbar")).toHaveCount(0);

  await page.getByRole("button", { name: "Open Market Pulse menu" }).click();
  const marketNavigation = page.getByRole("navigation", { name: "Market Pulse navigation" });
  await expect(marketNavigation).toBeVisible();
  await expect(marketNavigation.getByRole("link", { name: /Market statistics/ })).toBeVisible();
  await page.locator(".market-side-drawer").getByRole("button", { name: "Close Market Pulse menu" }).click();

  const chart = page.getByRole("img", { name: /NSEI daily closing history/ });
  await expect(chart).toBeVisible();
  await expect(page.getByRole("heading", { name: "Market statistics" })).toBeVisible();
  await expect(page.locator(".market-statistics-panel")).toContainText("Advances");
  await page.getByRole("button", { name: "1M", exact: true }).click();
  await chart.hover({ position: { x: 120, y: 100 } });
  await expect(page.locator(".history-tooltip")).toContainText("NSEI");

  await page.locator("#risk-alerts").scrollIntoViewIfNeeded();
  const stickyPositions = await page.evaluate(() => {
    const topbar = document.querySelector(".topbar").getBoundingClientRect();
    const ribbon = document.querySelector(".market-opening-ribbon").getBoundingClientRect();
    return { topbarTop: topbar.top, topbarBottom: topbar.bottom, ribbonTop: ribbon.top, ribbonBottom: ribbon.bottom };
  });
  expect(stickyPositions.topbarTop).toBeGreaterThanOrEqual(-1);
  expect(stickyPositions.topbarTop).toBeLessThanOrEqual(1);
  expect(stickyPositions.ribbonTop).toBeGreaterThanOrEqual(stickyPositions.topbarBottom - 1);
  expect(stickyPositions.ribbonTop).toBeLessThan(stickyPositions.topbarBottom + 20);
  expect(stickyPositions.ribbonBottom).toBeGreaterThan(stickyPositions.ribbonTop);

  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("navbar keeps relevant live context across every desk", async ({ page }) => {
  const refreshedCurrency = page.waitForRequest((request) => {
    const url = new URL(request.url());
    return url.pathname.endsWith("/market/currencies") && url.searchParams.get("refresh") === "true";
  });
  await page.getByRole("button", { name: "Refresh now" }).click();
  await refreshedCurrency;

  await page.getByRole("tab", { name: /INR Currency Desk/i }).click();
  await expect(page.getByLabel("Currency desk status")).toContainText("USD/INR NOW");
  await expect(page.getByLabel("Currency desk status")).toContainText("RATE DIRECTORY");

  await page.getByRole("tab", { name: /Market News/i }).click();
  await expect(page.getByLabel("News desk status")).toContainText("HEADLINES");
  await expect(page.getByLabel("News desk status")).toContainText("FEED CHECKED");

  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  await expect(page.getByLabel("Intelligence service status")).toContainText("AI PROVIDER");
  await expect(page.getByLabel("Intelligence service status")).toContainText("Gemini");
});

test("every desk has a distinct contextual navigation drawer", async ({ page }) => {
  await page.getByRole("button", { name: "Open Market Pulse menu" }).click();
  const marketNavigation = page.getByRole("navigation", { name: "Market Pulse navigation" });
  await expect(marketNavigation).toContainText("Market statistics");
  await expect(marketNavigation).not.toContainText("Currency directory");
  await page.getByRole("button", { name: "Close Market Pulse menu" }).last().click();

  await page.getByRole("tab", { name: /INR Currency Desk/i }).click();
  await page.getByRole("button", { name: "Open Currency Desk menu" }).click();
  const currencyNavigation = page.getByRole("navigation", { name: "Currency Desk navigation" });
  await expect(currencyNavigation).toContainText("Featured currencies");
  await expect(currencyNavigation).toContainText("Currency directory");
  await expect(currencyNavigation).not.toContainText("Market statistics");
  await currencyNavigation.getByRole("link", { name: /Currency directory/ }).click();
  await expect(page.locator("#currency-directory")).toBeVisible();
  await page.getByRole("button", { name: "Open Currency Desk menu" }).click();
  await page.getByRole("navigation", { name: "Currency Desk navigation" }).getByRole("link", { name: /Search a currency/ }).click();
  await expect(page.getByRole("textbox", { name: "Search currency directory" })).toBeFocused();

  await page.getByRole("tab", { name: /Market News/i }).click();
  await page.getByRole("button", { name: "Open Market News menu" }).click();
  const newsNavigation = page.getByRole("navigation", { name: "Market News navigation" });
  await expect(newsNavigation).toContainText("Latest headlines");
  await expect(newsNavigation).toContainText("Publisher evidence");
  await expect(newsNavigation).not.toContainText("Currency directory");
  await page.getByRole("button", { name: "Close Market News menu" }).last().click();

  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  await page.getByRole("button", { name: "Open Intelligence & MLOps menu" }).click();
  const intelligenceNavigation = page.getByRole("navigation", { name: "Intelligence & MLOps navigation" });
  await expect(intelligenceNavigation).toContainText("Model operations");
  await expect(intelligenceNavigation).toContainText("Runtime monitoring");
  await expect(intelligenceNavigation).not.toContainText("Latest headlines");
  await intelligenceNavigation.getByRole("link", { name: /Runtime monitoring/ }).click();
  await expect(page.locator("#runtime-operations")).toBeVisible();
  await expect(page.getByRole("button", { name: "Advanced model details" })).toHaveClass(/active/);
  await page.getByRole("button", { name: "Open Intelligence & MLOps menu" }).click();
  await page.getByRole("navigation", { name: "Intelligence & MLOps navigation" }).getByRole("link", { name: /Ask FinTrack/ }).click();
  await expect(page.locator(".agent-panel")).toHaveClass(/open/);
});

test("an unusable currency refresh never replaces verified rates with zero", async ({ page }) => {
  await page.route("**/market/currencies?refresh=true", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      baseCurrency: "INR",
      currencies: [{ code: "USD", name: "US Dollar", country: "United States", inrValue: null, digits: 2 }],
      referenceRates: {},
      generatedAt: new Date().toISOString()
    })
  }));
  await page.getByRole("tab", { name: /INR Currency Desk/i }).click();
  await expect(page.locator(".currency-card").first()).not.toContainText("₹0.00");
  await page.getByRole("button", { name: "Refresh now" }).click();
  await expect(page.locator(".currency-card").first()).not.toContainText("₹0.00");
  await expect(page.locator(".notice.warning")).toContainText("last verified response");
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
  await page.locator(".agent-launcher").click();
  await expect(page.getByRole("button", { name: "Tell me about Nifty 50" })).toBeVisible();
  await expect(page.getByRole("button", { name: "What do probability, RSI, and the projected range mean?" })).toBeVisible();
  await page.getByRole("button", { name: "Close research agent" }).click();
  await page.getByRole("button", { name: "Explain Chance of rise" }).click();
  await expect(page.locator(".agent-panel")).toHaveClass(/open/);
  await expect(page.locator(".chat-message.assistant")).toContainText("Probability up");
  await expect(page.locator(".chat-message.assistant small")).toHaveText("Gemini · verified data");
});

test("AI provider badge follows connectivity and the provider that answered", async ({ page, context }) => {
  await page.route("**/market/operations-status", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 700));
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ status: "ready", dependencies: { languageModel: { provider: "gemini", status: "configured" } } })
    });
  });
  await page.reload();
  await context.setOffline(true);
  await page.waitForTimeout(900);
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  const serviceStatus = page.getByLabel("Intelligence service status");

  await expect(serviceStatus).toContainText("Ollama");
  await expect(serviceStatus).toContainText("offline mode");
  const offlineAgentRequest = page.waitForRequest((request) => new URL(request.url()).pathname.endsWith("/market/agent"));
  await page.locator(".agent-launcher").click();
  await page.getByRole("button", { name: "Tell me about Nifty 50" }).click();
  expect((await offlineAgentRequest).postDataJSON().preferLocal).toBe(true);
  await expect(serviceStatus).toContainText("Ollama");
  await context.setOffline(false);
  await expect(serviceStatus).toContainText("Gemini");

  let provider = "ollama";
  await page.route("**/market/agent", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify(provider === "ollama" ? {
      answer: "This answer came from the local Ollama model using verified data.",
      llmProvider: "ollama",
      llmStatus: "fallback_after_grounding",
      llmUsed: true,
      llmAnswerAccepted: true
    } : {
      answer: "The language models were unavailable, so FinTrack returned its verified tool answer.",
      llmProvider: "deterministic",
      llmStatus: "offline",
      llmUsed: false,
      llmAnswerAccepted: false
    })
  }));

  await page.getByRole("button", { name: "Tell me about Nifty 50" }).click();
  await expect(serviceStatus).toContainText("Ollama");
  await expect(serviceStatus).toContainText("answered");

  provider = "fallback";
  await page.getByRole("button", { name: "What do probability, RSI, and the projected range mean?" }).click();
  await expect(serviceStatus).toContainText("Verified fallback");
  await expect(serviceStatus).toContainText("verified");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("operations observability is visible in MLOps without page overflow", async ({ page }) => {
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  const initialSecondaryNav = await page.evaluate(() => {
    const topbar = document.querySelector(".topbar").getBoundingClientRect();
    const detailTabs = document.querySelector(".intelligence-view-tabs").getBoundingClientRect();
    return { topbarBottom: topbar.bottom, detailTabsTop: detailTabs.top };
  });
  expect(initialSecondaryNav.detailTabsTop).toBeGreaterThanOrEqual(initialSecondaryNav.topbarBottom);
  expect(initialSecondaryNav.detailTabsTop).toBeLessThan(initialSecondaryNav.topbarBottom + 20);
  await page.getByRole("button", { name: "Advanced model details" }).click();
  const operationsHeading = page.getByText("Latency, failures and AI fallback evidence");
  await operationsHeading.scrollIntoViewIfNeeded();
  await expect(operationsHeading).toBeVisible();
  const stickyPositions = await page.evaluate(() => {
    const topbar = document.querySelector(".topbar").getBoundingClientRect();
    const detailTabs = document.querySelector(".intelligence-view-tabs").getBoundingClientRect();
    return { topbarBottom: topbar.bottom, detailTabsTop: detailTabs.top };
  });
  expect(stickyPositions.detailTabsTop).toBeGreaterThanOrEqual(stickyPositions.topbarBottom);
  expect(stickyPositions.detailTabsTop).toBeLessThan(stickyPositions.topbarBottom + 20);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("laptop intelligence labels remain readable without horizontal overflow", async ({ page, isMobile }) => {
  test.skip(isMobile, "Desktop-only typography rule; mobile sizing is intentionally unchanged.");
  await page.getByRole("tab", { name: /Intelligence & MLOps/i }).click();
  await page.getByRole("button", { name: "Advanced model details" }).click();

  const fontSizes = await page.locator(".intelligence-main").evaluate((root) => {
    const read = (selector) => Number.parseFloat(getComputedStyle(root.querySelector(selector)).fontSize);
    return {
      operationsKicker: read(".operations-summary-kicker"),
      metricAction: read(".metric-explain-button"),
      outcomeLabel: read(".prediction-outcome-summary dt")
    };
  });

  expect(fontSizes.operationsKicker).toBeGreaterThanOrEqual(12);
  expect(fontSizes.metricAction).toBeGreaterThanOrEqual(12);
  expect(fontSizes.outcomeLabel).toBeGreaterThanOrEqual(11);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("hero video stays inside its frame with picture-in-picture disabled", async ({ page }) => {
  const frame = page.locator(".hero-visual");
  const video = page.locator(".hero-video");

  await expect(frame).toBeVisible();
  await expect(video).toBeVisible();
  await expect.poll(() => video.evaluate((element) => element.disablePictureInPicture)).toBe(true);

  const frameBox = await frame.boundingBox();
  const videoBox = await video.boundingBox();
  expect(frameBox).not.toBeNull();
  expect(videoBox).not.toBeNull();
  expect(Math.abs(videoBox.x - frameBox.x)).toBeLessThanOrEqual(1);
  expect(Math.abs(videoBox.y - frameBox.y)).toBeLessThanOrEqual(1);
  expect(Math.abs(videoBox.width - frameBox.width)).toBeLessThanOrEqual(2);
  expect(Math.abs(videoBox.height - frameBox.height)).toBeLessThanOrEqual(2);
  expect(await page.evaluate(() => document.pictureInPictureElement)).toBeNull();
});
