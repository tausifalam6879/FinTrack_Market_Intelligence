import { useEffect, useMemo, useRef, useState } from "react";
import StatusBadge from "./StatusBadge";
import { marketApi } from "../services/marketApi";

const presets = [
  ["^NSEI", "Nifty 50"], ["^BSESN", "Sensex"], ["RELIANCE.NS", "Reliance"],
  ["HDFCBANK.NS", "HDFC Bank"], ["INFY.NS", "Infosys"], ["AAPL", "Apple"], ["MSFT", "Microsoft"]
];

const indexAliases = {
  "NIFTY": "^NSEI", "NIFTY 50": "^NSEI", "NSEI": "^NSEI",
  "SENSEX": "^BSESN", "BSE SENSEX": "^BSESN", "BSESN": "^BSESN"
};

const formatNumber = (value) => value === null || value === undefined ? "—" : Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
const formatPercent = (value) => value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;
const formatCompactMoney = (value, currency) => {
  const numeric = Number(value);
  if (value === null || value === undefined || !Number.isFinite(numeric)) return "—";
  const rawCurrency = String(currency || "").trim();
  const currencyCode = /^[A-Z]{3}$/.test(rawCurrency) ? rawCurrency : null;
  try {
    return new Intl.NumberFormat("en", {
      notation: "compact",
      maximumFractionDigits: 2,
      ...(currencyCode ? { style: "currency", currency: currencyCode } : {})
    }).format(numeric);
  } catch {
    const number = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 2 }).format(numeric);
    return rawCurrency && rawCurrency !== "Local currency" ? `${number} ${rawCurrency}` : number;
  }
};

