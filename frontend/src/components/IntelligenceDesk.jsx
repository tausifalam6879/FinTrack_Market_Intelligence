import { useEffect, useMemo, useState } from "react";
import StatusBadge from "./StatusBadge";
import { marketApi } from "../services/marketApi";

const presets = [
  ["^NSEI", "Nifty 50"], ["^BSESN", "Sensex"], ["RELIANCE.NS", "Reliance"],
  ["HDFCBANK.NS", "HDFC Bank"], ["INFY.NS", "Infosys"], ["AAPL", "Apple"], ["MSFT", "Microsoft"]
];

const formatNumber = (value) => value === null || value === undefined ? "—" : Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });

export default function IntelligenceDesk({ initialSymbol = "^NSEI" }) {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [draftSymbol, setDraftSymbol] = useState(initialSymbol);
  const [result, setResult] = useState(() => marketApi.seed.analysis(initialSymbol));
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);

  useEffect(() => { setSymbol(initialSymbol); setDraftSymbol(initialSymbol); }, [initialSymbol]);

  const load = async (nextSymbol = symbol, refresh = false, silent = false) => {
    const normalized = nextSymbol.trim().toUpperCase();
    if (!normalized) return;
    const seed = !refresh ? marketApi.seed.analysis(normalized) : null;
    if (seed) setResult(seed);
    else if (!refresh) setResult(null);
    if (!silent || !seed) setLoading(true);
    if (!silent) setError("");
    setSymbol(normalized); setDraftSymbol(normalized);
    try { setResult(await marketApi.analysis(normalized, refresh)); }
    catch { if (!silent) setError(`Research for ${normalized} is temporarily unavailable.`); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(initialSymbol, false, true); }, [initialSymbol]);

  const analysis = result?.data;
  const history = useMemo(() => analysis?.history || [], [analysis]);
  const send = async (value = question) => {
    const clean = value.trim();
    if (!clean || asking) return;
    const userMessage = { role: "user", content: clean };
    setMessages((current) => [...current, userMessage]); setQuestion(""); setAsking(true);
    try {
      const response = await marketApi.agent({ message: clean, symbol, recentMessages: messages.slice(-4) });
      setMessages((current) => [...current, { role: "assistant", content: response.answer, meta: response }]);
    } catch {
      setMessages((current) => [...current, { role: "assistant", content: "The research agent is temporarily unavailable. Price analytics above remain independent of the AI response.", meta: { llmStatus: "offline" } }]);
    } finally { setAsking(false); }
  };

  return (
    <section className="page-section" aria-labelledby="research-title">
      <div className="section-heading split-heading">
        <div><p className="eyebrow">OPEN MARKET INTELLIGENCE</p><h2 id="research-title">Research an index or company</h2><p>Technical evidence, macro drivers and AI explanations remain inside this website.</p></div>
        {result && <StatusBadge mode={result.mode} />}
      </div>

      <form className="symbol-search" onSubmit={(event) => { event.preventDefault(); load(draftSymbol); }}>
        <input value={draftSymbol} onChange={(event) => setDraftSymbol(event.target.value)} placeholder="Yahoo Finance symbol, e.g. RELIANCE.NS" aria-label="Market symbol" />
        <button className="primary-button" disabled={loading}>{loading ? "Researching…" : "Run research"}</button>
      </form>
      <div className="preset-row">{presets.map(([value, label]) => <button key={value} className={symbol === value ? "sector active" : "sector"} onClick={() => load(value)}>{label}</button>)}</div>
      {result?.mode === "snapshot" && <div className="notice warning">Showing packaged verified research while the live backend refreshes this symbol in the background.</div>}
      {result?.mode === "cache" && <div className="notice warning">Showing the last verified browser research while the live backend reconnects.</div>}
      {error && <div className="notice error">{error}</div>}

      {analysis && <>
        <div className="analysis-hero">
          <div><span className="asset-label">{analysis.symbol}</span><h3>{analysis.name}</h3><p>Evidence as of {new Date(analysis.dataAsOf).toLocaleString("en-IN")}</p></div>
          <div className={`outlook outlook-${String(analysis.outlook).toLowerCase()}`}><small>Experimental outlook</small><strong>{analysis.outlook}</strong></div>
        </div>
        <div className="metric-grid">
          <Metric label="Probability up" value={`${analysis.probabilityUp}%`} hint={`${analysis.probabilityDown}% probability down`} />
          <Metric label="Expected range" value={`${formatNumber(analysis.expectedRange?.low)} – ${formatNumber(analysis.expectedRange?.high)}`} hint={analysis.expectedRange?.currency} />
          <Metric label="RSI (14)" value={formatNumber(analysis.technicalIndicators?.rsi14)} hint="Below 30 oversold · above 70 overbought" />
          <Metric label="Historical test" value={`${analysis.model?.backtestAccuracy}%`} hint={`${analysis.model?.quality} signal quality`} />
        </div>
        <div className="research-grid">
          <article className="chart-panel"><div className="panel-title"><h3>One-year evidence</h3><span>Daily close</span></div><Sparkline history={history} /></article>
          <article className="drivers-panel"><div className="panel-title"><h3>Technical and macro inputs</h3><span>Transparent factors</span></div>
            <dl>
              <div><dt>SMA 20</dt><dd>{formatNumber(analysis.technicalIndicators?.sma20)}</dd></div>
              <div><dt>SMA 50</dt><dd>{formatNumber(analysis.technicalIndicators?.sma50)}</dd></div>
              <div><dt>Daily volatility</dt><dd>{formatNumber(analysis.technicalIndicators?.dailyVolatility20d)}%</dd></div>
              <div><dt>News tone</dt><dd>{analysis.newsFactor?.sentimentLabel || "—"}</dd></div>
              <div><dt>Macro signal</dt><dd>{analysis.macroFactor?.signal || "—"}</dd></div>
              <div><dt>Model</dt><dd>{analysis.model?.type}</dd></div>
            </dl>
          </article>
        </div>
        <div className="notice warning"><strong>Research limitation:</strong> {analysis.disclaimer}</div>
      </>}

      <article className="agent-panel">
        <div className="panel-title"><div><p className="eyebrow">GROUNDED RESEARCH AGENT</p><h3>Ask using verified market evidence</h3></div><span>Tools first · Gemini second</span></div>
        <div className="suggested-row">
          {["Gold aur crude ka Nifty par kya impact hai?", "Top gainers aur losers batao", `Why is ${symbol} outlook ${analysis?.outlook || "neutral"}?`].map((item) => <button key={item} onClick={() => send(item)}>{item}</button>)}
        </div>
        <div className="chat-log">
          {messages.length === 0 && <div className="agent-empty">Ask about prices, factors, market breadth, model weakness or current headlines.</div>}
          {messages.map((message, index) => <div key={index} className={`chat-message ${message.role}`}><p>{message.content}</p>{message.meta && <small>{message.meta.llmStatus === "connected" && message.meta.llmAnswerAccepted ? "Gemini grounded" : message.meta.llmStatus === "grounding_fallback" ? "LLM checked · verified tool answer used" : "Verified tool fallback"}</small>}</div>)}
          {asking && <div className="chat-message assistant"><p>Checking market tools and preparing a grounded answer…</p></div>}
        </div>
        <form className="chat-form" onSubmit={(event) => { event.preventDefault(); send(); }}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about available market evidence…" /><button disabled={!question.trim() || asking}>Send</button></form>
      </article>
    </section>
  );
}

function Metric({ label, value, hint }) { return <article className="metric-card"><small>{label}</small><strong>{value}</strong><span>{hint}</span></article>; }

function Sparkline({ history }) {
  const points = history.map((item) => Number(item.close)).filter(Number.isFinite);
  if (points.length < 2) return <div className="chart-empty">Price history unavailable</div>;
  const min = Math.min(...points); const max = Math.max(...points); const range = max - min || 1;
  const path = points.map((value, index) => `${(index / (points.length - 1)) * 100},${90 - ((value - min) / range) * 75}`).join(" ");
  return <div className="sparkline"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Historical price line"><defs><linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#168f9e" stopOpacity=".28"/><stop offset="1" stopColor="#168f9e" stopOpacity="0"/></linearGradient></defs><polygon points={`0,100 ${path} 100,100`} fill="url(#chartFill)"/><polyline points={path} fill="none" stroke="#087d8c" strokeWidth="2" vectorEffect="non-scaling-stroke"/></svg><div><span>{formatNumber(min)}</span><span>{formatNumber(max)}</span></div></div>;
}
