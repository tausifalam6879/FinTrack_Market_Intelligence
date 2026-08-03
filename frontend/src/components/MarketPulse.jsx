import { useEffect, useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import { marketApi } from "../services/marketApi";

const formatNumber = (value) => Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const sectors = ["All", "Indices", "Energy", "Banking", "Technology", "Automobile", "Consumer", "Healthcare", "Telecom", "Media"];
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

export default function MarketPulse({ onResearch }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [sector, setSector] = useState("All");
  const [alertThreshold, setAlertThreshold] = useState(readAlertThreshold);
  const [nextScanAt, setNextScanAt] = useState(() => Date.now() + ALERT_SCAN_INTERVAL_MS);
  const [notificationPermission, setNotificationPermission] = useState(() => (
    typeof window.Notification === "undefined" ? "unsupported" : window.Notification.permission
  ));

  const load = async (refresh = false, silent = false) => {
    if (!silent) setLoading(true);
    if (!silent) setError("");
    try {
      setResult(await marketApi.overview(refresh));
    } catch (requestError) {
      if (!silent) setError("Market provider is temporarily unavailable. Please retry after a moment.");
    } finally {
      if (!silent) setLoading(false);
      setNextScanAt(Date.now() + ALERT_SCAN_INTERVAL_MS);
    }
  };

  useEffect(() => {
    load();
    const intervalId = window.setInterval(() => load(true, true), ALERT_SCAN_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(ALERT_THRESHOLD_KEY, String(alertThreshold));
  }, [alertThreshold]);

  const board = useMemo(() => {
    const items = result?.data?.watchlist || result?.data?.markets || [];
    return items.filter((item) => item.status === "available" && (sector === "All" || item.sector === sector));
  }, [result, sector]);

  const globalIndices = (result?.data?.markets || []).filter((item) => item.status === "available");
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
    <section className="page-section" aria-labelledby="market-title">
      <div className="section-heading split-heading">
        <div>
          <p className="eyebrow">PUBLIC MARKET PULSE</p>
          <h2 id="market-title">Markets at a glance</h2>
          <p>Filter sectors, inspect the latest available quote and open deeper research without leaving the website.</p>
        </div>
        <div className="heading-actions">
          {result && <StatusBadge mode={result.mode} />}
          <button className="secondary-button" onClick={() => load(true)} disabled={loading}>{loading ? "Checking…" : "Refresh now"}</button>
        </div>
      </div>

      {result?.mode === "cache" && <div className="notice warning">The live provider did not respond. Values below are the last verified browser response from {new Date(result.savedAt).toLocaleString("en-IN")}.</div>}
      {error && <div className="notice error">{error}</div>}

      <div className="sector-row" aria-label="Market sectors">
        {sectors.map((item) => <button key={item} className={sector === item ? "sector active" : "sector"} onClick={() => setSector(item)}>{item}</button>)}
      </div>

      {loading && !result ? <LoadingCards count={8} /> : (
        <div className="quote-grid">
          {board.map((quote) => {
            const positive = Number(quote.changePercent) >= 0;
            return (
              <button className="quote-card" key={quote.symbol} onClick={() => onResearch(quote.symbol)}>
                <div className="quote-card-top"><span>{quote.name}</span><span className={positive ? "trend up" : "trend down"}>{positive ? "↗" : "↘"}</span></div>
                <strong>{formatNumber(quote.price)}</strong>
                <span className={positive ? "change positive" : "change negative"}>{positive ? "+" : ""}{quote.changePercent}%</span>
                <small>{quote.symbol} · {quote.sector || quote.region}</small>
              </button>
            );
          })}
        </div>
      )}

      <section className="alert-center" aria-labelledby="alert-center-title">
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

      <div className="subsection-heading">
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

function LoadingCards({ count }) {
  return <div className="quote-grid">{Array.from({ length: count }, (_, index) => <div className="quote-card skeleton" key={index}><i /><i /><i /></div>)}</div>;
}
