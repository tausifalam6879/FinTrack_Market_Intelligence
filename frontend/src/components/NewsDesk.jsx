import { useEffect, useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import { marketApi } from "../services/marketApi";

const filters = ["All", "India", "United States", "Commodities", "Technology"];

const categoryFor = (symbol = "") => {
  if (["^NSEI", "INR=X", "INFY.NS", "MARUTI.NS", "SUNPHARMA.NS", "NETWORK18.NS"].includes(symbol)) return "India";
  if (["GC=F", "CL=F"].includes(symbol)) return "Commodities";
  if (["AAPL", "TSLA"].includes(symbol)) return "Technology";
  return "United States";
};

const relatedLabel = (symbol = "") => ({
  "^NSEI": "Nifty 50", "^GSPC": "S&P 500", "GC=F": "Gold", "CL=F": "Crude oil",
  "INR=X": "USD/INR", "INFY.NS": "Infosys", "MARUTI.NS": "Maruti Suzuki",
  "SUNPHARMA.NS": "Sun Pharma", "NETWORK18.NS": "Network18", AAPL: "Apple", TSLA: "Tesla"
}[symbol] || symbol);

const sentimentLabel = (value) => Number(value) > 0.15 ? "Positive" : Number(value) < -0.15 ? "Negative" : "Neutral";

export default function NewsDesk({ onResearch }) {
  const [result, setResult] = useState(() => marketApi.seed.newsFeed());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeFilter, setActiveFilter] = useState("All");
  const [search, setSearch] = useState("");

  const load = async (refresh = false, silent = false) => {
    if (!silent) setLoading(true);
    if (!silent) setError("");
    try {
      setResult(await marketApi.newsFeed(refresh));
    } catch {
      if (!silent) setError("The headline provider is temporarily unavailable. The packaged verified snapshot remains visible.");
    } finally {
      if (!silent) setLoading(false);
    }
  };

  useEffect(() => {
    load(false, true);
    const refreshTimer = window.setInterval(() => load(true, true), 5 * 60 * 1000);
    return () => window.clearInterval(refreshTimer);
  }, []);

  const articles = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (result?.data?.articles || []).filter((article) => {
      const categoryMatches = activeFilter === "All" || categoryFor(article.relatedSymbol) === activeFilter;
      const queryMatches = !query || `${article.title} ${article.publisher} ${relatedLabel(article.relatedSymbol)}`.toLowerCase().includes(query);
      return categoryMatches && queryMatches;
    });
  }, [result, activeFilter, search]);

  return (
    <section className="page-section" aria-labelledby="news-title">
      <div className="section-heading split-heading">
        <div>
          <p className="eyebrow">TIMESTAMPED MARKET HEADLINES</p>
          <h2 id="news-title">Market news desk</h2>
          <p>Scan recent business headlines by market theme, then open the original publisher only when you choose.</p>
        </div>
        <div className="heading-actions">
          {result && <StatusBadge mode={result.mode} />}
          <button className="secondary-button" onClick={() => load(true)} disabled={loading}>{loading ? "Checking…" : "Refresh news"}</button>
        </div>
      </div>

      {result?.mode === "snapshot" && <div className="notice warning">Showing the packaged verified headlines from {new Date(result.savedAt).toLocaleString("en-IN")} while current news loads in the background.</div>}
      {result?.mode === "cache" && <div className="notice warning">The live headline provider did not respond. Showing the last successful browser response from {new Date(result.savedAt).toLocaleString("en-IN")}.</div>}
      {error && <div className="notice error">{error}</div>}

      <div className="news-toolbar">
        <div className="sector-row" aria-label="News themes">
          {filters.map((filter) => <button key={filter} className={activeFilter === filter ? "sector active" : "sector"} onClick={() => setActiveFilter(filter)}>{filter}</button>)}
        </div>
        <input className="search-input" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search headlines, publisher or company…" aria-label="Search market news" />
      </div>

      {loading && !result ? <NewsSkeleton /> : articles.length > 0 ? (
        <div className="news-grid">
          {articles.map((article, index) => {
            const symbol = article.relatedSymbol || "^NSEI";
            const label = sentimentLabel(article.sentiment);
            const category = categoryFor(symbol);
            return <article className="news-card" key={`${article.title}-${index}`}>
              <div
                className={`news-visual news-visual-${category.toLowerCase().replaceAll(" ", "-")}${article.imageUrl ? " has-image" : ""}`}
                style={article.imageUrl ? { backgroundImage: `linear-gradient(180deg, rgba(8,30,48,.08), rgba(8,30,48,.78)), url("${article.imageUrl}")` } : undefined}
                aria-hidden="true"
              >
                <span>{relatedLabel(symbol)}</span><b>{label}</b>
              </div>
              <div className="news-card-meta"><span>{category}</span><span className={`sentiment sentiment-${label.toLowerCase()}`}>{label}</span></div>
              <h3>{article.title}</h3>
              <div className="news-source"><strong>{article.publisher || "Unknown publisher"}</strong><span>{article.publishedAt ? new Date(article.publishedAt).toLocaleString("en-IN") : "Publication time unavailable"}</span></div>
              <div className="news-card-actions">
                <button className="text-button" onClick={() => onResearch(symbol)}>Research {relatedLabel(symbol)} →</button>
                {article.url && <a href={article.url} target="_blank" rel="noreferrer">Read source ↗</a>}
              </div>
            </article>;
          })}
        </div>
      ) : <div className="news-empty">No matching current headline was returned. Try another filter or refresh the feed.</div>}

      <div className="news-footer-note">
        <span>Source: {result?.data?.source || "Yahoo Finance headlines via yfinance"}</span>
        {result?.data?.generatedAt && <span>Feed checked {new Date(result.data.generatedAt).toLocaleString("en-IN")}</span>}
      </div>
      <p className="data-note">Headlines and automatic keyword sentiment are informational. Open the original publisher and verify the full article before drawing a conclusion.</p>
    </section>
  );
}

function NewsSkeleton() {
  return <div className="news-grid">{Array.from({ length: 6 }, (_, index) => <div className="news-card skeleton" key={index}><i /><i /><i /></div>)}</div>;
}
