import { useEffect, useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import { marketApi } from "../services/marketApi";

const displayName = (code) => {
  try { return new Intl.DisplayNames(["en"], { type: "currency" }).of(code) || code; }
  catch { return code; }
};

const positiveRate = (value) => {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
};

const formatRate = (value, digits = 2) => {
  const parsed = positiveRate(value);
  return parsed === null ? null : parsed.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
};

export default function CurrencyDesk({ onDataChange }) {
  const [result, setResult] = useState(() => marketApi.seed.currencies());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");

  const load = async (refresh = false, silent = false) => {
    if (!silent) setLoading(true);
    if (!silent) setError("");
    try {
      const response = await marketApi.currencies(refresh);
      setResult(response);
      onDataChange?.(response);
    }
    catch { if (!silent) setError("Currency feed is temporarily unavailable. The packaged verified snapshot remains visible."); }
    finally { if (!silent) setLoading(false); }
  };

  useEffect(() => { load(false, true); }, []);

  const directory = useMemo(() => Object.entries(result?.data?.referenceRates || {})
    .map(([code, value]) => ({ code, value, name: displayName(code) }))
    .filter((item) => positiveRate(item.value) !== null)
    .filter((item) => `${item.code} ${item.name}`.toLowerCase().includes(search.trim().toLowerCase()))
    .sort((left, right) => left.code.localeCompare(right.code)), [result, search]);

  return (
    <section id="currency-overview" className="page-section" aria-labelledby="currency-title">
      <div className="section-heading split-heading">
        <div><p className="eyebrow">INR CURRENCY DESK</p><h2 id="currency-title">How global currencies compare with ₹1</h2><p>One unit of each listed currency is converted into Indian rupees using the latest available provider quote.</p></div>
        <div className="heading-actions">{result && <StatusBadge mode={result.mode} label={result.mode === "live" ? "Currency feed connected" : undefined} />}<button className="secondary-button" onClick={() => load(true)} disabled={loading}>{loading ? "Checking…" : "Refresh now"}</button></div>
      </div>

      {result?.mode === "snapshot" && <div className="notice warning">Showing the packaged verified snapshot from {new Date(result.savedAt).toLocaleString("en-IN")} while the latest currency feed loads in the background.</div>}
      {result?.mode === "cache" && <div className="notice warning">Showing the last verified response from {new Date(result.savedAt).toLocaleString("en-IN")} while the provider reconnects.</div>}
      {error && <div className="notice error">{error}</div>}

      <div id="featured-currency-rates" className="currency-grid">
        {(result?.data?.currencies || []).map((currency) => {
          const displayedRate = formatRate(currency.inrValue, currency.digits);
          return <article className="currency-card" key={currency.code}>
            <div className="currency-country">{currency.country}</div>
            <div className="currency-code">{currency.code}</div>
            <strong>{displayedRate === null ? "Unavailable" : `₹${displayedRate}`}</strong>
            <small>{currency.quoteMode === "intraday" ? "Latest quote" : "Reference rate"} · {currency.name}</small>
          </article>;
        })}
      </div>

      <div id="currency-directory" className="directory-panel">
        <div className="subsection-heading"><div><p className="eyebrow">CURRENCY DIRECTORY</p><h3>{directory.length} matching currencies</h3></div>{result?.data?.generatedAt && <small>Checked {new Date(result.data.generatedAt).toLocaleString("en-IN")}</small>}</div>
        <input id="currency-search" className="search-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search USD, Thai baht, South African rand…" aria-label="Search currency directory" />
        <div className="directory-grid">
          {directory.slice(0, 80).map((currency) => <article key={currency.code}><strong>{currency.code}</strong><span>₹{formatRate(currency.value, currency.value < 1 ? 4 : 2)}</span><small>{currency.name}</small></article>)}
        </div>
        {directory.length > 80 && <p className="data-note">Showing the first 80 matches. Narrow the search to find a specific currency.</p>}
      </div>
      <p id="currency-rate-notes" className="data-note">Rates are informational midpoint/reference values. Banks, cards and remittance providers may apply a different rate or markup.</p>
    </section>
  );
}
