import { useEffect, useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import { marketApi } from "../services/marketApi";

const formatNumber = (value) => Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const ALERT_SCAN_INTERVAL_MS = 15 * 60 * 1000;
const ALERT_THRESHOLD_KEY = "fintrack.market.alert-threshold.v1";
const SENT_ALERTS_KEY = "fintrack.market.sent-alerts.v1";

const readAlertThreshold = () => {
  const stored = Number(window.localStorage.getItem(ALERT_THRESHOLD_KEY));
  return stored >= 1 && stored <= 10 ? stored : 3;
};

const readSentAlerts = () => {
  try {
    const stored = JSON.parse(window.localStorage.getItem(SENT_ALERTS_KEY) || "[]");
    return Array.isArray(stored) ? stored : [];
  } catch {
    return [];
  }
};

export default function MarketPulse({ onResearch, onQuotesChange, onMarketContextRefresh }) {
  const [result, setResult] = useState(() => marketApi.seed.overview());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [companyQuery, setCompanyQuery] = useState("");
  const [companyMatches, setCompanyMatches] = useState([]);
  const [companySearchMode, setCompanySearchMode] = useState("");
  const [companySearchError, setCompanySearchError] = useState("");
  const [searchingCompanies, setSearchingCompanies] = useState(false);
  const [alertThreshold, setAlertThreshold] = useState(readAlertThreshold);
  const [nextScanAt, setNextScanAt] = useState(() => Date.now() + ALERT_SCAN_INTERVAL_MS);
  const [notificationPermission, setNotificationPermission] = useState(() => (
    typeof window.Notification === "undefined" ? "unsupported" : window.Notification.permission
  ));

  const load = async (refresh = false, silent = false) => {
    if (!silent) setLoading(true);
    if (!silent) setError("");
    try {
      const response = await marketApi.overview(refresh);
      setResult(response);
      if (refresh) onMarketContextRefresh?.(true);
    } catch (requestError) {
      if (!silent) setError("Market provider is temporarily unavailable. Please retry after a moment.");
    } finally {
      if (!silent) setLoading(false);
      setNextScanAt(Date.now() + ALERT_SCAN_INTERVAL_MS);
    }
  };

  useEffect(() => {
    load(false, true);
    const intervalId = window.setInterval(() => load(true, true), ALERT_SCAN_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(ALERT_THRESHOLD_KEY, String(alertThreshold));
  }, [alertThreshold]);

  useEffect(() => {
    const clean = companyQuery.trim();
    if (clean.length < 2) {
      setCompanyMatches([]);
      setCompanySearchMode("");
      setCompanySearchError("");
      setSearchingCompanies(false);
      return undefined;
    }

    let active = true;
    const timer = window.setTimeout(async () => {
      setSearchingCompanies(true);
      setCompanySearchError("");
      try {
        const response = await marketApi.companies(clean, 8);
        if (!active) return;
        setCompanyMatches(response.items || []);
        setCompanySearchMode(response.mode || "live");
      } catch {
        if (!active) return;
        setCompanyMatches([]);
        setCompanySearchMode("");
        setCompanySearchError("Company search provider is temporarily unavailable.");
      } finally {
        if (active) setSearchingCompanies(false);
      }
    }, 350);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [companyQuery]);

  useEffect(() => {
    const quotes = result?.data?.watchlist || result?.data?.markets || [];
    onQuotesChange?.(quotes.filter((item) => item.status === "available"));
  }, [onQuotesChange, result]);

  const globalIndices = (result?.data?.markets || []).filter((item) => item.status === "available");
  const chartIndices = (result?.data?.watchlist || []).filter((item) => item.status === "available" && item.sector === "Indices");
  const generatedAt = result?.data?.generatedAt || result?.savedAt;
  const downsideAlerts = useMemo(() => {
    const companies = result?.data?.watchlist || [];
    return companies
      .filter((item) => item.status === "available" && item.sector !== "Indices" && Number(item.changePercent) <= -alertThreshold)
      .sort((first, second) => Number(first.changePercent) - Number(second.changePercent));
  }, [result, alertThreshold]);

  useEffect(() => {
    if (notificationPermission !== "granted" || result?.mode !== "live" || !generatedAt || downsideAlerts.length === 0) return;

    const sentAlerts = readSentAlerts();
    const sentSet = new Set(sentAlerts);
    const newKeys = [];

    downsideAlerts.forEach((alert) => {
      const alertKey = `${alert.symbol}|${generatedAt}|${alertThreshold}`;
      if (sentSet.has(alertKey)) return;
      const severity = Number(alert.changePercent) <= -5 ? "Critical move" : "Downside move";
      new window.Notification(`${severity}: ${alert.name}`, {
        body: `${alert.symbol} is ${Math.abs(Number(alert.changePercent)).toFixed(2)}% below its previous close. Open FinTrack to verify the timestamp and source.`,
        tag: `fintrack-${alert.symbol}`
      });
      newKeys.push(alertKey);
    });

    if (newKeys.length) {
      window.localStorage.setItem(SENT_ALERTS_KEY, JSON.stringify([...sentAlerts, ...newKeys].slice(-100)));
    }
  }, [alertThreshold, downsideAlerts, generatedAt, notificationPermission, result?.mode]);

  const enableNotifications = async () => {
    if (typeof window.Notification === "undefined") {
      setNotificationPermission("unsupported");
      return;
    }
    const permission = await window.Notification.requestPermission();
    setNotificationPermission(permission);
  };

  return (
    <section id="market-overview" className="page-section" aria-labelledby="market-title">
      <div className="section-heading split-heading">
        <div>
          <p className="eyebrow">PUBLIC MARKET PULSE</p>
          <h2 id="market-title">Markets at a glance</h2>
          <p>Search companies, inspect daily market movement and open deeper research without leaving the website.</p>
        </div>
        <div className="heading-actions">
          {result && <StatusBadge mode={result.mode} />}
          <button className="secondary-button" onClick={() => load(true)} disabled={loading}>{loading ? "Checking…" : "Refresh now"}</button>
        </div>
      </div>

      {result?.mode === "snapshot" && <div className="notice warning">Showing the packaged verified snapshot from {new Date(result.savedAt).toLocaleString("en-IN")} while the latest live feed loads in the background.</div>}
      {result?.mode === "cache" && <div className="notice warning">The live provider did not respond. Values below are the last verified browser response from {new Date(result.savedAt).toLocaleString("en-IN")}.</div>}
      {error && <div className="notice error">{error}</div>}

      <section id="company-search" className="company-discovery" aria-labelledby="company-discovery-title">
        <div>
          <p className="eyebrow">DYNAMIC COMPANY DISCOVERY</p>
          <h3 id="company-discovery-title">Find any supported public company</h3>
          <p>Search by company name or ticker. No account is required.</p>
        </div>
        <form className="company-search-form" onSubmit={(event) => {
          event.preventDefault();
          if (companyMatches[0]) onResearch(companyMatches[0].symbol);
        }}>
          <input
            value={companyQuery}
            onChange={(event) => setCompanyQuery(event.target.value)}
            placeholder="Search Reliance, Tata Motors, Apple, Microsoft…"
            aria-label="Search companies by name or ticker"
            aria-describedby="company-search-help"
          />
          <button className="primary-button" disabled={!companyMatches.length || searchingCompanies}>
            {searchingCompanies ? "Searching…" : "Open first match"}
          </button>
        </form>
        <small id="company-search-help">Type at least two characters. Research opens with the selected Yahoo Finance symbol.</small>
        {companyQuery.trim().length >= 2 && <div className="company-search-results" aria-label="Company search results">
          {searchingCompanies && <div className="company-search-state">Searching the live company directory…</div>}
          {!searchingCompanies && companySearchError && <div className="company-search-state error">{companySearchError}</div>}
          {!searchingCompanies && !companySearchError && companyMatches.length === 0 && <div className="company-search-state">No matching public company was found.</div>}
          {!searchingCompanies && companyMatches.map((company) => <button key={company.symbol} onClick={() => onResearch(company.symbol)}>
            <span><strong>{company.name}</strong><small>{company.symbol} · {company.exchange}</small></span>
            <span><small>{company.sector}</small><b>Research →</b></span>
          </button>)}
          {!searchingCompanies && companySearchMode === "fallback" && companyMatches.length > 0 && <p className="company-search-note">Live discovery is unavailable; showing matches from the verified FinTrack board.</p>}
        </div>}
      </section>

      <div id="daily-market" className="market-data-workspace">
        <MarketHistoryPanel indices={chartIndices.length ? chartIndices : globalIndices} onResearch={onResearch} />
        <MarketStatisticsPanel quotes={result?.data?.watchlist || []} generatedAt={generatedAt} onResearch={onResearch} />
      </div>

      <section id="risk-alerts" className="alert-center" aria-labelledby="alert-center-title">
        <div className="alert-center-header">
          <div>
            <p className="eyebrow">AI-ASSISTED RISK MONITOR</p>
            <h3 id="alert-center-title">Company downside alerts</h3>
            <p>FinTrack checks verified company moves every 15 minutes and flags shares crossing your selected downside threshold.</p>
          </div>
          <div className="alert-actions">
            <span className="scan-chip">Next scan {new Date(nextScanAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span>
            {notificationPermission !== "granted" && <button className="secondary-button" onClick={enableNotifications} disabled={notificationPermission === "denied"}>
              {notificationPermission === "denied" ? "Notifications blocked" : notificationPermission === "unsupported" ? "Notifications unsupported" : "Enable notifications"}
            </button>}
            {notificationPermission === "granted" && <span className="notification-enabled">Browser notifications on</span>}
          </div>
        </div>

        <div className="threshold-control">
          <label htmlFor="downside-threshold">Alert when a company falls <strong>{alertThreshold}% or more</strong></label>
          <input
            id="downside-threshold"
            type="range"
            min="1"
            max="10"
            step="0.5"
            value={alertThreshold}
            onChange={(event) => setAlertThreshold(Number(event.target.value))}
            aria-valuetext={`${alertThreshold} percent downside`}
          />
          <div aria-hidden="true"><span>1% sensitive</span><span>10% severe</span></div>
        </div>

        {downsideAlerts.length > 0 ? <div className="market-alert-grid">
          {downsideAlerts.map((alert) => {
            const critical = Number(alert.changePercent) <= -5;
            return <article className={`market-alert ${critical ? "critical" : "warning"}`} key={alert.symbol}>
              <span className="alert-icon" aria-hidden="true">!</span>
              <div>
                <small>{critical ? "Critical downside move" : "Downside threshold crossed"}</small>
                <h4>{alert.name}</h4>
                <p><strong>{alert.changePercent}%</strong> versus previous close · {alert.symbol}</p>
              </div>
              <button className="text-button" onClick={() => onResearch(alert.symbol)}>Verify evidence →</button>
            </article>;
          })}
        </div> : <div className="alert-clear"><span aria-hidden="true">✓</span><div><strong>No monitored company has crossed the {alertThreshold}% downside threshold.</strong><small>This status will be checked again automatically; you can also use Refresh now.</small></div></div>}

        <p className="alert-disclaimer">Alerts are evidence-based risk signals, not automatic sell instructions or personalized investment advice. Always verify the quote timestamp, source and your own risk plan.</p>
      </section>

      <div id="global-markets" className="subsection-heading">
        <div><p className="eyebrow">GLOBAL VIEW</p><h3>Major global indices</h3></div>
        {generatedAt && <small>Feed checked {new Date(generatedAt).toLocaleString("en-IN")}</small>}
      </div>
      <div className="indices-grid">
        {globalIndices.map((index) => <article className="index-card" key={index.symbol}>
          <div><strong>{index.name}</strong><small>{index.region} · {index.symbol}</small></div>
          <div className="index-value"><strong>{formatNumber(index.price)}</strong><span className={Number(index.changePercent) >= 0 ? "positive" : "negative"}>{Number(index.changePercent) >= 0 ? "+" : ""}{index.changePercent}%</span></div>
          <button className="text-button" onClick={() => onResearch(index.symbol)}>Open intelligence →</button>
        </article>)}
      </div>

      <p className="data-note">Quotes are informational and may be delayed or unchanged while an exchange is closed. The timestamp—not the animation—determines data freshness.</p>
    </section>
  );
}

function MarketStatisticsPanel({ quotes, generatedAt, onResearch }) {
  const companies = quotes.filter((item) => item.status === "available" && item.sector !== "Indices");
  const advances = companies.filter((item) => Number(item.changePercent) > 0.05);
  const declines = companies.filter((item) => Number(item.changePercent) < -0.05);
  const unchanged = companies.length - advances.length - declines.length;
  const atHigh = companies.filter((item) => Number(item.high) > 0 && Number(item.price) >= Number(item.high) * 0.9995).length;
  const atLow = companies.filter((item) => Number(item.low) > 0 && Number(item.price) <= Number(item.low) * 1.0005).length;
  const sorted = [...companies].sort((first, second) => Number(second.changePercent) - Number(first.changePercent));
  const gainer = sorted[0];
  const loser = sorted[sorted.length - 1];

  return <section id="market-statistics" className="market-statistics-panel" aria-labelledby="market-statistics-title">
    <div className="market-statistics-heading">
      <div><p className="eyebrow">VERIFIED BOARD BREADTH</p><h3 id="market-statistics-title">Market statistics</h3></div>
      {generatedAt && <small>As of {new Date(generatedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</small>}
    </div>
    <div className="market-stat-primary">
      <article><small>Monitored</small><strong>{companies.length}</strong></article>
      <article className="stat-up"><small>Advances</small><strong>{advances.length}</strong></article>
      <article className="stat-down"><small>Declines</small><strong>{declines.length}</strong></article>
      <article className="stat-flat"><small>Unchanged</small><strong>{unchanged}</strong></article>
    </div>
    <div className="market-stat-session">
      <div><small>At session high</small><strong className="positive">▲ {atHigh}</strong></div>
      <div><small>At session low</small><strong className="negative">▼ {atLow}</strong></div>
    </div>
    <div className="market-movers">
      <p>BOARD MOVERS</p>
      {gainer && <button onClick={() => onResearch(gainer.symbol)}><span><small>Largest gainer</small><strong>{gainer.name}</strong></span><b className="positive">+{gainer.changePercent}%</b></button>}
      {loser && <button onClick={() => onResearch(loser.symbol)}><span><small>Largest decline</small><strong>{loser.name}</strong></span><b className="negative">{loser.changePercent}%</b></button>}
    </div>
    <p className="market-stat-note">Breadth covers FinTrack's monitored company board, not every exchange-listed stock.</p>
  </section>;
}

function MarketHistoryPanel({ indices, onResearch }) {
  const choices = indices.slice(0, 5);
  const [symbol, setSymbol] = useState(() => choices.find((item) => item.symbol === "^NSEI")?.symbol || choices[0]?.symbol || "^NSEI");
  const [period, setPeriod] = useState("3M");
  const [analysis, setAnalysis] = useState(() => marketApi.seed.analysis(symbol)?.data || null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!choices.some((item) => item.symbol === symbol) && choices[0]) setSymbol(choices[0].symbol);
  }, [choices, symbol]);

  useEffect(() => {
    let active = true;
    const seed = marketApi.seed.analysis(symbol)?.data;
    if (seed) setAnalysis(seed);
    setLoading(!seed);
    marketApi.analysis(symbol)
      .then((response) => { if (active) setAnalysis(response.data); })
      .catch(() => undefined)
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [symbol]);

  const history = analysis?.history || [];
  const periodDays = { "1M": 22, "3M": 66, "6M": 132, "1Y": 260 }[period];
  const visibleHistory = history.slice(-periodDays);
  const selectedQuote = choices.find((item) => item.symbol === symbol);

  return <section className="market-history-panel" aria-labelledby="market-history-title">
    <div className="market-history-heading">
      <div><p className="eyebrow">DAILY MARKET HISTORY</p><h3 id="market-history-title">Move through the chart, day by day</h3><p>Hover or touch the line to inspect the verified closing value for that date.</p></div>
      <button className="text-button" onClick={() => onResearch(symbol)}>Open full research →</button>
    </div>
    <div className="market-history-toolbar">
      <div className="index-picker" aria-label="Choose market index">{choices.map((item) => <button key={item.symbol} className={symbol === item.symbol ? "active" : ""} onClick={() => setSymbol(item.symbol)}>{item.name}</button>)}</div>
      <div className="period-picker" aria-label="Choose chart period">{["1M", "3M", "6M", "1Y"].map((item) => <button key={item} className={period === item ? "active" : ""} onClick={() => setPeriod(item)}>{item}</button>)}</div>
    </div>
    <div className="market-history-summary">
      <div><small>{selectedQuote?.name || analysis?.name || symbol}</small><strong>{selectedQuote ? formatNumber(selectedQuote.price) : "—"}</strong></div>
      <span className={Number(selectedQuote?.changePercent) >= 0 ? "positive" : "negative"}>{selectedQuote ? `${Number(selectedQuote.changePercent) >= 0 ? "+" : ""}${selectedQuote.changePercent}% today` : "Daily close history"}</span>
      <small>{analysis?.dataAsOf ? `Evidence ${new Date(analysis.dataAsOf).toLocaleString("en-IN")}` : "Loading verified history…"}</small>
    </div>
    {loading && visibleHistory.length < 2 ? <div className="history-loading">Loading verified daily history…</div> : <InteractiveHistoryChart history={visibleHistory} symbol={symbol} />}
    <p className="chart-disclaimer">This is daily closing history, not an intraday exchange feed. Quotes may be delayed.</p>
  </section>;
}

function InteractiveHistoryChart({ history, symbol }) {
  const rows = history.filter((item) => Number.isFinite(Number(item.close)));
  const [hoverIndex, setHoverIndex] = useState(null);
  if (rows.length < 2) return <div className="history-loading">Verified history is unavailable for this index right now.</div>;
  const closes = rows.map((item) => Number(item.close));
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const spread = max - min || 1;
  const xFor = (index) => 22 + (index / (rows.length - 1)) * 676;
  const yFor = (value) => 218 - ((value - min) / spread) * 178;
  const path = rows.map((item, index) => `${xFor(index)},${yFor(Number(item.close))}`).join(" ");
  const activeIndex = hoverIndex === null ? rows.length - 1 : hoverIndex;
  const active = rows[activeIndex];
  const activeX = xFor(activeIndex);
  const activeY = yFor(Number(active.close));
  const move = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
    setHoverIndex(Math.round(ratio * (rows.length - 1)));
  };
  return <div className="interactive-history-chart" onPointerMove={move} onPointerLeave={() => setHoverIndex(null)}>
    <svg viewBox="0 0 720 250" preserveAspectRatio="none" role="img" aria-label={`${symbol} daily closing history`}>
      <defs><linearGradient id={`history-fill-${symbol.replace(/\W/g, "")}`} x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#32a6c5" stopOpacity=".42"/><stop offset="1" stopColor="#32a6c5" stopOpacity=".03"/></linearGradient></defs>
      {[40, 84, 128, 172, 218].map((y) => <line key={y} x1="22" x2="698" y1={y} y2={y} className="history-gridline" />)}
      <polygon points={`22,218 ${path} 698,218`} fill={`url(#history-fill-${symbol.replace(/\W/g, "")})`} />
      <polyline points={path} className="history-line" />
      <line x1={activeX} x2={activeX} y1="30" y2="218" className="history-cursor" />
      <circle cx={activeX} cy={activeY} r="5" className="history-point" />
    </svg>
    <div className={`history-tooltip ${activeX > 510 ? "align-left" : ""}`} style={{ left: `${(activeX / 720) * 100}%`, top: `${Math.max(8, (activeY / 250) * 100 - 4)}%` }}>
      <strong>{symbol}</strong><b>{formatNumber(active.close)}</b><span>{new Date(`${active.date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short", year: "numeric" })}</span>
    </div>
    <div className="history-axis"><span>{new Date(`${rows[0].date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span><span>{new Date(`${rows[rows.length - 1].date}T00:00:00`).toLocaleDateString("en-IN", { day: "2-digit", month: "short" })}</span></div>
  </div>;
}