export default function IntelligenceDesk({ initialSymbol = "^NSEI" }) {
  const [symbol, setSymbol] = useState(initialSymbol);
  const [draftSymbol, setDraftSymbol] = useState(initialSymbol);
  const [result, setResult] = useState(() => marketApi.seed.analysis(initialSymbol));
  const [loading, setLoading] = useState(false);
  const [resolvingCompany, setResolvingCompany] = useState(false);
  const [error, setError] = useState("");
  const [companyMatches, setCompanyMatches] = useState([]);
  const [companySearchOpen, setCompanySearchOpen] = useState(false);
  const [companySearchError, setCompanySearchError] = useState("");
  const [searchingCompanies, setSearchingCompanies] = useState(false);
  const [resolvedCompany, setResolvedCompany] = useState(null);
  const [modelStatus, setModelStatus] = useState(null);
  const [modelStatusLoading, setModelStatusLoading] = useState(false);
  const [modelStatusError, setModelStatusError] = useState("");
  const [experiments, setExperiments] = useState(null);
  const [experimentsLoading, setExperimentsLoading] = useState(false);
  const [experimentsError, setExperimentsError] = useState("");
  const [peerComparison, setPeerComparison] = useState(null);
  const [peerComparisonLoading, setPeerComparisonLoading] = useState(false);
  const [peerComparisonError, setPeerComparisonError] = useState("");
  const [companyResearch, setCompanyResearch] = useState(null);
  const [companyResearchLoading, setCompanyResearchLoading] = useState(false);
  const [companyResearchError, setCompanyResearchError] = useState("");
  const [documents, setDocuments] = useState([]);
  const [documentsLoading, setDocumentsLoading] = useState(false);
  const [documentPreparation, setDocumentPreparation] = useState(null);
  const [ragPreparing, setRagPreparing] = useState(false);
  const [ragPrepareError, setRagPrepareError] = useState("");
  const [ragQuestion, setRagQuestion] = useState("");
  const [ragResult, setRagResult] = useState(null);
  const [ragLoading, setRagLoading] = useState(false);
  const [ragError, setRagError] = useState("");
  const [messages, setMessages] = useState([]);
  const [question, setQuestion] = useState("");
  const [asking, setAsking] = useState(false);
  const loadSequenceRef = useRef(0);

  useEffect(() => { setSymbol(initialSymbol); setDraftSymbol(initialSymbol); }, [initialSymbol]);

  useEffect(() => {
    const clean = draftSymbol.trim();
    if (!companySearchOpen || clean.length < 2 || clean.startsWith("^")) {
      setCompanyMatches([]);
      setCompanySearchError("");
      setSearchingCompanies(false);
      return undefined;
    }
    let active = true;
    const timer = window.setTimeout(async () => {
      setSearchingCompanies(true);
      setCompanySearchError("");
      try {
        const response = await marketApi.companies(clean, 6);
        if (!active) return;
        setCompanyMatches(response.items || []);
        if (!(response.items || []).length) setCompanySearchError(`No public company matched “${clean}”.`);
      } catch {
        if (active) {
          setCompanyMatches([]);
          setCompanySearchError("Company directory is temporarily unavailable.");
        }
      } finally {
        if (active) setSearchingCompanies(false);
      }
    }, 300);
    return () => { active = false; window.clearTimeout(timer); };
  }, [companySearchOpen, draftSymbol]);

  const load = async (nextSymbol = symbol, refresh = false, silent = false) => {
    const normalized = nextSymbol.trim().toUpperCase();
    if (!normalized) return;
    const requestId = ++loadSequenceRef.current;
    const seed = !refresh ? marketApi.seed.analysis(normalized) : null;
    if (seed) setResult(seed);
    else if (!refresh) setResult(null);
    if (!silent || !seed) setLoading(true);
    if (!silent) setError("");
    setModelStatusLoading(true);
    setModelStatusError("");
    setExperimentsLoading(true);
    setExperimentsError("");
    setPeerComparisonLoading(!normalized.startsWith("^"));
    setPeerComparisonError("");
    setCompanyResearch(null);
    setCompanyResearchLoading(!normalized.startsWith("^"));
    setCompanyResearchError("");
    setDocumentsLoading(true);
    setDocumentPreparation(null);
    setRagPrepareError("");
    setRagResult(null);
    setRagError("");
    setCompanySearchOpen(false);
    setCompanyMatches([]);
    setSymbol(normalized); setDraftSymbol(normalized);
    const monitoringRequest = marketApi.modelStatus(normalized)
      .then((status) => { if (loadSequenceRef.current === requestId) setModelStatus(status); })
      .catch(() => { if (loadSequenceRef.current === requestId) { setModelStatus(null); setModelStatusError("Persistent model monitoring is temporarily unavailable."); } })
      .finally(() => { if (loadSequenceRef.current === requestId) setModelStatusLoading(false); });
    const experimentsRequest = marketApi.experiments(normalized, 8)
      .then((response) => { if (loadSequenceRef.current === requestId) setExperiments(response); })
      .catch(() => {
        if (loadSequenceRef.current === requestId) {
          setExperiments(null);
          setExperimentsError("Experiment comparison is temporarily unavailable.");
        }
      })
      .finally(() => { if (loadSequenceRef.current === requestId) setExperimentsLoading(false); });
    const peersRequest = normalized.startsWith("^")
      ? Promise.resolve().then(() => {
          if (loadSequenceRef.current === requestId) {
            setPeerComparison(null);
            setPeerComparisonLoading(false);
          }
        })
      : marketApi.peerComparison(normalized, refresh)
        .then((response) => { if (loadSequenceRef.current === requestId) setPeerComparison(response.data || response); })
        .catch(() => {
          if (loadSequenceRef.current === requestId) {
            setPeerComparison(null);
            setPeerComparisonError("Dynamic sector comparison is temporarily unavailable.");
          }
        })
        .finally(() => { if (loadSequenceRef.current === requestId) setPeerComparisonLoading(false); });
    const companyRequest = normalized.startsWith("^")
      ? Promise.resolve().then(() => {
          if (loadSequenceRef.current === requestId) {
            setCompanyResearch(null);
            setCompanyResearchLoading(false);
          }
        })
      : marketApi.company(normalized, refresh)
        .then((response) => { if (loadSequenceRef.current === requestId) setCompanyResearch(response.data || response); })
        .catch(() => {
          if (loadSequenceRef.current === requestId) {
            setCompanyResearch(null);
            setCompanyResearchError("Company fundamentals are temporarily unavailable.");
          }
        })
        .finally(() => { if (loadSequenceRef.current === requestId) setCompanyResearchLoading(false); });
    const documentsRequest = normalized.startsWith("^")
      ? Promise.resolve().then(() => { setDocuments([]); setDocumentPreparation(null); setDocumentsLoading(false); })
      : marketApi.documents(normalized)
        .then(async (initialResponse) => {
          if (loadSequenceRef.current !== requestId) return;
          let response = initialResponse;
          setDocumentPreparation(response.preparation || null);
          if (!(response.items || []).length && response.preparation?.autoPrepare && response.preparation?.needsPreparation !== false) {
            setRagPreparing(true);
            try {
              await marketApi.prepareDocuments(normalized);
              response = await marketApi.documents(normalized);
            } catch {
              if (loadSequenceRef.current === requestId) {
                setRagPrepareError(`Verified market evidence for ${normalized} could not be indexed right now. Please retry.`);
              }
            } finally {
              if (loadSequenceRef.current === requestId) setRagPreparing(false);
            }
          }
          if (loadSequenceRef.current === requestId) {
            setDocuments(response.items || []);
            setDocumentPreparation(response.preparation || null);
          }
        })
        .catch(() => { if (loadSequenceRef.current === requestId) { setDocuments([]); setDocumentPreparation(null); } })
        .finally(() => { if (loadSequenceRef.current === requestId) setDocumentsLoading(false); });
    try {
      const nextResult = await marketApi.analysis(normalized, refresh);
      if (loadSequenceRef.current === requestId) {
        setResult(nextResult);
        await monitoringRequest;
        try {
          const refreshedStatus = await marketApi.modelStatus(normalized);
          if (loadSequenceRef.current === requestId) {
            setModelStatus(refreshedStatus);
            setModelStatusError("");
          }
        } catch {
          // The first monitoring response remains usable if this post-prediction refresh fails.
        }
      }
    } catch {
      if (!silent && loadSequenceRef.current === requestId) setError(`Research for ${normalized} is temporarily unavailable.`);
    } finally {
      if (loadSequenceRef.current === requestId) setLoading(false);
    }
    await Promise.allSettled([monitoringRequest, experimentsRequest, peersRequest, companyRequest, documentsRequest]);
  };

  useEffect(() => { load(initialSymbol, false, true); }, [initialSymbol]);

  const analysis = result?.data;
  const history = useMemo(() => analysis?.history || [], [analysis]);
  const modelComparisons = analysis?.model?.modelsCompared || [];
  const featureImportance = analysis?.model?.featureImportance || [];
  const localExplanation = analysis?.model?.localExplanation;
  const predictionAudit = analysis?.predictionAudit || [];
  const selectCompany = (company) => {
    setResolvedCompany(company);
    setCompanySearchOpen(false);
    setCompanyMatches([]);
    load(company.symbol);
  };
  const resolveAndLoad = async () => {
    const clean = draftSymbol.trim();
    if (!clean || resolvingCompany || loading) return;
    const alias = indexAliases[clean.toUpperCase()];
    if (clean.startsWith("^") || alias) {
      setResolvedCompany(null);
      load(alias || clean);
      return;
    }
    setResolvingCompany(true);
    setError("");
    try {
      const response = await marketApi.companies(clean, 8);
      const items = response.items || [];
      const exact = items.find((item) => item.symbol.toUpperCase() === clean.toUpperCase());
      const company = exact || items[0];
      if (!company) {
        setError(`“${clean}” ke liye koi public company nahi mili. Company name ya valid ticker try karein.`);
        setCompanySearchOpen(true);
        return;
      }
      selectCompany(company);
    } catch {
      setError("Company name ko market ticker me resolve nahi kiya ja saka. Please retry.");
    } finally { setResolvingCompany(false); }
  };
  const prepareDocuments = async () => {
    if (ragPreparing || !documentPreparation?.supported) return;
    setRagPreparing(true); setRagPrepareError(""); setRagResult(null);
    try {
      await marketApi.prepareDocuments(symbol);
      const response = await marketApi.documents(symbol);
      setDocuments(response.items || []);
      setDocumentPreparation(response.preparation || documentPreparation);
    } catch {
      setRagPrepareError(`Official report for ${symbol} could not be indexed right now. Please retry.`);
    } finally { setRagPreparing(false); }
  };
  const askDocuments = async (value = ragQuestion) => {
    const clean = value.trim();
    if (!clean || ragLoading || documents.length === 0) return;
    setRagQuestion(clean); setRagLoading(true); setRagError(""); setRagResult(null);
    try { setRagResult(await marketApi.askDocuments({ symbol, question: clean, limit: 5 })); }
    catch { setRagError("Document retrieval is temporarily unavailable. Market analytics above remain independent."); }
    finally { setRagLoading(false); }
  };
  const send = async (value = question) => {
    const clean = value.trim();
    if (!clean || asking) return;
    const userMessage = { role: "user", content: clean };
    setMessages((current) => [...current, userMessage]); setQuestion(""); setAsking(true);
    try {
      const response = await marketApi.agent({ message: clean, symbol, recentMessages: messages.slice(-8) });
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

      <div className="intelligence-company-search">
        <form className="symbol-search" onSubmit={(event) => { event.preventDefault(); resolveAndLoad(); }}>
          <input value={draftSymbol} onChange={(event) => { setDraftSymbol(event.target.value); setResolvedCompany(null); setCompanySearchOpen(true); }} placeholder="Company name or ticker, e.g. Amazon, CSCO, RELIANCE.NS" aria-label="Company name or market ticker" autoComplete="off" />
          <button className="primary-button" disabled={loading || resolvingCompany}>{resolvingCompany ? "Finding company…" : loading ? "Researching…" : "Run research"}</button>
        </form>
        {companySearchOpen && draftSymbol.trim().length >= 2 && !draftSymbol.trim().startsWith("^") && <div className="company-search-results intelligence-search-results" aria-label="Matching companies">
          {searchingCompanies && <div className="company-search-state">Finding the correct market ticker…</div>}
          {!searchingCompanies && companySearchError && <div className="company-search-state error">{companySearchError}</div>}
          {!searchingCompanies && companyMatches.map((company) => <button type="button" key={company.symbol} onClick={() => selectCompany(company)}>
            <span><strong>{company.name}</strong><small>{company.symbol} · {company.exchange}</small></span>
            <span><b>Use this company →</b></span>
          </button>)}
        </div>}
        {resolvedCompany && resolvedCompany.symbol === symbol && <div className="resolved-company">Resolved to <strong>{resolvedCompany.name}</strong><span>{resolvedCompany.symbol} · {resolvedCompany.exchange}</span></div>}
      </div>
      <div className="preset-row">{presets.map(([value, label]) => <button key={value} className={symbol === value ? "sector active" : "sector"} onClick={() => { setResolvedCompany({ symbol: value, name: label, exchange: value.endsWith(".NS") ? "NSE" : value.startsWith("^") ? "Index" : "US" }); load(value); }}>{label}</button>)}</div>
      {result?.mode === "snapshot" && <div className="notice warning">Showing packaged verified research while the live backend refreshes this symbol in the background.</div>}
      {result?.mode === "cache" && <div className="notice warning">Showing the last verified browser research while the live backend reconnects.</div>}
      {error && <div className="notice error">{error}</div>}

      <OperationsSummary status={modelStatus} loading={modelStatusLoading} error={modelStatusError} />

      {analysis && <>
        <div className="analysis-hero">
          <div><span className="asset-label">{analysis.symbol}</span><h3>{resolvedCompany?.symbol === analysis.symbol ? resolvedCompany.name : analysis.name}</h3><p>Evidence as of {new Date(analysis.dataAsOf).toLocaleString("en-IN")}</p></div>
          <div className={`outlook outlook-${String(analysis.outlook).toLowerCase()}`}><small>Experimental outlook</small><strong>{analysis.outlook}</strong></div>
        </div>
        <div className="metric-grid">
          <Metric label="Probability up" value={`${analysis.probabilityUp}%`} hint={`${analysis.probabilityDown}% probability down`} />
          <Metric label="Expected range" value={`${formatNumber(analysis.expectedRange?.low)} – ${formatNumber(analysis.expectedRange?.high)}`} hint={analysis.expectedRange?.currency} />
          <Metric label="RSI (14)" value={formatNumber(analysis.technicalIndicators?.rsi14)} hint="Below 30 oversold · above 70 overbought" />
          <Metric label="Walk-forward score" value={`${analysis.model?.balancedAccuracy ?? analysis.model?.backtestAccuracy}%`} hint={`${analysis.model?.walkForwardFolds || 1} time-ordered folds · ${analysis.model?.quality} quality`} />
        </div>
        {!analysis.symbol.startsWith("^") && <CompanyFundamentalsPanel data={companyResearch} loading={companyResearchLoading} error={companyResearchError} />}
        {!analysis.symbol.startsWith("^") && <SectorPeerPanel data={peerComparison} loading={peerComparisonLoading} error={peerComparisonError} />}
        {analysis.riskBenchmark && <RiskBenchmarkPanel data={analysis.riskBenchmark} symbol={analysis.symbol} />}
        {localExplanation && <PredictionExplanation explanation={localExplanation} outlook={analysis.outlook} />}
        <ModelRegistryPanel status={modelStatus} loading={modelStatusLoading} error={modelStatusError} activeModel={analysis.model} />
        <ExperimentTrackingPanel data={experiments} loading={experimentsLoading} error={experimentsError} />
        {!symbol.startsWith("^") && <DocumentRagPanel
          symbol={symbol}
          documents={documents}
          documentsLoading={documentsLoading}
          preparation={documentPreparation}
          preparing={ragPreparing}
          prepareError={ragPrepareError}
          prepare={prepareDocuments}
          question={ragQuestion}
          setQuestion={setRagQuestion}
          result={ragResult}
          loading={ragLoading}
          error={ragError}
          ask={askDocuments}
        />}
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
        {modelComparisons.length > 0 && <ModelEvidence
          model={analysis.model}
          comparisons={modelComparisons}
          importance={featureImportance}
          audit={predictionAudit}
        />}
        <div className="notice warning"><strong>Research limitation:</strong> {analysis.disclaimer}</div>
      </>}

      <article className="agent-panel">
        <div className="panel-title"><div><p className="eyebrow">GROUNDED RESEARCH AGENT</p><h3>Ask using verified market evidence</h3></div><span>Verified data + calculations + probabilistic scenarios</span></div>
        <div className="suggested-row">
          {[
            "Aaj ke data se Nifty ka next-session scenario aur calculation samjhao",
            "15 July 2026 ko Nifty ka behaviour kya tha?",
            "Top gainers, losers aur market risk samjhao",
            `Why is ${symbol} outlook ${analysis?.outlook || "neutral"}?`
          ].map((item) => <button key={item} onClick={() => send(item)}>{item}</button>)}
        </div>
        <div className="chat-log">
          {messages.length === 0 && <div className="agent-empty">Ask about prices, factors, market breadth, model weakness or current headlines.</div>}
          {messages.map((message, index) => <div key={index} className={`chat-message ${message.role}`}><p>{message.content}</p>{message.meta && <>
            <small>{message.meta.llmStatus === "connected" && message.meta.llmAnswerAccepted ? "Gemini grounded" : message.meta.llmStatus === "grounding_fallback" ? "LLM checked · verified tool answer used" : "Verified tool fallback"}</small>
            {message.role === "assistant" && <AgentEvidenceTrace meta={message.meta} />}
          </>}</div>)}
          {asking && <div className="chat-message assistant"><p>Checking verified market evidence, calculations and model scenarios...</p></div>}
        </div>
        <form className="chat-form" onSubmit={(event) => { event.preventDefault(); send(); }}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about available market evidence…" /><button disabled={!question.trim() || asking}>Send</button></form>
      </article>
    </section>
  );
}

function Metric({ label, value, hint }) { return <article className="metric-card"><small>{label}</small><strong>{value}</strong><span>{hint}</span></article>; }

function CompanyFundamentalsPanel({ data, loading, error }) {
  if (loading) return <section className="fundamentals-panel fundamentals-state" aria-live="polite">
    <div><p className="eyebrow">COMPANY FUNDAMENTALS & PERFORMANCE</p><h3>Loading public company evidence…</h3></div>
    <span>Provider profile</span>
  </section>;
  if (error || !data) return <section className="fundamentals-panel fundamentals-state fundamentals-unavailable">
    <div><p className="eyebrow">COMPANY FUNDAMENTALS & PERFORMANCE</p><h3>Company evidence is temporarily unavailable</h3><p>{error || "Technical and model evidence above remains independent."}</p></div>
    <span>Optional evidence</span>
  </section>;

  const financials = data.financials || {};
  const valuation = financials.valuation || data.fundamentals || {};
  const profitability = financials.profitability || {};
  const growth = financials.growth || {};
  const balance = financials.balanceSheet || {};
  const cashFlow = financials.cashFlowAndIncome || {};
  const shareholder = financials.shareholderReturns || {};
  const currency = data.quote?.currency;
  const money = (value) => formatCompactMoney(value, currency);
  const ratio = (value) => value === null || value === undefined ? "—" : `${Number(value).toFixed(2)}x`;
  const percent = (value) => value === null || value === undefined ? "—" : `${Number(value).toFixed(1)}%`;
  const performance = data.performance || {};
  const range = data.range || {};
  const rangePosition = Number.isFinite(Number(range.currentPositionPercent)) ? Number(range.currentPositionPercent) : null;
  const companyWebsite = /^https?:\/\//i.test(data.website || "") ? data.website : null;
  const groups = [
    ["Valuation", [
      ["Market cap", money(valuation.marketCap)], ["Enterprise value", money(valuation.enterpriseValue)],
      ["Trailing P/E", ratio(valuation.trailingPE)], ["Forward P/E", ratio(valuation.forwardPE)],
      ["Price / book", ratio(valuation.priceToBook)], ["Price / sales", ratio(valuation.priceToSales)],
    ]],
    ["Profitability & growth", [
      ["Return on equity", percent(profitability.returnOnEquityPercent)], ["Profit margin", percent(profitability.profitMarginPercent)],
      ["Operating margin", percent(profitability.operatingMarginPercent)], ["Revenue growth", percent(growth.revenueGrowthPercent)],
      ["Earnings growth", percent(growth.earningsGrowthPercent)], ["Dividend yield", percent(shareholder.dividendYieldPercent ?? data.fundamentals?.dividendYield)],
      ["Payout ratio", percent(shareholder.payoutRatioPercent)],
    ]],
    ["Balance sheet & cash flow", [
      ["Total revenue", money(cashFlow.totalRevenue)], ["Net income", money(cashFlow.netIncomeToCommon)],
      ["EBITDA", money(cashFlow.ebitda)], ["Operating cash flow", money(cashFlow.operatingCashflow)],
      ["Free cash flow", money(cashFlow.freeCashflow)], ["Total cash", money(balance.totalCash)],
      ["Total debt", money(balance.totalDebt)], ["Debt / equity", percent(balance.debtToEquity)],
      ["Current ratio", ratio(balance.currentRatio)], ["Quick ratio", ratio(balance.quickRatio)],
    ]],
  ];

  return <section className="fundamentals-panel" aria-labelledby="fundamentals-title">
    <div className="fundamentals-heading">
      <div><p className="eyebrow">COMPANY FUNDAMENTALS & PERFORMANCE</p><h3 id="fundamentals-title">{data.name}</h3><p>{data.sector} · {data.industry} · {data.country}</p></div>
      {companyWebsite ? <a href={companyWebsite} target="_blank" rel="noreferrer">Company website ↗</a> : <span>Public profile</span>}
    </div>
    {data.summary && <p className="company-summary">{data.summary}</p>}
    <div className="company-performance-grid">
      <PerformanceMetric label="1 day" value={performance.oneDay} />
      <PerformanceMetric label="1 month" value={performance.oneMonth} />
      <PerformanceMetric label="3 months" value={performance.threeMonths} />
      <PerformanceMetric label="6 months" value={performance.sixMonths} />
      <PerformanceMetric label="1 year" value={performance.oneYear} />
    </div>
    <div className="company-range-card">
      <div><strong>52-week price position</strong><span>{rangePosition === null ? "Position unavailable" : `${rangePosition.toFixed(1)}% of observed range`}</span></div>
      <div className="company-range-track">{rangePosition !== null && <><i style={{ width: `${rangePosition}%` }} /><b style={{ left: `${rangePosition}%` }} /></>}</div>
      <div><span>{formatNumber(range.fiftyTwoWeekLow)} low</span><strong>{formatNumber(data.quote?.price)} current</strong><span>{formatNumber(range.fiftyTwoWeekHigh)} high</span></div>
    </div>
    <CompanyCatalystPanel data={data.catalysts} currency={currency} />
    <div className="fundamental-groups">{groups.map(([title, entries]) => <FundamentalGroup key={title} title={title} entries={entries} />)}</div>
    <CompanyNewsIntelligencePanel data={data.newsIntelligence} articles={data.news} />
    <p className="fundamentals-method"><strong>Source:</strong> {data.source}. Figures may use different reporting periods and are shown as provider evidence, not an accounting audit or investment recommendation.{data.dataAsOf ? ` Data as of ${new Date(data.dataAsOf).toLocaleString("en-IN")}.` : ""}</p>
  </section>;
}

function PerformanceMetric({ label, value }) {
  const numeric = value === null || value === undefined ? null : Number(value);
  return <article className={numeric === null ? "" : numeric >= 0 ? "positive" : "negative"}><small>{label}</small><strong>{numeric === null ? "—" : `${numeric > 0 ? "+" : ""}${numeric.toFixed(1)}%`}</strong></article>;
}

function FundamentalGroup({ title, entries }) {
  return <article><h4>{title}</h4><dl>{entries.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl></article>;
}

function CompanyNewsIntelligencePanel({ data, articles = [] }) {
  if (!data || data.status !== "available") return <section className="company-news-intelligence news-intelligence-unavailable">
    <div className="news-intelligence-heading"><div><p className="eyebrow">COMPANY NEWS INTELLIGENCE</p><h4>No recent headline evidence available</h4></div><span>No tone inferred</span></div>
    <p>The provider returned no recent company headlines, so FinTrack does not invent sentiment, themes or publisher coverage.</p>
  </section>;

  const distribution = data.distribution || {};
  const articleCount = Number(data.articleCount || articles.length || 0);
  const percentage = (value) => articleCount ? Math.max(0, (Number(value || 0) / articleCount) * 100) : 0;
  const toneClass = (label) => String(label || "mixed/neutral") === "mixed/neutral" ? "neutral" : String(label).toLowerCase();
  const label = (value) => String(value || "mixed/neutral").replace("mixed/neutral", "Mixed / neutral").replace(/^./, (character) => character.toUpperCase());
  const formatDate = (value, options = { day: "numeric", month: "short", year: "numeric" }) => {
    if (!value) return "Date unavailable";
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? "Date unavailable" : parsed.toLocaleDateString("en-IN", options);
  };
  const visibleArticles = articles.slice(0, 6);
  const visibleDays = (data.dailyTone || []).slice(-5);
  const topSources = (data.topSources || []).map((item) => `${item.publisher} (${item.articleCount})`).join(" · ");

  return <section className="company-news-intelligence" aria-labelledby="company-news-intelligence-title">
    <div className="news-intelligence-heading">
      <div><p className="eyebrow">COMPANY NEWS INTELLIGENCE</p><h4 id="company-news-intelligence-title">Headline tone, themes and source coverage</h4></div>
      <span>Separate from FinTrack ML</span>
    </div>
    <div className="news-intelligence-metrics">
      <article className={`tone-${toneClass(data.sentimentLabel)}`}><small>Aggregate headline tone</small><strong>{label(data.sentimentLabel)}</strong><span>{Number(data.sentimentScore || 0) >= 0 ? "+" : ""}{Number(data.sentimentScore || 0).toFixed(3)} score</span></article>
      <article><small>Coverage</small><strong>{articleCount} headlines</strong><span>{label(data.coverage)} evidence breadth</span></article>
      <article><small>Source diversity</small><strong>{data.sourceCount || 0} publishers</strong><span>{topSources || "Publisher names unavailable"}</span></article>
      <article><small>Freshness</small><strong>{label(data.freshness)}</strong><span>{formatDate(data.latestPublishedAt)}</span></article>
    </div>
    <div className="news-evidence-layout">
      <article className="news-distribution-card">
        <div className="news-card-heading"><strong>Tone distribution</strong><span>Title-only classification</span></div>
        <div className="news-tone-bar" aria-label={`${distribution.positive || 0} positive, ${distribution["mixed/neutral"] || 0} mixed or neutral, ${distribution.negative || 0} negative headlines`}>
          <i className="positive" style={{ width: `${percentage(distribution.positive)}%` }} />
          <i className="neutral" style={{ width: `${percentage(distribution["mixed/neutral"])}%` }} />
          <i className="negative" style={{ width: `${percentage(distribution.negative)}%` }} />
        </div>
        <div className="news-tone-legend"><span className="positive">{distribution.positive || 0} positive</span><span>{distribution["mixed/neutral"] || 0} mixed/neutral</span><span className="negative">{distribution.negative || 0} negative</span></div>
        <div className="news-theme-list">{(data.themes || []).map((item) => <span key={item.theme}>{item.theme}<b>{item.articleCount}</b></span>)}</div>
      </article>
      <article className="news-timeline-card">
        <div className="news-card-heading"><strong>Daily headline tone</strong><span>Latest returned dates</span></div>
        {visibleDays.length ? <div className="news-daily-tone">{visibleDays.map((day) => {
          const score = Number(day.sentimentScore || 0);
          return <div key={day.date}><span>{formatDate(`${day.date}T00:00:00`, { day: "numeric", month: "short" })}</span><div><i /><b className={`tone-${toneClass(day.sentimentLabel)}`} style={{ left: `${Math.max(0, Math.min(100, (score + 1) * 50))}%` }} /></div><strong>{score >= 0 ? "+" : ""}{score.toFixed(2)}</strong></div>;
        })}</div> : <p>Publisher dates were unavailable for the returned headlines.</p>}
      </article>
    </div>
    <div className="news-headline-evidence">
      <div className="news-card-heading"><strong>Dated publisher evidence</strong><span>Open the original source to verify context</span></div>
      {visibleArticles.length ? <div>{visibleArticles.map((item, index) => {
        const content = <><div><span className={`headline-tone tone-${toneClass(item.sentimentLabel)}`}>{label(item.sentimentLabel)}</span><small>{(item.themes || []).slice(0, 2).join(" · ") || "General company update"}</small></div><strong>{item.title}</strong><span>{item.publisher} · {formatDate(item.publishedAt)}</span></>;
        return item.url ? <a key={`${item.title}-${index}`} href={item.url} target="_blank" rel="noreferrer">{content}<b aria-hidden="true">↗</b></a> : <article key={`${item.title}-${index}`}>{content}</article>;
      })}</div> : <p>No recent publisher headlines were returned.</p>}
    </div>
    <p className="news-intelligence-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function CompanyCatalystPanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="catalyst-panel catalyst-unavailable">
    <div className="catalyst-heading"><div><p className="eyebrow">UPCOMING CATALYSTS & ANALYST CONSENSUS</p><h4>No provider catalyst evidence available</h4></div><span>Not estimated</span></div>
    <p>No calendar event, analyst target or reported EPS-surprise history was returned for this listing.</p>
  </section>;
  const consensus = data.analystConsensus || {};
  const estimates = data.nextEarningsEstimate || {};
  const summary = data.surpriseSummary || {};
  const events = data.events || [];
  const history = data.earningsHistory || [];
  const formatDate = (value) => {
    if (!value) return "Date unavailable";
    const parsed = new Date(`${value}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  const targetValues = [consensus.targetLow, consensus.targetMean, consensus.targetHigh, consensus.currentPrice]
    .map(Number).filter(Number.isFinite);
  const targetMin = targetValues.length ? Math.min(...targetValues) : null;
  const targetMax = targetValues.length ? Math.max(...targetValues) : null;
  const targetPosition = (value) => {
    if (value === null || value === undefined || targetMin === null || targetMax === null || targetMax === targetMin) return null;
    return Math.max(0, Math.min(100, ((Number(value) - targetMin) / (targetMax - targetMin)) * 100));
  };
  const currentPosition = targetPosition(consensus.currentPrice);
  const meanPosition = targetPosition(consensus.targetMean);
  const gap = consensus.targetGapPercent;
  return <section className="catalyst-panel" aria-labelledby="company-catalyst-title">
    <div className="catalyst-heading">
      <div><p className="eyebrow">UPCOMING CATALYSTS & ANALYST CONSENSUS</p><h4 id="company-catalyst-title">Calendar events and external expectations</h4></div>
      <span>Separate from FinTrack ML</span>
    </div>
    <div className="catalyst-events">
      {events.length ? events.map((event) => <article key={`${event.type}-${event.date}`} className={`event-${event.status}`}>
        <small>{event.status}</small><strong>{event.label}</strong><span>{formatDate(event.date)}</span>
      </article>) : <p>No dated corporate event was returned.</p>}
    </div>
    <div className="catalyst-evidence-grid">
      <article className="analyst-consensus-card">
        <div className="analyst-card-heading"><div><small>Third-party analyst consensus</small><strong>{consensus.recommendation || "Not available"}</strong></div><span>{consensus.analystCount || 0} analysts</span></div>
        <div className="target-metrics">
          <div><small>Low target</small><strong>{formatCompactMoney(consensus.targetLow, currency)}</strong></div>
          <div><small>Mean target</small><strong>{formatCompactMoney(consensus.targetMean, currency)}</strong></div>
          <div><small>High target</small><strong>{formatCompactMoney(consensus.targetHigh, currency)}</strong></div>
        </div>
        {targetMin !== null && targetMax !== null && targetMax > targetMin ? <>
          <div className="analyst-target-track">
            <i className="current-price-marker" style={{ left: `${currentPosition}%` }} title="Current price" />
            <i className="mean-target-marker" style={{ left: `${meanPosition}%` }} title="Mean analyst target" />
          </div>
          <div className="analyst-target-legend"><span>● Current {formatCompactMoney(consensus.currentPrice, currency)}</span><span>◆ Mean target</span></div>
        </> : <p className="target-unavailable">Analyst target range was not returned.</p>}
        <p className="target-gap"><strong>{gap === null || gap === undefined ? "—" : `${Number(gap) > 0 ? "+" : ""}${Number(gap).toFixed(1)}%`}</strong> mean-target gap versus current price—not a forecast guarantee.</p>
      </article>
      <article className="earnings-evidence-card">
        <div className="earnings-card-heading"><div><small>Recent reported EPS</small><strong>{summary.reportedQuarters || 0} quarters available</strong></div><span>{summary.beats || 0} beats · {summary.misses || 0} misses</span></div>
        <div className="next-estimate-strip">
          <div><small>Next EPS average</small><strong>{estimates.epsAverage ?? "—"}</strong></div>
          <div><small>Revenue average</small><strong>{formatCompactMoney(estimates.revenueAverage, currency)}</strong></div>
          <div><small>Average surprise</small><strong>{summary.averageSurprisePercent === null || summary.averageSurprisePercent === undefined ? "—" : `${summary.averageSurprisePercent}%`}</strong></div>
        </div>
        {history.length ? <div className="earnings-history-list">{history.map((item) => <div key={item.date}>
          <span>{formatDate(item.date)}</span><small>Est. {item.epsEstimate ?? "—"} · Actual {item.reportedEps ?? "—"}</small><strong className={Number(item.surprisePercent) >= 0 ? "positive" : "negative"}>{item.surprisePercent === null || item.surprisePercent === undefined ? "—" : `${Number(item.surprisePercent) > 0 ? "+" : ""}${item.surprisePercent}%`}</strong>
        </div>)}</div> : <p className="target-unavailable">No reported EPS-surprise history was returned.</p>}
      </article>
    </div>
    <p className="catalyst-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function RiskBenchmarkPanel({ data, symbol }) {
  if (!data || data.status === "unavailable") return <section className="risk-benchmark-panel risk-unavailable">
    <div className="risk-heading"><div><p className="eyebrow">RISK & BENCHMARK INTELLIGENCE</p><h3>Historical risk evidence unavailable</h3></div><span>Provider unavailable</span></div>
    <p className="risk-caveat">{data?.message || "The prediction above remains separate from this optional historical comparison."}</p>
  </section>;
  const asset = data.asset || {};
  const comparison = data.comparison;
  const benchmark = data.benchmark;
  const signed = (value) => value === null || value === undefined ? "—" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)} pp`;
  return <section className="risk-benchmark-panel" aria-labelledby="risk-benchmark-title">
    <div className="risk-heading">
      <div><p className="eyebrow">RISK & BENCHMARK INTELLIGENCE</p><h3 id="risk-benchmark-title">How has {symbol} behaved versus the broad market?</h3><p>{data.period} · close-to-close evidence</p></div>
      <span className={`risk-band risk-${asset.riskBand || "contained"}`}>{asset.riskBand || "historical"} risk</span>
    </div>
    <div className="risk-layout">
      <div className="risk-chart-card">
        <div className="risk-chart-title"><strong>Normalized performance</strong><small>Period start = 100</small></div>
        <BenchmarkChart history={data.normalizedHistory || []} symbol={symbol} benchmark={benchmark} />
      </div>
      <div className="risk-metric-grid">
        <RiskMetric label="Period return" value={formatPercent(asset.periodReturnPercent)} hint={`${asset.observations || 0} daily returns`} />
        <RiskMetric label="Annualized volatility" value={formatPercent(asset.annualizedVolatilityPercent)} hint="Dispersion, not direction" />
        <RiskMetric label="Maximum drawdown" value={formatPercent(asset.maxDrawdownPercent)} hint="Largest peak-to-trough fall" />
        <RiskMetric label="95% historical VaR" value={formatPercent(asset.historicalVar95Percent)} hint="Observed one-day loss threshold" />
        <RiskMetric label={benchmark ? `Beta vs ${benchmark.symbol}` : "Beta"} value={comparison?.beta ?? "—"} hint={benchmark ? `Correlation ${comparison?.correlation ?? "—"}` : "No self-comparison for an index"} />
        <RiskMetric label="Relative return" value={signed(comparison?.relativeReturnPoints)} hint={comparison ? `${comparison.relativePerformance} vs ${benchmark?.name}` : "Broad benchmark not applicable"} />
      </div>
    </div>
    <div className="risk-evidence-strip">
      <span><strong>{formatPercent(asset.positiveSessionsPercent)}</strong> positive sessions</span>
      <span><strong>{asset.returnToVolatility ?? "—"}</strong> return/volatility</span>
      <span><strong>{comparison ? formatPercent(comparison.trackingErrorPercent) : "—"}</strong> tracking error</span>
      <span><strong>{benchmark?.name || "Standalone index"}</strong> benchmark</span>
    </div>
    <p className="risk-caveat"><strong>Method:</strong> {data.method} {data.caveat}</p>
  </section>;
}

function RiskMetric({ label, value, hint }) {
  return <article><small>{label}</small><strong>{value}</strong><span>{hint}</span></article>;
}

function SectorPeerPanel({ data, loading, error }) {
  if (loading) return <section className="peer-panel peer-state" aria-live="polite">
    <div><p className="eyebrow">SECTOR PEER INTELLIGENCE</p><h3>Discovering comparable companies…</h3></div>
    <span>Dynamic screener</span>
  </section>;
  if (error || !data || data.status !== "available") return <section className="peer-panel peer-state peer-unavailable">
    <div><p className="eyebrow">SECTOR PEER INTELLIGENCE</p><h3>Peer evidence is not available for this listing</h3><p>{error || data?.message || "The primary market analysis above remains available."}</p></div>
    <span>Optional evidence</span>
  </section>;

  const selected = data.selected || {};
  const medians = data.peerMedians || {};
  const comparison = data.comparison || {};
  const rows = [selected, ...(data.peers || [])];
  const metricValue = (value, suffix = "") => value === null || value === undefined ? "—" : `${Number(value).toFixed(2)}${suffix}`;
  return <section className="peer-panel" aria-labelledby="sector-peer-title">
    <div className="peer-heading">
      <div><p className="eyebrow">SECTOR PEER INTELLIGENCE</p><h3 id="sector-peer-title">How does {selected.name || selected.symbol} compare with similar companies?</h3><p>{data.sector} · {data.region} · dynamically discovered by comparable market size</p></div>
      <span>{data.peers.length} live peers</span>
    </div>
    <div className="peer-summary-grid">
      <PeerSummary label="Market-cap rank" value={selected.marketCapRank ? `#${selected.marketCapRank} of ${rows.length}` : "—"} hint={comparison.marketCap} />
      <PeerSummary label="Trailing P/E" value={metricValue(selected.trailingPE, "x")} hint={`${comparison.trailingPE} · median ${metricValue(medians.trailingPE, "x")}`} />
      <PeerSummary label="Price / book" value={metricValue(selected.priceToBook, "x")} hint={`${comparison.priceToBook} · median ${metricValue(medians.priceToBook, "x")}`} />
      <PeerSummary label="52-week return" value={metricValue(selected.fiftyTwoWeekReturnPercent, "%")} hint={`${comparison.fiftyTwoWeekReturnPercent} · median ${metricValue(medians.fiftyTwoWeekReturnPercent, "%")}`} />
    </div>
    <div className="peer-table-wrap">
      <table className="peer-table">
        <thead><tr><th>Company</th><th>Market cap</th><th>P/E</th><th>P/B</th><th>Dividend</th><th>52-week</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.symbol} className={row.isSelected ? "selected" : ""}>
          <td><strong>{row.name}</strong><small>{row.symbol} · {row.exchange}{row.isSelected ? " · Selected" : ""}</small></td>
          <td>{formatCompactMoney(row.marketCap, row.currency || selected.currency)}</td>
          <td>{metricValue(row.trailingPE, "x")}</td>
          <td>{metricValue(row.priceToBook, "x")}</td>
          <td>{metricValue(row.dividendYield, "%")}</td>
          <td className={Number(row.fiftyTwoWeekReturnPercent) >= 0 ? "positive" : "negative"}>{metricValue(row.fiftyTwoWeekReturnPercent, "%")}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="peer-method"><strong>Method:</strong> {data.method} Provider coverage: {data.providerCoverage || rows.length} listings. {data.disclaimer}</p>
  </section>;
}

function PeerSummary({ label, value, hint }) {
  return <article><small>{label}</small><strong>{value}</strong><span>{hint || "not available"}</span></article>;
}

function BenchmarkChart({ history, symbol, benchmark }) {
  const rows = history.filter((item) => Number.isFinite(Number(item.asset)));
  if (rows.length < 2) return <div className="risk-chart-empty">Comparison history unavailable</div>;
  const numericValue = (value) => value === null || value === undefined ? null : Number(value);
  const values = rows.flatMap((item) => [numericValue(item.asset), numericValue(item.benchmark)]).filter(Number.isFinite);
  const min = Math.min(...values); const max = Math.max(...values); const range = max - min || 1;
  const pathFor = (key) => rows
    .filter((item) => Number.isFinite(numericValue(item[key])))
    .map((item, index, points) => `${(index / Math.max(points.length - 1, 1)) * 100},${88 - ((Number(item[key]) - min) / range) * 72}`)
    .join(" ");
  const assetPath = pathFor("asset");
  const benchmarkPath = pathFor("benchmark");
  return <div className="benchmark-chart">
    <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`${symbol} normalized performance${benchmark ? ` versus ${benchmark.name}` : ""}`}>
      <line x1="0" x2="100" y1="88" y2="88" className="risk-gridline" />
      <line x1="0" x2="100" y1="52" y2="52" className="risk-gridline" />
      <line x1="0" x2="100" y1="16" y2="16" className="risk-gridline" />
      {benchmarkPath && <polyline points={benchmarkPath} className="benchmark-line" />}
      <polyline points={assetPath} className="asset-line" />
    </svg>
    <div className="risk-chart-legend"><span className="asset-legend">{symbol}</span>{benchmark && <span className="benchmark-legend">{benchmark.name}</span>}<small>{formatNumber(min)} – {formatNumber(max)}</small></div>
  </div>;
}

function AgentEvidenceTrace({ meta }) {
  const trace = meta.toolTrace || [];
  const citations = meta.citations || [];
  if (trace.length === 0) return null;
  return <details className="agent-evidence-trace">
    <summary>Agent plan · {trace.length} read-only tools · evidence trace</summary>
    <div className="agent-plan-intents">
      {(meta.agentPlan?.intents || []).map((intent) => <span key={intent}>{intent.replaceAll("_", " ")}</span>)}
    </div>
    <ol>{trace.map((item) => <li key={`${item.step}-${item.tool}`} className={`trace-${item.status}`}>
      <span>{item.step}</span>
      <div><strong>{item.label || item.tool.replaceAll("_", " ")}</strong><small>{item.status.replaceAll("_", " ")} · {item.evidenceCount || 0} evidence · {item.source || "FinTrack"}</small>{item.message && <em>{item.message}</em>}</div>
    </li>)}</ol>
    {citations.length > 0 && <div className="agent-citation-list"><strong>Document citations</strong>{citations.map((citation) => <a key={`${citation.citation}-${citation.page}`} href={citation.sourceUrl} target="_blank" rel="noreferrer">
      [{citation.citation} p.{citation.page}] {citation.title}
    </a>)}</div>}
    <p>Planner: {meta.agentPlan?.planner || "legacy"} · tool mutation disabled · LLM does not choose tools</p>
  </details>;
}

function OperationsSummary({ status, loading, error }) {
  const dataOps = status?.dataOperations;
  const drift = status?.driftMonitoring;
  const retraining = status?.retrainingPolicy;
  const schema = dataOps?.storage?.schema;
  const checking = loading || (!status && !error);
  const storageLabel = dataOps?.storage?.durableAcrossDeploys ? "Durable PostgreSQL" : "Instance storage";
  const freshness = String(dataOps?.freshness || "provider_only").replaceAll("_", " ");
  const driftLabel = String(drift?.status || "collecting evidence").replaceAll("_", " ");

  return <aside className="operations-summary" aria-labelledby="operations-summary-title">
    <div className="operations-summary-copy">
      <span className="operations-summary-kicker">NEW · DATA & MLOPS STATUS</span>
      <strong id="operations-summary-title">Operational checks are now visible here</strong>
      <small>{checking
        ? "Loading data freshness, database and model-monitoring evidence…"
        : error
          ? error
          : `${dataOps?.storedBars || 0} validated daily bars · ${freshness} · ${storageLabel}`}</small>
    </div>
    <div className="operations-summary-chips" aria-label="Operational status summary">
      <span>Data: {checking ? "checking" : freshness}</span>
      <span>Schema: {schema ? `v${schema.currentVersion}/${schema.expectedVersion}` : "checking"}</span>
      <span>Drift: {checking ? "checking" : driftLabel}</span>
      <span>Auto retraining: {checking ? "checking" : retraining?.automaticRetraining ? "on" : "off"}</span>
      <span>API: {checking ? "checking" : status?._delivery?.gateway === "spring-boot" ? "Spring Boot" : "FastAPI direct"}</span>
    </div>
    <a className="operations-summary-link" href="#model-operations">View full monitoring ↓</a>
  </aside>;
}

function PredictionExplanation({ explanation, outlook }) {
  const contributions = explanation?.contributions || [];
  const path = explanation?.probabilityPath || {};
  const maxImpact = Math.max(
    ...contributions.map((item) => Math.abs(Number(item.adjustedProbabilityImpactPoints) || 0)),
    0.1
  );
  const pathSteps = [
    ["Raw ML", path.rawTechnicalProbabilityUp, "Model output"],
    ["Reliability adjusted", path.reliabilityAdjustedProbabilityUp, "Walk-forward skill"],
    ["News overlay", path.newsAdjustmentPoints, "probability points", true],
    ["Macro overlay", path.macroAdjustmentPoints, "probability points", true],
    ["Final outlook", path.finalProbabilityUp, outlook]
  ];

  return <section className="prediction-explanation" aria-labelledby="prediction-explanation-title">
    <div className="prediction-explanation-heading">
      <div>
        <p className="eyebrow">LOCAL PREDICTION EXPLAINABILITY</p>
        <h3 id="prediction-explanation-title">Why is this outlook {String(outlook).toLowerCase()}?</h3>
        <p>{explanation.summary}</p>
      </div>
      <span>Current values vs training reference</span>
    </div>
    <div className="probability-path" aria-label="Probability calculation path">
      {pathSteps.map(([label, value, hint, signed], index) => <article key={label}>
        <small>{label}</small>
        <strong>{signed && Number(value) > 0 ? "+" : ""}{value ?? "—"}{signed ? " pp" : "%"}</strong>
        <span>{hint}</span>
        {index < pathSteps.length - 1 && <b aria-hidden="true">→</b>}
      </article>)}
    </div>
    <div className="local-impact-grid">
      {contributions.map((item) => {
        const impact = Number(item.adjustedProbabilityImpactPoints) || 0;
        const width = `${Math.max(2, Math.abs(impact) / maxImpact * 50)}%`;
        return <article className={`local-impact ${item.direction}`} key={item.feature}>
          <div className="local-impact-title"><strong>{item.label}</strong><span>{impact > 0 ? "+" : ""}{impact.toFixed(2)} pp</span></div>
          <small>Current {item.currentDisplay} · reference {item.referenceDisplay}</small>
          <div className="local-impact-track" aria-label={`${item.label} ${item.direction.replaceAll("_", " ")}`}>
            <i />
            <b style={impact >= 0 ? { left: "50%", width } : { right: "50%", width }} />
          </div>
        </article>;
      })}
    </div>
    <p className="explanation-method"><strong>{explanation.method}</strong> Reference: {explanation.referenceSource}. {explanation.caveat}</p>
  </section>;
}

function ModelRegistryPanel({ status, loading, error, activeModel }) {
  const approved = status?.approvedModel;
  const latest = status?.latestModelRun;
  const monitoring = status?.predictionMonitoring;
  const drift = status?.driftMonitoring;
  const retraining = status?.retrainingPolicy;
  const dataOps = status?.dataOperations;
  const rolling20 = monitoring?.rollingQuality?.windows?.find((item) => item.window === 20);
  const driftFeatures = (drift?.features || []).filter((item) => item.psi !== null && item.psi !== undefined).slice(0, 4);
  const approvedServing = status?.servingMode === "approved_artifact";
  return <section id="model-operations" className={`registry-panel ${approvedServing ? "registry-approved" : "registry-fallback"}`} aria-labelledby="registry-title">
    <div className="registry-heading">
      <div>
        <p className="eyebrow">MODEL DEPLOYMENT & MONITORING</p>
        <h3 id="registry-title">{approvedServing ? "Approved offline model is serving" : "Runtime fallback is serving"}</h3>
        <p>{approvedServing
          ? "The prediction uses a checksummed artifact that passed an untouched chronological holdout."
          : "No approved artifact is available for this symbol; the existing request-time experiment remains active."}</p>
      </div>
      <span className={`registry-status ${approvedServing ? "approved" : "fallback"}`}>{approvedServing ? "Approved artifact" : "Fallback mode"}</span>
    </div>
    {loading && <div className="registry-state">Loading persistent model provenance…</div>}
    {!loading && error && <div className="registry-state warning">{error}</div>}
    {!loading && !error && <div className="registry-metrics">
      <ValidationStat label="Serving model" value={approved?.model || activeModel?.type || "Runtime experiment"} />
      <ValidationStat label="Final holdout" value={approved ? `${approved.holdout.balancedAccuracy}% balanced` : "Not approved"} />
      <ValidationStat label="Holdout ROC AUC" value={approved?.holdout?.rocAuc ? `${approved.holdout.rocAuc}%` : "—"} />
      <ValidationStat label="Dataset version" value={approved?.datasetVersion || latest?.datasetVersion || "Runtime data"} />
      <ValidationStat label="Stored predictions" value={monitoring?.totalStored ?? 0} />
      <ValidationStat label="Observed accuracy" value={monitoring?.observedAccuracy === null || monitoring?.observedAccuracy === undefined ? "Awaiting outcomes" : `${monitoring.observedAccuracy}%`} />
    </div>}
    {!loading && !error && !approved && latest && <div className="registry-rejection">
      <strong>Latest offline run: {latest.status}</strong>
      <span>{latest.model} · holdout balanced accuracy {latest.holdout.balancedAccuracy}% · ROC AUC {latest.holdout.rocAuc ?? "—"}%</span>
      <small>A weak or unapproved model is never promoted automatically.</small>
    </div>}
    {!loading && !error && monitoring?.records?.length > 0 && <div className="registry-audit">
      {monitoring.records.slice(0, 4).map((item) => <article key={item.id}>
        <span>{item.modelDataDate}</span>
        <strong>{item.outlook} · {Number(item.probabilityUp).toFixed(1)}% up</strong>
        <small>{item.status === "evaluated" ? `Actual ${item.actualDirection} · ${item.correct ? "correct" : "not correct"}` : "Awaiting next session"}</small>
      </article>)}
    </div>}
    {!loading && !error && <div className={`monitoring-decision monitoring-${retraining?.severity || "neutral"}`}>
      <div className="monitoring-decision-heading">
        <div>
          <span className="monitoring-kicker">DRIFT & RETRAINING POLICY</span>
          <strong>{String(retraining?.decision || "collecting_evidence").replaceAll("_", " ")}</strong>
        </div>
        <span className={`monitoring-pill ${drift?.status || "not_applicable"}`}>{String(drift?.status || "not applicable").replaceAll("_", " ")}</span>
      </div>
      <div className="monitoring-policy-grid">
        <ValidationStat label="Recent feature rows" value={`${drift?.recentObservations || 0}/${drift?.minimumObservations || 20}`} />
        <ValidationStat label="Mean PSI" value={drift?.meanPsi ?? "Collecting"} />
        <ValidationStat label="Maximum PSI" value={drift?.maxPsi ?? "Collecting"} />
        <ValidationStat label="Rolling 20 accuracy" value={rolling20?.accuracy === null || rolling20?.accuracy === undefined ? `${rolling20?.evaluated || 0}/20 outcomes` : `${rolling20.accuracy}%`} />
        <ValidationStat label="Artifact data age" value={retraining?.artifactDataAgeDays === undefined ? "No approved run" : `${retraining.artifactDataAgeDays} days`} />
        <ValidationStat label="Auto retraining" value={retraining?.automaticRetraining ? "Enabled" : "Disabled - approval gate"} />
      </div>
      {driftFeatures.length > 0 && <div className="drift-feature-list">{driftFeatures.map((item) => <span key={item.feature} className={`drift-feature ${item.status}`}>
        <strong>{item.feature.replaceAll("_", " ")}</strong><small>PSI {item.psi} - {item.status}</small>
      </span>)}</div>}
      <div className="monitoring-explanation">
        <strong>{retraining?.reasons?.[0] || drift?.recommendation || "Monitoring evidence is being collected."}</strong>
        <span>{retraining?.nextStep || drift?.recommendation}</span>
      </div>
    </div>}
    {!loading && !error && <div className={`data-operations-card data-${dataOps?.freshness || "provider_only"}`}>
      <div className="monitoring-decision-heading">
        <div>
          <span className="monitoring-kicker">DATA FRESHNESS & SCHEDULED OPERATIONS</span>
          <strong>{String(dataOps?.freshness || "provider_only").replaceAll("_", " ")}</strong>
        </div>
        <span className={`monitoring-pill ${dataOps?.freshness || "provider_only"}`}>
          {dataOps?.storage?.durableAcrossDeploys ? "Durable PostgreSQL" : "Instance storage"}
        </span>
      </div>
      <div className="monitoring-policy-grid">
        <ValidationStat label="Stored daily bars" value={dataOps?.storedBars ?? 0} />
        <ValidationStat label="Latest session" value={dataOps?.latestSession || "Provider only"} />
        <ValidationStat label="Data age" value={dataOps?.calendarAgeDays === null || dataOps?.calendarAgeDays === undefined ? "Not persisted" : `${dataOps.calendarAgeDays} days`} />
        <ValidationStat label="Offline training data" value={dataOps?.offlineTrainingReady ? "Ready" : `${dataOps?.storedBars || 0}/${dataOps?.minimumTrainingBars || 180} bars`} />
        <ValidationStat label="Scheduled refresh" value={dataOps?.scheduledRefreshEligible ? "Eligible" : "Seeds after research"} />
        <ValidationStat label="Last pipeline run" value={dataOps?.pipeline?.status || "Not run"} />
        <ValidationStat label="Database schema" value={dataOps?.storage?.schema ? `v${dataOps.storage.schema.currentVersion}/${dataOps.storage.schema.expectedVersion}` : "Checking"} />
        <ValidationStat label="Backup policy" value={dataOps?.storage?.backup?.configured ? dataOps.storage.backup.policy : "Not configured"} />
      </div>
      <div className="monitoring-explanation">
        <strong>{dataOps?.message || "Open research will seed validated persistent history for this symbol."}</strong>
        <span>Public search remains unrestricted. The background universe grows from companies actually researched, not from a fixed five-company list.</span>
      </div>
    </div>}
  </section>;
}

function ExperimentTrackingPanel({ data, loading, error }) {
  const runs = data?.runs || [];
  const deepRun = runs.find((run) => run.deepLearningExperiment);
  const deep = deepRun?.deepLearningExperiment;
  return <section className="experiment-panel" aria-labelledby="experiment-tracking-title">
    <div className="experiment-heading">
      <div>
        <p className="eyebrow">MLFLOW EXPERIMENT TRACKING</p>
        <h3 id="experiment-tracking-title">Reproducible offline run comparison</h3>
        <p>Training parameters, chronological holdout metrics, naive baselines, dataset versions and model artifacts are logged together.</p>
      </div>
      <span className={`experiment-status ${data?.trackedCount ? "tracked" : "empty"}`}>
        {loading ? "Loading…" : `${data?.trackedCount || 0}/${data?.count || 0} MLflow tracked`}
      </span>
    </div>
    {loading && <div className="experiment-state">Loading experiment lineage…</div>}
    {!loading && error && <div className="experiment-state warning">{error}</div>}
    {!loading && !error && runs.length === 0 && <div className="experiment-state">
      No offline experiment has been trained for this symbol yet. Runtime predictions remain clearly separated from tracked model artifacts.
    </div>}
    {!loading && !error && runs.length > 0 && <div className="experiment-table-wrap"><table className="experiment-table">
      <thead><tr><th>Run</th><th>Model</th><th>Status</th><th>Holdout balanced</th><th>ROC AUC</th><th>Brier</th><th>Best baseline</th><th>Tracking</th></tr></thead>
      <tbody>{runs.map((run) => <tr key={run.modelRunId}>
        <td><strong>{run.modelRunId.slice(0, 8)}</strong><small>{new Date(run.createdAt).toLocaleDateString("en-IN")}</small></td>
        <td><strong>{run.model}</strong><small>{run.trainingRows} train · {run.holdoutRows} holdout</small></td>
        <td><span className={`experiment-run-status status-${run.status}`}>{run.status}</span></td>
        <td>{run.holdoutBalancedAccuracy}%</td>
        <td>{run.holdoutRocAuc === null ? "—" : `${run.holdoutRocAuc}%`}</td>
        <td>{run.holdoutBrierScore}</td>
        <td>{run.bestBaselineBalancedAccuracy === null ? "—" : `${run.bestBaselineBalancedAccuracy}%`}</td>
        <td><strong>{run.tracking.status === "logged" ? "MLflow" : "Legacy"}</strong><small>{run.tracking.runId ? run.tracking.runId.slice(0, 8) : run.tracking.status}</small></td>
      </tr>)}</tbody>
    </table></div>}
    {!loading && !error && deep && <article className="deep-learning-comparison" aria-labelledby="deep-learning-title">
      <div className="deep-learning-heading">
        <div><p className="eyebrow">PYTORCH DEEP-LEARNING EXPERIMENT</p><h4 id="deep-learning-title">Classical model vs seeded MLP</h4></div>
        <span>Experimental - not serving</span>
      </div>
      <div className="deep-learning-grid">
        <ValidationStat label="Classical holdout" value={`${deepRun.model} - ${deepRun.holdoutBalancedAccuracy}%`} />
        <ValidationStat label="PyTorch holdout" value={deep.holdoutBalancedAccuracy === null ? "Unavailable" : `${deep.holdoutBalancedAccuracy}% balanced`} />
        <ValidationStat label="MLP ROC AUC / Brier" value={`${deep.holdoutRocAuc === null ? "-" : `${deep.holdoutRocAuc}%`} / ${deep.holdoutBrierScore ?? "-"}`} />
        <ValidationStat label="Delta vs classical" value={deep.balancedAccuracyDeltaVsClassical === null ? "-" : `${deep.balancedAccuracyDeltaVsClassical > 0 ? "+" : ""}${deep.balancedAccuracyDeltaVsClassical} pp`} />
        <ValidationStat label="Early stopping" value={`Best ${deep.earlyStopping.bestEpoch || "-"} / trained ${deep.earlyStopping.epochsTrained || "-"}`} />
        <ValidationStat label="Reproducibility" value={`Seed ${deep.seed} - ${deep.device} - ${deep.frameworkVersion || deep.framework}`} />
      </div>
      <p className="deep-learning-policy">Final holdout is evaluation-only. The MLP uses an earlier chronological validation window for early stopping and cannot auto-replace the approved classical artifact.</p>
    </article>}
    {!loading && !error && data?.configuration && <div className="experiment-footer">
      <span>{data.configuration.experimentName}</span><span>{data.configuration.backend} tracking store</span><span>Read-only public comparison</span>
    </div>}
  </section>;
}

function DocumentRagPanel({ symbol, documents, documentsLoading, preparation, preparing, prepareError, prepare, question, setQuestion, result, loading, error, ask }) {
  const hasMarketProfile = documents.some((document) => document.documentType.startsWith("market-profile"));
  const hasSec10K = documents.some((document) => document.documentType === "sec-10-k");
  const suggestions = hasMarketProfile ? [
    "Ye company, ETF ya kis type ka market instrument hai?",
    "Is instrument ka exchange, currency aur market profile kya hai?",
    "Available valuation ya fund metrics kya hain?",
    "One-year observed price range aur evidence limitation batao."
  ] : [
    "Revenue aur EBITDA ke main drivers kya the?",
    "Report me debt aur capital expenditure ke baare me kya kaha gaya?",
    "Company ne kaun se major risks disclose kiye?",
    "Management ka future growth strategy kya hai?"
  ];
  const officialReportMode = preparation?.evidenceType === "official-annual-report";
  const officialSecMode = preparation?.evidenceType === "official-sec-10-k";
  const prepareLabel = officialReportMode
    ? "Prepare official annual report"
    : officialSecMode
      ? "Prepare official SEC 10-K"
      : "Prepare verified market evidence";
  return <section className="document-rag" aria-labelledby="document-rag-title">
    <div className="rag-heading">
      <div>
        <p className="eyebrow">DOCUMENT EVIDENCE RAG</p>
        <h3 id="document-rag-title">Ask indexed evidence with source citations</h3>
        <p>{hasMarketProfile
          ? `This exchange has no integrated official-filing provider, so ${symbol} uses a clearly labelled market-profile snapshot.`
          : `Answers retrieve evidence only from indexed documents for ${symbol}. Market prices and ML predictions remain separate.`}</p>
      </div>
      <span className={`rag-count ${documents.length ? "ready" : "empty"}`}>{documentsLoading ? "Loading…" : preparing ? "Indexing…" : `${documents.length} document${documents.length === 1 ? "" : "s"}`}</span>
    </div>

    {documents.length > 0 ? <>
      <div className="rag-documents">{documents.map((document) => <article key={document.id}>
        <div><strong>{document.title}</strong><small>{document.documentType} · {document.reportingPeriod || "Period not supplied"}</small></div>
        <div><span>{document.pageCount} pages</span><span>{document.chunkCount} chunks</span><span>{document.embeddingProvider}</span></div>
        {document.sourceUrl && <a href={document.sourceUrl} target="_blank" rel="noreferrer">Open cited source ↗</a>}
      </article>)}</div>
      {officialSecMode && preparation?.needsPreparation && !hasSec10K && <div className="rag-upgrade">
        <span>An official SEC 10-K is preferred when SEC EDGAR is reachable. The existing market profile remains available as a safe fallback.</span>
        <button className="rag-prepare-button" onClick={prepare} disabled={preparing}>{preparing ? "Checking SEC EDGAR…" : "Upgrade to official SEC 10-K"}</button>
      </div>}
      <div className="rag-suggestions">{suggestions.map((item) => <button key={item} onClick={() => ask(item)} disabled={loading}>{item}</button>)}</div>
      <form className="rag-form" onSubmit={(event) => { event.preventDefault(); ask(); }}>
        <input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question from the company documents…" />
        <button disabled={!question.trim() || loading}>{loading ? "Retrieving…" : "Ask documents"}</button>
      </form>
    </> : !documentsLoading && <div className="rag-empty">
      <strong>{preparing ? `Building the evidence index for ${symbol}…` : `No indexed evidence for ${symbol} yet.`}</strong>
      {preparation?.supported ? <>
        <span>{preparation.message || `FinTrack can build a cited index from ${preparation.provider}.`}</span>
        <button className="rag-prepare-button" onClick={prepare} disabled={preparing}>{preparing ? "Retrieving and indexing…" : prepareLabel}</button>
      </> : <span>{preparation?.message || "The public page will not invent an answer when no trusted document is available."}</span>}
    </div>}

    {prepareError && <div className="rag-error">{prepareError}</div>}
    {error && <div className="rag-error">{error}</div>}
    {result && <div className="rag-answer">
      <div className="rag-answer-meta"><strong>Grounded answer</strong><span>{result.generationMode.replaceAll("_", " ")} · {result.embeddingProvider}</span></div>
      <p>{result.answer}</p>
      <div className="rag-citations">{result.citations.map((citation) => <article key={`${citation.citation}-${citation.page}`}>
        <span>[{citation.citation} p.{citation.page}] · similarity {(Number(citation.score) * 100).toFixed(1)}%</span>
        <strong>{citation.title}</strong>
        <p>{citation.snippet}</p>
        {citation.sourceUrl && <a href={citation.sourceUrl} target="_blank" rel="noreferrer">Open cited source ↗</a>}
      </article>)}</div>
      <small>{result.disclaimer}</small>
    </div>}
  </section>;
}

function ModelEvidence({ model, comparisons, importance, audit }) {
  const maxImportance = Math.max(...importance.map((item) => Number(item.importance) || 0), 1);
  return <section className="model-evidence" aria-labelledby="model-validation-title">
    <div className="panel-title">
      <div><p className="eyebrow">PREDICTIVE ML EVIDENCE</p><h3 id="model-validation-title">Model validation and prediction audit</h3></div>
      <span>Time order preserved · no random shuffle</span>
    </div>
    <div className="validation-summary">
      <ValidationStat label="Selected classifier" value={model.type} />
      <ValidationStat label="Walk-forward folds" value={model.walkForwardFolds} />
      <ValidationStat label="Balanced accuracy" value={formatPercent(model.balancedAccuracy)} />
      <ValidationStat label="ROC AUC" value={formatPercent(model.rocAuc)} />
      <ValidationStat label="Reliability weight" value={model.reliabilityWeight} />
      <ValidationStat label="Training rows" value={model.trainingRows} />
    </div>
    <div className="validation-columns">
      <div className="model-table-wrap">
        <h4>Candidate model comparison</h4>
        <div className="table-scroll"><table className="model-table">
          <thead><tr><th>Model</th><th>Balanced accuracy</th><th>ROC AUC</th><th>F1</th><th>Brier</th></tr></thead>
          <tbody>{comparisons.map((item) => <tr key={item.id} className={item.selected ? "selected-row" : ""}>
            <td>{item.name}{item.selected && <span className="selected-pill">Selected</span>}</td>
            <td>{formatPercent(item.balancedAccuracy)}</td><td>{formatPercent(item.rocAuc)}</td><td>{formatPercent(item.f1)}</td><td>{item.brierScore ?? "—"}</td>
          </tr>)}</tbody>
        </table></div>
      </div>
      <div className="importance-panel">
        <h4>Feature importance</h4>
        {importance.slice(0, 7).map((item) => <div className="importance-row" key={item.feature}>
          <div><span>{item.label}</span><strong>{item.importance}%</strong></div>
          <div className="importance-track"><span style={{ width: `${(Number(item.importance) / maxImportance) * 100}%` }} /></div>
        </div>)}
      </div>
    </div>
    <div className="audit-panel">
      <h4>Prediction audit</h4>
      {audit.length === 0 ? <p>No completed-session audit record yet. The first prediction will be evaluated after a later trading session becomes available.</p> :
        <div className="audit-grid">{audit.slice(0, 4).map((item) => <article className="audit-record" key={item.id}>
          <span>{item.modelDataDate}</span><strong>{item.outlook} · {item.probabilityUp}% up</strong>
          <small>{item.status === "evaluated" ? `Actual: ${item.actualDirection} (${item.actualReturnPercent}%) · ${item.correct ? "correct" : "not correct"}` : "Awaiting next session"}</small>
        </article>)}</div>}
    </div>
    <p className="method-note">Target: next trading session direction. Validation uses expanding historical windows with a one-session gap. Low out-of-sample skill shrinks confidence toward 50%, and only probabilities outside 42%-58% become directional. Feature importance is a diagnostic, not proof of causality.</p>
  </section>;
}

function ValidationStat({ label, value }) { return <article className="validation-card"><small>{label}</small><strong>{value ?? "—"}</strong></article>; }

function Sparkline({ history }) {
  const points = history.map((item) => Number(item.close)).filter(Number.isFinite);
  if (points.length < 2) return <div className="chart-empty">Price history unavailable</div>;
  const min = Math.min(...points); const max = Math.max(...points); const range = max - min || 1;
  const path = points.map((value, index) => `${(index / (points.length - 1)) * 100},${90 - ((value - min) / range) * 75}`).join(" ");
  return <div className="sparkline"><svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Historical price line"><defs><linearGradient id="chartFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#168f9e" stopOpacity=".28"/><stop offset="1" stopColor="#168f9e" stopOpacity="0"/></linearGradient></defs><polygon points={`0,100 ${path} 100,100`} fill="url(#chartFill)"/><polyline points={path} fill="none" stroke="#087d8c" strokeWidth="2" vectorEffect="non-scaling-stroke"/></svg><div><span>{formatNumber(min)}</span><span>{formatNumber(max)}</span></div></div>;
}
