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

const SAVED_RESEARCH_KEY = "fintrack.saved-research.v1";
const MAX_SAVED_RESEARCH = 12;
const MAX_COMPARISON = 4;

const readSavedResearch = () => {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(SAVED_RESEARCH_KEY) || "[]");
    return Array.isArray(parsed) ? parsed.slice(0, MAX_SAVED_RESEARCH) : [];
  } catch {
    return [];
  }
};

const cleanAgentAnswer = (value = "") => String(value)
  .replace(/^\s*#{0,3}\s*Seedha jawab\s*$/gim, "")
  .replace(/^\s*#{1,3}\s*/gm, "")
  .replace(/\*\*/g, "")
  .replace(/\n{3,}/g, "\n\n")
  .trim();

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
  const [agentOpen, setAgentOpen] = useState(false);
  const [activeView, setActiveView] = useState("overview");
  const [savedResearch, setSavedResearch] = useState(readSavedResearch);
  const [comparisonSymbols, setComparisonSymbols] = useState([]);
  const [comparisonRows, setComparisonRows] = useState([]);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonOpen, setComparisonOpen] = useState(false);
  const loadSequenceRef = useRef(0);

  useEffect(() => { setSymbol(initialSymbol); setDraftSymbol(initialSymbol); }, [initialSymbol]);

  useEffect(() => {
    try { window.localStorage.setItem(SAVED_RESEARCH_KEY, JSON.stringify(savedResearch)); }
    catch { /* Private browsing must not break public research. */ }
  }, [savedResearch]);

  useEffect(() => {
    if (!comparisonOpen || comparisonSymbols.length < 2) {
      setComparisonRows([]);
      setComparisonError("");
      return undefined;
    }
    let active = true;
    setComparisonLoading(true);
    setComparisonError("");
    Promise.all(comparisonSymbols.map(async (item) => {
      const response = await marketApi.analysis(item.symbol, false);
      return response?.data || response;
    }))
      .then((rows) => { if (active) setComparisonRows(rows.filter(Boolean)); })
      .catch(() => { if (active) setComparisonError("Comparison data is temporarily unavailable. Please retry."); })
      .finally(() => { if (active) setComparisonLoading(false); });
    return () => { active = false; };
  }, [comparisonOpen, comparisonSymbols]);

  useEffect(() => {
    if (symbol.startsWith("^") && ["company", "documents"].includes(activeView)) setActiveView("overview");
  }, [symbol, activeView]);

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
  const send = async (value = question, viewOverride = activeView, recentOverride = messages.slice(-6)) => {
    const clean = value.trim();
    if (!clean || asking) return;
    const userMessage = { role: "user", content: clean };
    setMessages((current) => [...current, userMessage]); setQuestion(""); setAsking(true);
    try {
      const sectionInstruction = {
        overview: "Section: overview. Explain only the dashboard data the user asks about, what it measures, how to read the displayed value, and its main limitation.",
        company: "Section: company evidence. Explain only the company data the user asks about, what it measures, and its main limitation.",
        documents: "Section: reports and RAG. Answer only from indexed company reports; do not invent missing document facts.",
        mlops: "Section: model and MLOps. Explain only the model or monitoring data the user asks about, what it measures, and its main limitation."
      }[viewOverride];
      const response = await marketApi.agent({ message: `${sectionInstruction} User question: ${clean}`, symbol, recentMessages: recentOverride });
      setMessages((current) => [...current, { role: "assistant", content: response.answer, meta: response }]);
    } catch {
      setMessages((current) => [...current, { role: "assistant", content: "The research agent is temporarily unavailable. Price analytics above remain independent of the AI response.", meta: { llmStatus: "offline" } }]);
    } finally { setAsking(false); }
  };

  const suggestedQuestions = {
    overview: [`${symbol} outlook ka simple meaning kya hai?`, "Probability, RSI aur expected range ko aasaan language me samjhao"],
    company: [`${symbol} ke fundamentals me sabse important baat kya hai?`, "Performance, catalysts aur analyst estimates ko simple language me samjhao"],
    documents: [`${symbol} ke available reports ka short summary do`, "Document evidence me risk ya debt ke baare me kya likha hai?"],
    mlops: ["Model score reliable hai ya nahi, simple language me batao", "Experiment, drift aur serving model ka difference samjhao"]
  }[activeView];

  const openContextAgent = () => {
    setMessages([]);
    setQuestion("");
    setAgentOpen(true);
  };

  const explainMetric = (label, value, hint = "", view = "overview") => {
    const displayedValue = value === null || value === undefined || value === "" ? "unavailable" : value;
    const prompt = `${label} ki displayed value ${displayedValue} hai${hint ? ` (${hint})` : ""}. Ye metric kya measure karta hai, is exact value ka simple meaning kya hai, aur iski ek important limitation Hinglish me 100 words ke andar samjhao.`;
    setActiveView(view);
    setMessages([]);
    setQuestion("");
    setAgentOpen(true);
    void send(prompt, view, []);
  };

  const saveCurrentResearch = () => {
    if (!analysis) return;
    const entry = {
      symbol: analysis.symbol,
      name: resolvedCompany?.symbol === analysis.symbol ? resolvedCompany.name : analysis.name,
      savedAt: new Date().toISOString()
    };
    setSavedResearch((current) => [entry, ...current.filter((item) => item.symbol !== entry.symbol)].slice(0, MAX_SAVED_RESEARCH));
  };

  const removeSavedResearch = (savedSymbol) => {
    setSavedResearch((current) => current.filter((item) => item.symbol !== savedSymbol));
    setComparisonSymbols((current) => current.filter((item) => item.symbol !== savedSymbol));
  };

  const toggleComparison = (item) => {
    setComparisonSymbols((current) => {
      if (current.some((selected) => selected.symbol === item.symbol)) return current.filter((selected) => selected.symbol !== item.symbol);
      if (current.length >= MAX_COMPARISON) return current;
      return [...current, item];
    });
  };

  const printResearchReport = () => {
    if (!analysis) return;
    const previousTitle = document.title;
    document.title = `FinTrack ${analysis.symbol} research report`;
    window.print();
    window.setTimeout(() => { document.title = previousTitle; }, 500);
  };

  return (
    <section className="page-section intelligence-page" aria-labelledby="research-title">
      <div className="intelligence-main">
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
        <div className="research-actions" aria-label="Research actions">
          <button type="button" onClick={saveCurrentResearch} disabled={savedResearch.some((item) => item.symbol === analysis.symbol)}>
            {savedResearch.some((item) => item.symbol === analysis.symbol) ? "✓ Saved for comparison" : "+ Save company"}
          </button>
          <button type="button" onClick={() => setComparisonOpen((current) => !current)}>
            Compare saved ({savedResearch.length}) {comparisonOpen ? "↑" : "↓"}
          </button>
          <button type="button" onClick={printResearchReport}>Print / Save PDF</button>
        </div>
        {comparisonOpen && <SavedResearchPanel
          items={savedResearch}
          selected={comparisonSymbols}
          rows={comparisonRows}
          loading={comparisonLoading}
          error={comparisonError}
          toggle={toggleComparison}
          remove={removeSavedResearch}
          openResearch={(item) => { setResolvedCompany(item); load(item.symbol); }}
        />}
        <div className="metric-grid">
          <Metric label="Probability up" value={`${analysis.probabilityUp}%`} hint={`${analysis.probabilityDown}% probability down`} onExplain={explainMetric} />
          <Metric label="Expected range" value={`${formatNumber(analysis.expectedRange?.low)} – ${formatNumber(analysis.expectedRange?.high)}`} hint={analysis.expectedRange?.currency} onExplain={explainMetric} />
          <Metric label="RSI (14)" value={formatNumber(analysis.technicalIndicators?.rsi14)} hint="Below 30 oversold · above 70 overbought" onExplain={explainMetric} />
          <Metric label="Walk-forward score" value={`${analysis.model?.balancedAccuracy ?? analysis.model?.backtestAccuracy}%`} hint={`${analysis.model?.walkForwardFolds || 1} time-ordered folds · ${analysis.model?.quality} quality`} onExplain={explainMetric} />
        </div>
        <PredictionOutcomeSummary status={modelStatus} loading={modelStatusLoading} onOpen={() => setActiveView("mlops")} />
        <nav className="intelligence-view-tabs" aria-label="Intelligence detail views">
          {[
            ["overview", "Overview"],
            ...(!analysis.symbol.startsWith("^") ? [["company", "Company evidence"], ["documents", "Reports & RAG"]] : []),
            ["mlops", "Model & MLOps"]
          ].map(([value, label]) => <button type="button" key={value} className={activeView === value ? "active" : ""} onClick={() => setActiveView(value)}>{label}</button>)}
        </nav>
        <div className="context-agent-bar">
          <div><strong>Need help with this section?</strong><span>Grounded Gemini will answer only from the visible {activeView} evidence.</span></div>
          <button type="button" onClick={openContextAgent}>✦ Ask Grounded Gemini</button>
        </div>
        {activeView === "company" && !analysis.symbol.startsWith("^") && <CompanyFundamentalsPanel data={companyResearch} loading={companyResearchLoading} error={companyResearchError} />}
        {activeView === "company" && !analysis.symbol.startsWith("^") && <SectorPeerPanel data={peerComparison} loading={peerComparisonLoading} error={peerComparisonError} />}
        {activeView === "overview" && analysis.riskBenchmark && <RiskBenchmarkPanel data={analysis.riskBenchmark} symbol={analysis.symbol} onExplain={explainMetric} />}
        {activeView === "overview" && localExplanation && <PredictionExplanation explanation={localExplanation} outlook={analysis.outlook} />}
        {activeView === "mlops" && <ModelRegistryPanel status={modelStatus} loading={modelStatusLoading} error={modelStatusError} activeModel={analysis.model} />}
        {activeView === "mlops" && <ExperimentTrackingPanel data={experiments} loading={experimentsLoading} error={experimentsError} />}
        {activeView === "documents" && !symbol.startsWith("^") && <DocumentRagPanel
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
        {activeView === "overview" && <div className="research-grid">
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
        </div>}
        {activeView === "mlops" && modelComparisons.length > 0 && <ModelEvidence
          model={analysis.model}
          comparisons={modelComparisons}
          importance={featureImportance}
          audit={predictionAudit}
        />}
        <div className="notice warning"><strong>Research limitation:</strong> {analysis.disclaimer}</div>
      </>}

      </div>
      <button type="button" className="agent-launcher" onClick={openContextAgent}>✦ Ask Grounded Gemini</button>
      <article className={`agent-panel agent-drawer${agentOpen ? " open" : ""}`}>
        <div className="panel-title"><div><p className="eyebrow">GROUNDED GEMINI · {activeView.toUpperCase()}</p><h3>Ask about this section</h3></div><button type="button" className="agent-close" onClick={() => setAgentOpen(false)} aria-label="Close research agent">×</button></div>
        <div className="suggested-row">
          {suggestedQuestions.map((item) => <button key={item} onClick={() => send(item)}>{item}</button>)}
        </div>
        <div className="chat-log">
          {messages.length === 0 && <div className="agent-empty">Ask about prices, factors, market breadth, model weakness or current headlines.</div>}
          {messages.map((message, index) => <div key={index} className={`chat-message ${message.role}`}><p>{message.role === "assistant" ? cleanAgentAnswer(message.content) : message.content}</p>{message.meta && <>
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

function SavedResearchPanel({ items, selected, rows, loading, error, toggle, remove, openResearch }) {
  const selectedSymbols = new Set(selected.map((item) => item.symbol));
  return <section className="saved-research-panel" aria-labelledby="saved-research-title">
    <div className="saved-research-heading">
      <div><p className="eyebrow">PERSONAL BROWSER WATCHLIST</p><h3 id="saved-research-title">Compare any saved companies</h3><p>Saved only in this browser. Select 2–4 symbols; no login or personal finance data is required.</p></div>
      <span>{selected.length}/{MAX_COMPARISON} selected</span>
    </div>
    {items.length === 0 && <div className="saved-research-empty">Open any company or index and choose “Save company”. Your list will stay dynamic—not limited to fixed presets.</div>}
    {items.length > 0 && <div className="saved-symbol-list">
      {items.map((item) => <article key={item.symbol} className={selectedSymbols.has(item.symbol) ? "selected" : ""}>
        <button type="button" className="saved-symbol-main" onClick={() => openResearch(item)}><strong>{item.name || item.symbol}</strong><span>{item.symbol}</span></button>
        <button type="button" className="saved-compare-toggle" disabled={!selectedSymbols.has(item.symbol) && selected.length >= MAX_COMPARISON} onClick={() => toggle(item)}>
          {selectedSymbols.has(item.symbol) ? "✓ Comparing" : "Compare"}
        </button>
        <button type="button" className="saved-remove" onClick={() => remove(item.symbol)} aria-label={`Remove ${item.symbol}`}>×</button>
      </article>)}
    </div>}
    {selected.length === 1 && <p className="comparison-guidance">Select one more saved symbol to start the side-by-side comparison.</p>}
    {loading && <p className="comparison-guidance">Loading verified comparison evidence…</p>}
    {error && <div className="notice error">{error}</div>}
    {!loading && rows.length >= 2 && <div className="comparison-table-wrap">
      <table className="comparison-table">
        <thead><tr><th>Company</th><th>Outlook</th><th>Probability up</th><th>Expected range</th><th>RSI (14)</th><th>Walk-forward</th><th>1-year return</th><th>Volatility</th></tr></thead>
        <tbody>{rows.map((row) => <tr key={row.symbol}>
          <th><strong>{row.name || row.symbol}</strong><span>{row.symbol}</span></th>
          <td><b className={`comparison-outlook outlook-${String(row.outlook).toLowerCase()}`}>{row.outlook}</b></td>
          <td>{formatPercent(row.probabilityUp)}</td>
          <td>{formatNumber(row.expectedRange?.low)} – {formatNumber(row.expectedRange?.high)} <small>{row.expectedRange?.currency}</small></td>
          <td>{formatNumber(row.technicalIndicators?.rsi14)}</td>
          <td>{formatPercent(row.model?.balancedAccuracy ?? row.model?.backtestAccuracy)}</td>
          <td>{formatPercent(row.riskBenchmark?.asset?.periodReturnPercent)}</td>
          <td>{formatPercent(row.riskBenchmark?.asset?.annualizedVolatilityPercent)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    <p className="comparison-footnote">Comparison is descriptive evidence, not a ranking or buy/sell recommendation. Different currencies and exchanges are shown as reported.</p>
  </section>;
}

function PredictionOutcomeSummary({ status, loading, onOpen }) {
  const monitoring = status?.predictionMonitoring;
  const evaluated = monitoring?.evaluated ?? monitoring?.rollingQuality?.evaluatedTotal ?? 0;
  const pending = Math.max(0, (monitoring?.totalStored ?? 0) - evaluated);
  return <aside className="prediction-outcome-summary" aria-label="Prediction outcome tracking">
    <div><span>PREDICTION OUTCOME TRACKING</span><strong>{loading ? "Checking stored predictions…" : `${monitoring?.totalStored ?? 0} predictions stored`}</strong></div>
    <dl>
      <div><dt>Evaluated</dt><dd>{loading ? "—" : evaluated}</dd></div>
      <div><dt>Awaiting session</dt><dd>{loading ? "—" : pending}</dd></div>
      <div><dt>Observed accuracy</dt><dd>{loading || monitoring?.observedAccuracy === null || monitoring?.observedAccuracy === undefined ? "Awaiting outcomes" : `${monitoring.observedAccuracy}%`}</dd></div>
    </dl>
    <button type="button" onClick={onOpen}>Open audit & MLOps →</button>
  </aside>;
}

function Metric({ label, value, hint, onExplain }) { return <article className="metric-card"><div className="explainable-metric-heading"><small>{label}</small>{onExplain && <button type="button" className="metric-explain-button" onClick={() => onExplain(label, value, hint)} aria-label={`Explain ${label}`}>? Explain</button>}</div><strong>{value}</strong><span>{hint}</span></article>; }

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
    <CompanyAnalystEstimatePanel data={data.analystEstimateIntelligence} currency={currency} />
    <CompanyCorporateActionPanel data={data.corporateActionIntelligence} currency={currency} />
    <div className="fundamental-groups">{groups.map(([title, entries]) => <FundamentalGroup key={title} title={title} entries={entries} />)}</div>
    <CompanyFinancialTrendPanel data={data.financialTrends} currency={currency} />
    <CompanyProfitabilityReturnsPanel data={data.profitabilityReturnsIntelligence} currency={currency} />
    <CompanyEarningsQualityPanel data={data.earningsQualityIntelligence} currency={currency} />
    <CompanyLiquidityDebtPanel data={data.liquidityDebtIntelligence} currency={currency} />
    <CompanyOwnershipPanel data={data.ownershipIntelligence} currency={currency} />
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

function CompanyCorporateActionPanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="corporate-action-panel corporate-action-unavailable">
    <div className="corporate-action-heading"><div><p className="eyebrow">DIVIDENDS & CORPORATE ACTIONS</p><h4>No distribution or split evidence available</h4></div><span>Missing is not zero</span></div>
    <p>The provider returned no dividend, capital-gain distribution or split history for this listing. FinTrack does not infer a zero payout.</p>
  </section>;

  const summary = data.summary || {};
  const snapshot = data.snapshot || {};
  const annual = data.annualDividends || [];
  const dividends = data.recentDividends || [];
  const splits = data.recentSplits || [];
  const capitalGains = data.recentCapitalGains || [];
  const upcoming = data.upcomingEvents || [];
  const localCurrency = data.currency || currency;
  const value = (raw, digits = 2) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric)) return "—";
    return numeric.toLocaleString("en-IN", { maximumFractionDigits: digits });
  };

  const perShare = (raw) => raw === null || raw === undefined ? "—" : `${value(raw, 6)} ${localCurrency || "local currency"}`;
  const percent = (raw, signed = false) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric)) return "—";
    return `${signed && numeric > 0 ? "+" : ""}${numeric.toFixed(2)}%`;
  };
  const formatDate = (raw) => {
    if (!raw) return "Date unavailable";
    const parsed = new Date(`${raw}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  const maxAnnual = Math.max(...annual.map((item) => Number(item.totalPerShare) || 0), 1);
  const hasDividendEvidence = dividends.length > 0 || annual.length > 0;
  const cagrYears = summary.completedYearCagrStart && summary.completedYearCagrEnd
    ? `${summary.completedYearCagrStart}–${summary.completedYearCagrEnd} completed years`
    : "Needs two completed years";

  return <section className="corporate-action-panel" aria-labelledby="corporate-action-title">
    <div className="corporate-action-heading">
      <div><p className="eyebrow">DIVIDENDS & CORPORATE ACTIONS</p><h4 id="corporate-action-title">Per-share distributions, growth evidence and stock splits</h4></div>
      <span>{data.coverageLevel || "partial"} provider coverage</span>
    </div>
    <div className="corporate-action-summary">
      <article><small>Trailing 12 months</small><strong>{perShare(summary.trailing12MonthTotalPerShare)}</strong><span>{summary.paymentsLast12Months || 0} recorded payment(s)</span></article>
      <article><small>Current dividend yield</small><strong>{percent(snapshot.currentYieldPercent)}</strong><span>{snapshot.fiveYearAverageYieldPercent == null ? "5-year average unavailable" : `${percent(snapshot.fiveYearAverageYieldPercent)} five-year average`}</span></article>
      <article className={Number(summary.completedYearDividendCagrPercent) >= 0 ? "positive" : "negative"}><small>Completed-year CAGR</small><strong>{percent(summary.completedYearDividendCagrPercent, true)}</strong><span>{cagrYears}</span></article>
      <article><small>Latest split</small><strong>{summary.latestSplitRatio || "No split returned"}</strong><span>{summary.latestSplitDate ? formatDate(summary.latestSplitDate) : "Provider history unavailable"}</span></article>
    </div>
    <div className="corporate-action-layout">
      <article className="annual-dividend-card">
        <div className="corporate-action-card-heading"><strong>Annual dividend record</strong><span>Current calendar year is partial</span></div>
        {annual.length ? <div className="annual-dividend-bars">{[...annual].reverse().map((item) => <div key={item.year}>
          <span>{item.year}{item.isPartialYear ? "*" : ""}</span>
          <i><b style={{ width: `${Math.max(4, (Number(item.totalPerShare || 0) / maxAnnual) * 100)}%` }} /></i>
          <strong>{perShare(item.totalPerShare)}</strong>
          <small className={Number(item.changePercent) >= 0 ? "positive" : "negative"}>{item.isPartialYear ? "partial" : `${percent(item.changePercent, true)} YoY`}</small>
        </div>)}</div> : <p className="corporate-action-empty">No cash-distribution history was returned. Split evidence below remains independent.</p>}
      </article>
      <article className="corporate-action-history-card">
        <div className="corporate-action-card-heading"><strong>Recent provider events</strong><span>Newest first</span></div>
        {dividends.slice(0, 5).map((item, index) => <div className="corporate-action-event" key={`dividend-${item.date}-${index}`}><span>Dividend</span><p><strong>{perShare(item.amountPerShare)} per share</strong><small>{formatDate(item.date)}</small></p></div>)}
        {splits.slice(0, 4).map((item, index) => <div className="corporate-action-event split" key={`split-${item.date}-${index}`}><span>Split</span><p><strong>{item.displayRatio}</strong><small>{formatDate(item.date)}</small></p></div>)}
        {capitalGains.slice(0, 3).map((item, index) => <div className="corporate-action-event gain" key={`gain-${item.date}-${index}`}><span>Capital gain</span><p><strong>{perShare(item.amountPerShare)} per share</strong><small>{formatDate(item.date)}</small></p></div>)}
        {!dividends.length && !splits.length && !capitalGains.length && <p className="corporate-action-empty">No dated event rows were returned by the provider.</p>}
      </article>
    </div>
    <div className="corporate-action-footnotes">
      <span>Payout ratio: <strong>{percent(snapshot.payoutRatioPercent)}</strong></span>
      <span>Prior trailing window: <strong>{perShare(summary.previous12MonthTotalPerShare)}</strong></span>
      <span>TTM change: <strong>{percent(summary.trailingChangePercent, true)}</strong></span>
      {!hasDividendEvidence && <span className="evidence-warning">No cash history returned; this is not shown as zero.</span>}
    </div>
    {upcoming.length > 0 && <div className="corporate-action-upcoming"><strong>Upcoming provider dates</strong>{upcoming.map((item) => <span key={`${item.type}-${item.date}`}>{item.label}: {formatDate(item.date)}</span>)}</div>}
    <p className="corporate-action-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function CompanyFinancialTrendPanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="financial-trend-panel financial-trend-unavailable">
    <div className="financial-trend-heading"><div><p className="eyebrow">FINANCIAL STATEMENT TRENDS</p><h4>No comparable statement periods available</h4></div><span>Not estimated</span></div>
    <p>The provider returned no comparable annual or quarterly statement rows, so FinTrack does not create synthetic trends.</p>
  </section>;

  const summary = data.summary || {};
  const annual = data.annual || [];
  const quarterly = data.quarterly || [];
  const latestAnnual = annual[annual.length - 1] || {};
  const formatDate = (value, short = false) => {
    if (!value) return "Period unavailable";
    const parsed = new Date(`${value}T00:00:00`);
    if (Number.isNaN(parsed.getTime())) return value;
    return parsed.toLocaleDateString("en-IN", short ? { month: "short", year: "2-digit" } : { day: "numeric", month: "short", year: "numeric" });
  };
  const percent = (value, signed = false) => {
    const numeric = Number(value);
    if (value === null || value === undefined || !Number.isFinite(numeric)) return "—";
    return `${signed && numeric > 0 ? "+" : ""}${numeric.toFixed(1)}%`;
  };
  const directionClass = (value) => value === null || value === undefined ? "" : Number(value) >= 0 ? "positive" : "negative";
  const points = (value) => {
    const numeric = Number(value);
    if (value === null || value === undefined || !Number.isFinite(numeric)) return "Change unavailable";
    return `${numeric > 0 ? "+" : ""}${numeric.toFixed(1)} pts vs prior year`;
  };
  const trendLabel = (value) => String(value || "unavailable").replace(/^./, (character) => character.toUpperCase());
  const trendClass = (value) => ["growing", "declining", "stable", "mixed"].includes(value) ? value : "unavailable";
  const maxQuarterRevenue = Math.max(...quarterly.map((item) => Math.abs(Number(item.revenue) || 0)), 1);

  return <section className="financial-trend-panel" aria-labelledby="financial-trend-title">
    <div className="financial-trend-heading">
      <div><p className="eyebrow">FINANCIAL STATEMENT TRENDS</p><h4 id="financial-trend-title">Annual growth, profitability, cash flow and leverage</h4></div>
      <span>{summary.annualPeriodCount || annual.length} reported years</span>
    </div>
    <div className="financial-trend-summary">
      <article><small>Revenue CAGR</small><strong>{percent(summary.revenueCagrPercent, true)}</strong><span className={`trend-${trendClass(summary.revenueTrend)}`}>{trendLabel(summary.revenueTrend)} revenue trend</span></article>
      <article><small>Latest operating margin</small><strong>{percent(summary.latestOperatingMarginPercent)}</strong><span>{points(summary.operatingMarginChangePoints)}</span></article>
      <article><small>Latest free cash flow</small><strong>{formatCompactMoney(summary.latestFreeCashFlow, currency)}</strong><span className={`trend-${trendClass(summary.freeCashFlowTrend)}`}>{trendLabel(summary.freeCashFlowTrend)} FCF trend</span></article>
      <article><small>Debt / equity</small><strong>{summary.latestDebtToEquityRatio === null || summary.latestDebtToEquityRatio === undefined ? "—" : `${Number(summary.latestDebtToEquityRatio).toFixed(2)}x`}</strong><span>{percent(summary.latestDebtYoYPercent, true)} debt YoY</span></article>
    </div>
    <div className="financial-annual-table-wrap">
      <div className="financial-card-heading"><strong>Annual reported evidence</strong><span>Latest fiscal period: {formatDate(summary.latestAnnualPeriod)}</span></div>
      <table className="financial-annual-table">
        <thead><tr><th>Fiscal period</th><th>Revenue</th><th>YoY</th><th>Net income</th><th>YoY</th><th>Op. margin</th><th>Free cash flow</th><th>Debt / equity</th></tr></thead>
        <tbody>{[...annual].reverse().map((item) => <tr key={item.period} className={item.period === latestAnnual.period ? "latest" : ""}>
          <td><strong>{formatDate(item.period)}</strong>{item.period === latestAnnual.period && <small>Latest annual</small>}</td>
          <td>{formatCompactMoney(item.revenue, currency)}</td><td className={directionClass(item.revenueYoYPercent)}>{percent(item.revenueYoYPercent, true)}</td>
          <td>{formatCompactMoney(item.netIncome, currency)}</td><td className={directionClass(item.netIncomeYoYPercent)}>{percent(item.netIncomeYoYPercent, true)}</td>
          <td>{percent(item.operatingMarginPercent)}</td><td>{formatCompactMoney(item.freeCashFlow, currency)}</td><td>{item.debtToEquityRatio === null || item.debtToEquityRatio === undefined ? "—" : `${Number(item.debtToEquityRatio).toFixed(2)}x`}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className="quarterly-financial-card">
      <div className="financial-card-heading"><strong>Recent quarterly revenue evidence</strong><span>Quarter-over-quarter changes are not seasonally adjusted</span></div>
      {quarterly.length ? <div className="quarterly-revenue-bars">{quarterly.map((item, index) => {
        const revenue = Math.abs(Number(item.revenue) || 0);
        const comparison = index === 0 ? "First returned period" : item.previousQuarterComparable ? `${percent(item.revenueQoQPercent, true)} QoQ` : "Period gap · not QoQ";
        return <article key={item.period}><div><b style={{ height: `${Math.max(5, (revenue / maxQuarterRevenue) * 100)}%` }} /></div><strong>{formatCompactMoney(item.revenue, currency)}</strong><span>{formatDate(item.period, true)}</span><small>{comparison} · {percent(item.operatingMarginPercent)} margin</small></article>;
      })}</div> : <p>No comparable quarterly revenue periods were returned.</p>}
    </div>
    <p className="financial-trend-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function CompanyEarningsQualityPanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="earnings-quality-panel earnings-quality-unavailable">
    <div className="earnings-quality-heading"><div><p className="eyebrow">EARNINGS QUALITY & CAPITAL ALLOCATION</p><h4>No comparable cash-flow periods available</h4></div><span>Not estimated</span></div>
    <p>The provider returned no aligned annual income and cash-flow rows, so FinTrack does not invent conversion or capital-allocation evidence.</p>
  </section>;

  const summary = data.summary || {};
  const annual = data.annual || [];
  const latest = annual[annual.length - 1] || {};
  const localCurrency = data.currency || currency;
  const percent = (raw, signed = false) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric)) return "—";
    return `${signed && numeric > 0 ? "+" : ""}${numeric.toFixed(1)}%`;
  };
  const formatDate = (raw) => {
    if (!raw) return "Period unavailable";
    const parsed = new Date(`${raw}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  const money = (raw) => formatCompactMoney(raw, localCurrency);
  const direction = (raw) => raw === null || raw === undefined ? "" : Number(raw) >= 0 ? "positive" : "negative";
  const conversionDirection = (raw) => raw === null || raw === undefined ? "" : direction(Number(raw) - 100);
  const maxCashMagnitude = Math.max(...annual.flatMap((item) => [item.netIncome, item.operatingCashFlow, item.freeCashFlow]).map((item) => Math.abs(Number(item) || 0)), 1);
  const barWidth = (raw) => `${Math.max(2, (Math.abs(Number(raw) || 0) / maxCashMagnitude) * 100)}%`;
  const allocationItems = [
    ["Capital expenditure", latest.capitalExpenditure, `${percent(latest.capitalExpenditureToOperatingCashFlowPercent)} of operating cash`],
    ["Cash dividends", latest.dividendsPaid, "Reported cash outflow"],
    ["Share repurchases", latest.shareRepurchases, "Reported cash outflow"],
    ["Share issuance", latest.shareIssuance, "Reported cash inflow"],
    ["Debt repayment", latest.debtRepayment, "Reported cash outflow"],
    ["Debt issuance", latest.debtIssuance, "Reported cash inflow"],
  ];

  return <section className="earnings-quality-panel" aria-labelledby="earnings-quality-title">
    <div className="earnings-quality-heading">
      <div><p className="eyebrow">EARNINGS QUALITY & CAPITAL ALLOCATION</p><h4 id="earnings-quality-title">Cash conversion and reported deployment of capital</h4></div>
      <span>{data.coverageLevel || "partial"} statement coverage</span>
    </div>
    {data.financialSectorCaution && <div className="earnings-quality-caution"><strong>Financial-sector context:</strong> Debt and operating cash-flow classifications reflect this business model and are not directly comparable with industrial companies.</div>}
    <div className="earnings-quality-summary">
      <article className={conversionDirection(summary.latestOperatingCashConversionPercent)}><small>Operating-cash conversion</small><strong>{percent(summary.latestOperatingCashConversionPercent)}</strong><span>OCF / positive net income</span></article>
      <article className={conversionDirection(summary.latestFreeCashFlowConversionPercent)}><small>Free-cash-flow conversion</small><strong>{percent(summary.latestFreeCashFlowConversionPercent)}</strong><span>FCF / positive net income</span></article>
      <article><small>Positive FCF periods</small><strong>{summary.positiveFreeCashFlowPeriods || 0} / {summary.freeCashFlowPeriodCount || 0}</strong><span>Returned annual periods only</span></article>
      <article className={direction(summary.latestFreeCashFlowAfterShareholderReturns)}><small>FCF after cash returns</small><strong>{money(summary.latestFreeCashFlowAfterShareholderReturns)}</strong><span>{percent(summary.latestShareholderReturnsToFreeCashFlowPercent)} of positive FCF returned</span></article>
    </div>
    <div className="earnings-quality-layout">
      <article className="cash-conversion-card">
        <div className="earnings-quality-card-heading"><strong>Profit-to-cash evidence</strong><span>Aligned annual fiscal periods</span></div>
        <div className="cash-conversion-legend"><span className="income">Net income</span><span className="operating">Operating cash</span><span className="free">Free cash flow</span></div>
        <div className="cash-conversion-bars">{annual.map((item) => <div key={item.period}>
          <span>{new Date(`${item.period}T00:00:00`).getFullYear()}</span>
          <section>
            <i className="income"><b style={{ width: barWidth(item.netIncome) }} /></i>
            <i className="operating"><b style={{ width: barWidth(item.operatingCashFlow) }} /></i>
            <i className="free"><b style={{ width: barWidth(item.freeCashFlow) }} /></i>
          </section>
          <p><strong>{percent(item.operatingCashConversionPercent)}</strong><small>OCF conversion</small></p>
        </div>)}</div>
      </article>
      <article className="capital-allocation-card">
        <div className="earnings-quality-card-heading"><strong>Latest capital allocation</strong><span>{formatDate(summary.latestPeriod)}</span></div>
        <div className="capital-allocation-grid">{allocationItems.map(([label, amount, hint]) => <div key={label}>
          <small>{label}</small><strong>{money(amount)}</strong><span>{amount === null || amount === undefined ? "Provider row unavailable" : hint}</span>
        </div>)}</div>
      </article>
    </div>
    <div className="earnings-quality-table-wrap">
      <div className="earnings-quality-card-heading"><strong>Reported conversion history</strong><span>Ratios require positive reported net income</span></div>
      <table className="earnings-quality-table">
        <thead><tr><th>Fiscal period</th><th>Net income</th><th>Operating cash</th><th>OCF conversion</th><th>Free cash flow</th><th>FCF conversion</th><th>Shareholder cash returns</th></tr></thead>
        <tbody>{[...annual].reverse().map((item) => <tr key={item.period}>
          <td><strong>{formatDate(item.period)}</strong><small>{item.conversionBasis}</small></td>
          <td>{money(item.netIncome)}</td><td>{money(item.operatingCashFlow)}</td><td>{percent(item.operatingCashConversionPercent)}</td>
          <td className={direction(item.freeCashFlow)}>{money(item.freeCashFlow)}</td><td>{percent(item.freeCashFlowConversionPercent)}</td><td>{money(item.shareholderCashReturns)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="earnings-quality-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function CompanyLiquidityDebtPanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="liquidity-debt-panel liquidity-debt-unavailable">
    <div className="liquidity-debt-heading"><div><p className="eyebrow">BALANCE SHEET, LIQUIDITY & DEBT CAPACITY</p><h4>No comparable balance-sheet periods available</h4></div><span>Not estimated</span></div>
    <p>The provider returned no usable annual liquidity or leverage rows, so FinTrack does not invent a balance-sheet assessment.</p>
  </section>;

  const summary = data.summary || {};
  const annual = data.annual || [];
  const latest = annual[annual.length - 1] || {};
  const localCurrency = data.currency || currency;
  const money = (raw) => formatCompactMoney(raw, localCurrency);
  const ratio = (raw) => {
    const numeric = Number(raw);
    return raw === null || raw === undefined || !Number.isFinite(numeric) ? "—" : `${numeric.toFixed(2)}x`;
  };
  const percent = (raw, signed = false) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric)) return "—";
    return `${signed && numeric > 0 ? "+" : ""}${numeric.toFixed(1)}%`;
  };
  const formatDate = (raw) => {
    if (!raw) return "Period unavailable";
    const parsed = new Date(`${raw}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  const direction = (raw, inverse = false) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric) || numeric === 0) return "neutral";
    const positive = inverse ? numeric < 0 : numeric > 0;
    return positive ? "positive" : "negative";
  };
  const maxBalance = Math.max(...annual.flatMap((item) => [item.liquidFunds, item.totalDebt]).map((value) => Math.abs(Number(value) || 0)), 1);
  const width = (raw) => `${Math.max(2, (Math.abs(Number(raw) || 0) / maxBalance) * 100)}%`;
  const mismatchPeriods = summary.providerNetDebtBasisMismatchPeriods || [];
  const structureItems = [
    ["Debt / equity", ratio(summary.latestTotalDebtToEquityRatio), "Reported debt and equity"],
    ["Debt / assets", percent(summary.latestTotalDebtToAssetsPercent), "Capital structure"],
    ["Liquid funds / debt", percent(summary.latestLiquidFundsToDebtPercent), summary.latestLiquidityBasis || "Liquidity basis unavailable"],
    ["Interest coverage", ratio(summary.latestInterestCoverageRatio), data.financialSectorCaution ? "Withheld for financial-sector comparability" : "EBIT / interest expense"],
    ["Debt / EBITDA", ratio(summary.latestDebtToEbitdaRatio), data.financialSectorCaution ? "Withheld for financial-sector comparability" : "Reported annual EBITDA"],
    ["Working capital", money(summary.latestWorkingCapital), "Current assets minus liabilities"],
  ];

  return <section className="liquidity-debt-panel" aria-labelledby="liquidity-debt-title">
    <div className="liquidity-debt-heading">
      <div><p className="eyebrow">BALANCE SHEET, LIQUIDITY & DEBT CAPACITY</p><h4 id="liquidity-debt-title">Reported liquidity, leverage and coverage evidence</h4></div>
      <span>{data.coverageLevel || "partial"} statement coverage</span>
    </div>
    {data.financialSectorCaution && <div className="liquidity-debt-caution"><strong>Financial-sector context:</strong> Debt, liquidity and interest classifications reflect this business model. Industrial interest-coverage and debt/EBITDA ratios are intentionally withheld.</div>}
    {mismatchPeriods.length > 0 && <div className="liquidity-basis-warning"><strong>Net-debt basis warning:</strong> Provider net debt differs from total debt minus disclosed liquid funds in {mismatchPeriods.length} returned period(s). FinTrack keeps both bases separate.</div>}
    <div className="liquidity-debt-summary">
      <article><small>Liquid funds</small><strong>{money(summary.latestLiquidFunds)}</strong><span>{summary.latestLiquidityBasis || "Basis unavailable"}</span></article>
      <article className={direction(summary.latestDebtAfterLiquidFunds, true)}><small>Debt after liquid funds</small><strong>{money(summary.latestDebtAfterLiquidFunds)}</strong><span>{summary.latestBalancePosition || "Position unavailable"}</span></article>
      <article><small>Current ratio</small><strong>{ratio(summary.latestCurrentRatio)}</strong><span>{money(summary.latestWorkingCapital)} working capital</span></article>
      <article><small>Interest coverage</small><strong>{ratio(summary.latestInterestCoverageRatio)}</strong><span>{ratio(summary.latestDebtToEbitdaRatio)} debt / EBITDA</span></article>
    </div>
    <div className="liquidity-debt-layout">
      <article className="liquidity-debt-trend-card">
        <div className="liquidity-debt-card-heading"><strong>Liquid funds versus total debt</strong><span>Aligned annual fiscal periods</span></div>
        <div className="liquidity-debt-legend"><span className="liquid">Liquid funds</span><span className="debt">Total debt</span></div>
        <div className="liquidity-debt-bars">{annual.map((item) => <div key={item.period}>
          <span>{new Date(`${item.period}T00:00:00`).getFullYear()}</span>
          <section><i className="liquid"><b style={{ width: width(item.liquidFunds) }} /></i><i className="debt"><b style={{ width: width(item.totalDebt) }} /></i></section>
          <p><strong>{money(item.debtAfterLiquidFunds)}</strong><small>{item.balancePosition}</small></p>
        </div>)}</div>
        <div className="liquidity-trend-chips"><span>Liquid funds: <strong>{summary.liquidFundsTrend || "unavailable"}</strong></span><span>Total debt: <strong>{summary.totalDebtTrend || "unavailable"}</strong></span></div>
      </article>
      <article className="debt-structure-card">
        <div className="liquidity-debt-card-heading"><strong>Latest reported structure</strong><span>{formatDate(summary.latestPeriod)}</span></div>
        <div className="debt-structure-grid">{structureItems.map(([label, value, hint]) => <div key={label}><small>{label}</small><strong>{value}</strong><span>{hint}</span></div>)}</div>
      </article>
    </div>
    <div className="liquidity-debt-table-wrap">
      <div className="liquidity-debt-card-heading"><strong>Balance-sheet history</strong><span>Missing statement rows remain unavailable</span></div>
      <table className="liquidity-debt-table">
        <thead><tr><th>Fiscal period</th><th>Liquid funds</th><th>Total debt</th><th>Debt after liquidity</th><th>Current ratio</th><th>Working capital</th><th>Debt / equity</th><th>Interest coverage</th></tr></thead>
        <tbody>{[...annual].reverse().map((item) => <tr key={item.period}>
          <td><strong>{formatDate(item.period)}</strong><small>{item.liquidityBasis}</small></td>
          <td>{money(item.liquidFunds)}</td><td>{money(item.totalDebt)}<small>{percent(item.totalDebtYoYPercent, true)} YoY</small></td>
          <td className={direction(item.debtAfterLiquidFunds, true)}>{money(item.debtAfterLiquidFunds)}</td><td>{ratio(item.currentRatio)}</td>
          <td className={direction(item.workingCapital)}>{money(item.workingCapital)}</td><td>{ratio(item.totalDebtToEquityRatio)}</td><td>{ratio(item.interestCoverageRatio)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="liquidity-debt-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function CompanyProfitabilityReturnsPanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="profitability-returns-panel profitability-returns-unavailable">
    <div className="profitability-returns-heading"><div><p className="eyebrow">PROFITABILITY, RETURNS & CAPITAL EFFICIENCY</p><h4>No aligned profitability periods available</h4></div><span>Not estimated</span></div>
    <p>The provider returned no usable annual income-statement and balance-sheet combination, so FinTrack does not invent margins or return ratios.</p>
  </section>;

  const summary = data.summary || {};
  const annual = data.annual || [];
  const latest = annual[annual.length - 1] || {};
  const localCurrency = data.currency || currency;
  const percent = (raw, signed = false) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric)) return "—";
    return `${signed && numeric > 0 ? "+" : ""}${numeric.toFixed(1)}%`;
  };
  const ratio = (raw) => {
    const numeric = Number(raw);
    return raw === null || raw === undefined || !Number.isFinite(numeric) ? "—" : `${numeric.toFixed(2)}x`;
  };
  const money = (raw) => formatCompactMoney(raw, localCurrency);
  const formatDate = (raw) => {
    if (!raw) return "Period unavailable";
    const parsed = new Date(`${raw}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? raw : parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  const direction = (raw) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric) || numeric === 0) return "neutral";
    return numeric > 0 ? "positive" : "negative";
  };
  const points = (raw) => {
    const numeric = Number(raw);
    if (raw === null || raw === undefined || !Number.isFinite(numeric)) return "Prior comparison unavailable";
    return `${numeric > 0 ? "+" : ""}${numeric.toFixed(1)} pts vs prior year`;
  };
  const marginMaximum = Math.max(...annual.flatMap((item) => [item.grossMarginPercent, item.operatingMarginPercent, item.netMarginPercent]).map((value) => Math.abs(Number(value) || 0)), 1);
  const marginWidth = (raw) => `${Math.max(2, (Math.abs(Number(raw) || 0) / marginMaximum) * 100)}%`;
  const efficiencyItems = [
    ["Asset turnover", ratio(summary.latestAssetTurnoverRatio), "Revenue / average assets"],
    ["Equity multiplier", ratio(summary.latestEquityMultiplierRatio), "Average assets / average equity"],
    ["Effective tax rate", percent(summary.latestEffectiveTaxRatePercent), "Reported tax / positive pretax income"],
    ["Average invested capital", money(summary.latestAverageInvestedCapital), "Average debt + equity − liquid funds"],
    ["Approximate NOPAT", money(summary.latestNopat), "EBIT after provider-derived tax"],
    ["ROIC trend", String(summary.returnOnInvestedCapitalTrend || "unavailable").replace(/^./, (letter) => letter.toUpperCase()), "Comparable returned periods"],
  ];

  return <section className="profitability-returns-panel" aria-labelledby="profitability-returns-title">
    <div className="profitability-returns-heading">
      <div><p className="eyebrow">PROFITABILITY, RETURNS & CAPITAL EFFICIENCY</p><h4 id="profitability-returns-title">Margins and average-balance return evidence</h4></div>
      <span>{data.coverageLevel || "partial"} statement coverage</span>
    </div>
    {data.financialSectorCaution && <div className="profitability-returns-caution"><strong>Financial-sector context:</strong> ROA and ROE remain descriptive. Industrial ROIC is intentionally withheld because debt and cash are operating inputs for financial institutions.</div>}
    <div className="profitability-returns-summary">
      <article className={direction(summary.latestReturnOnAssetsChangePoints)}><small>Return on assets</small><strong>{percent(summary.latestReturnOnAssetsPercent)}</strong><span>{points(summary.latestReturnOnAssetsChangePoints)}</span></article>
      <article className={direction(summary.latestReturnOnEquityChangePoints)}><small>Return on equity</small><strong>{percent(summary.latestReturnOnEquityPercent)}</strong><span>{points(summary.latestReturnOnEquityChangePoints)}</span></article>
      <article className={direction(summary.latestReturnOnInvestedCapitalChangePoints)}><small>Approximate ROIC</small><strong>{percent(summary.latestReturnOnInvestedCapitalPercent)}</strong><span>{data.financialSectorCaution ? "Withheld for sector comparability" : points(summary.latestReturnOnInvestedCapitalChangePoints)}</span></article>
      <article><small>Asset turnover</small><strong>{ratio(summary.latestAssetTurnoverRatio)}</strong><span>{ratio(summary.latestEquityMultiplierRatio)} equity multiplier</span></article>
    </div>
    <div className="profitability-returns-layout">
      <article className="margin-progression-card">
        <div className="profitability-returns-card-heading"><strong>Margin progression</strong><span>Aligned annual fiscal periods</span></div>
        <div className="margin-progression-legend"><span className="gross">Gross</span><span className="operating">Operating</span><span className="net">Net</span></div>
        <div className="margin-progression-bars">{annual.map((item) => <div key={item.period}>
          <span>{new Date(`${item.period}T00:00:00`).getFullYear()}</span>
          <section>
            <i className="gross"><b className={Number(item.grossMarginPercent) < 0 ? "negative" : ""} style={{ width: marginWidth(item.grossMarginPercent) }} /></i>
            <i className="operating"><b className={Number(item.operatingMarginPercent) < 0 ? "negative" : ""} style={{ width: marginWidth(item.operatingMarginPercent) }} /></i>
            <i className="net"><b className={Number(item.netMarginPercent) < 0 ? "negative" : ""} style={{ width: marginWidth(item.netMarginPercent) }} /></i>
          </section>
          <p><strong>{percent(item.operatingMarginPercent)}</strong><small>operating margin</small></p>
        </div>)}</div>
        <div className="profitability-trend-chips"><span>Operating margin: <strong>{summary.operatingMarginTrend || "unavailable"}</strong></span><span>ROE: <strong>{summary.returnOnEquityTrend || "unavailable"}</strong></span></div>
      </article>
      <article className="capital-efficiency-card">
        <div className="profitability-returns-card-heading"><strong>Latest efficiency bridge</strong><span>{formatDate(summary.latestPeriod)}</span></div>
        <div className="capital-efficiency-grid">{efficiencyItems.map(([label, value, hint]) => <div key={label}><small>{label}</small><strong>{value}</strong><span>{hint}</span></div>)}</div>
      </article>
    </div>
    <div className="profitability-returns-table-wrap">
      <div className="profitability-returns-card-heading"><strong>Profitability and return history</strong><span>Return ratios require beginning and ending balances</span></div>
      <table className="profitability-returns-table">
        <thead><tr><th>Fiscal period</th><th>Gross margin</th><th>Operating margin</th><th>Net margin</th><th>ROA</th><th>ROE</th><th>Approx. ROIC</th><th>Asset turnover</th></tr></thead>
        <tbody>{[...annual].reverse().map((item) => <tr key={item.period} className={item.period === latest.period ? "latest" : ""}>
          <td><strong>{formatDate(item.period)}</strong><small>{item.period === latest.period ? "Latest reported" : "Annual reported"}</small></td>
          <td>{percent(item.grossMarginPercent)}</td><td>{percent(item.operatingMarginPercent)}<small>{points(item.operatingMarginChangePoints)}</small></td><td>{percent(item.netMarginPercent)}</td>
          <td>{percent(item.returnOnAssetsPercent)}</td><td>{percent(item.returnOnEquityPercent)}</td><td>{percent(item.returnOnInvestedCapitalPercent)}</td><td>{ratio(item.assetTurnoverRatio)}</td>
        </tr>)}</tbody>
      </table>
    </div>
    <p className="profitability-returns-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function CompanyOwnershipPanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="ownership-panel ownership-unavailable">
    <div className="ownership-heading"><div><p className="eyebrow">OWNERSHIP & INSIDER ACTIVITY</p><h4>No ownership dataset available for this listing</h4></div><span>Not estimated</span></div>
    <p>The provider returned no holder or insider dataset, so FinTrack does not infer missing ownership activity.</p>
  </section>;

  const major = data.majorOwnership || {};
  const concentration = data.concentration || {};
  const insider = data.insiderSummary || {};
  const institutions = data.institutionalHolders || [];
  const funds = data.mutualFundHolders || [];
  const transactions = data.recentInsiderTransactions || [];
  const coverage = data.coverage || {};
  const insidersHeld = Number(major.insidersPercentHeld || 0);
  const institutionsHeld = Number(major.institutionsPercentHeld || 0);
  const otherHeld = Math.max(0, 100 - insidersHeld - institutionsHeld);
  const compositionTotal = Math.max(100, insidersHeld + institutionsHeld);
  const width = (value) => `${Math.max(0, Math.min(100, (Number(value || 0) / compositionTotal) * 100))}%`;
  const percent = (value, signed = false) => {
    const numeric = Number(value);
    if (value === null || value === undefined || !Number.isFinite(numeric)) return "—";
    return `${signed && numeric > 0 ? "+" : ""}${numeric.toFixed(2)}%`;
  };
  const compact = (value) => formatCompactMoney(value, null);
  const formatDate = (value) => {
    if (!value) return "Date unavailable";
    const parsed = new Date(`${value}T00:00:00`);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  };
  const activityClass = insider.netActivity === "net buying" ? "positive" : insider.netActivity === "net selling" ? "negative" : "neutral";
  const holderTable = (rows, missingMessage) => rows.length ? <div className="ownership-table-wrap"><table className="ownership-table">
    <thead><tr><th>Holder</th><th>Reported</th><th>Held</th><th>Shares</th><th>Position change</th></tr></thead>
    <tbody>{rows.slice(0, 6).map((item, index) => <tr key={`${item.holder}-${index}`}>
      <td><strong>{item.holder}</strong></td><td>{formatDate(item.dateReported)}</td><td>{percent(item.percentHeld)}</td><td>{compact(item.shares)}</td><td className={Number(item.positionChangePercent) >= 0 ? "positive" : "negative"}>{percent(item.positionChangePercent, true)}</td>
    </tr>)}</tbody>
  </table></div> : <p className="ownership-missing">{missingMessage}</p>;

  return <section className="ownership-panel" aria-labelledby="ownership-title">
    <div className="ownership-heading">
      <div><p className="eyebrow">OWNERSHIP & INSIDER ACTIVITY</p><h4 id="ownership-title">Holder concentration and reported insider transactions</h4></div>
      <span>{data.coverageLevel || "partial"} provider coverage</span>
    </div>
    <div className="ownership-summary-grid">
      <article><small>Insiders held</small><strong>{percent(major.insidersPercentHeld)}</strong><span>Provider-reported ownership</span></article>
      <article><small>Institutions held</small><strong>{percent(major.institutionsPercentHeld)}</strong><span>{percent(major.institutionsFloatPercentHeld)} of float</span></article>
      <article><small>Institutional holders</small><strong>{major.institutionsCount ? Number(major.institutionsCount).toLocaleString("en-IN") : "—"}</strong><span>Provider-reported count</span></article>
      <article className={activityClass}><small>Six-month insider activity</small><strong>{String(insider.netActivity || "unavailable").replace(/^./, (letter) => letter.toUpperCase())}</strong><span>{percent(insider.netSharesPercent, true)} of reported insider shares</span></article>
    </div>
    {coverage.majorOwnership && <article className="ownership-composition-card">
      <div className="ownership-card-heading"><strong>Reported ownership composition</strong><span>Categories are provider-reported</span></div>
      <div className="ownership-composition-bar" aria-label={`${percent(insidersHeld)} insiders, ${percent(institutionsHeld)} institutions, ${percent(otherHeld)} other or unclassified`}>
        <i className="insiders" style={{ width: width(insidersHeld) }} /><i className="institutions" style={{ width: width(institutionsHeld) }} /><i className="other" style={{ width: width(otherHeld) }} />
      </div>
      <div className="ownership-composition-legend"><span className="insiders">Insiders {percent(insidersHeld)}</span><span className="institutions">Institutions {percent(institutionsHeld)}</span><span>Other / unclassified {percent(otherHeld)}</span></div>
    </article>}
    <div className="ownership-holder-grid">
      <article><div className="ownership-card-heading"><strong>Top returned institutions</strong><span>{concentration.returnedInstitutionCount || 0} rows · {percent(concentration.topInstitutionsPercentHeld)} combined</span></div>{holderTable(institutions, "Institutional holder rows were not returned for this exchange/listing.")}</article>
      <article><div className="ownership-card-heading"><strong>Top returned mutual funds</strong><span>{concentration.returnedFundCount || 0} rows · {percent(concentration.topFundsPercentHeld)} combined</span></div>{holderTable(funds, "Mutual-fund holder rows were not returned for this exchange/listing.")}</article>
    </div>
    <div className="insider-activity-layout">
      <article className="insider-summary-card">
        <div className="ownership-card-heading"><strong>Insider activity · last 6 months</strong><span>Reported shares and transactions</span></div>
        <div className="insider-summary-grid">
          <div><small>Purchases</small><strong>{compact(insider.purchaseShares)}</strong><span>{insider.purchaseTransactions || 0} transactions</span></div>
          <div><small>Sales</small><strong>{compact(insider.saleShares)}</strong><span>{insider.saleTransactions || 0} transactions</span></div>
          <div className={activityClass}><small>Net shares</small><strong>{compact(insider.netSharesPurchased)}</strong><span>{percent(insider.netSharesPercent, true)}</span></div>
        </div>
      </article>
      <article className="insider-transaction-card">
        <div className="ownership-card-heading"><strong>Recent insider evidence</strong><span>Latest {transactions.length ? formatDate(data.latestInsiderTransactionDate) : "date unavailable"}</span></div>
        {transactions.length ? <div className="insider-transaction-list">{transactions.slice(0, 6).map((item, index) => <div key={`${item.insider}-${item.date}-${index}`}>
          <span className={`transaction-type type-${item.type.replace(/[^a-z]+/g, "-")}`}>{item.type}</span>
          <p><strong>{item.insider}</strong><small>{item.position} · {formatDate(item.date)}</small></p>
          <p><strong>{compact(item.shares)} shares</strong><small>{item.description}{item.reportedValue !== null && item.reportedValue !== undefined ? ` · ${formatCompactMoney(item.reportedValue, currency)}` : ""}</small></p>
        </div>)}</div> : <p className="ownership-missing">Recent insider transaction rows were not returned for this listing.</p>}
      </article>
    </div>
    <p className="ownership-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
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

function CompanyAnalystEstimatePanel({ data, currency }) {
  if (!data || data.status !== "available") return <section className="estimate-panel estimate-unavailable">
    <div className="estimate-heading"><div><p className="eyebrow">ANALYST ESTIMATES & REVISIONS</p><h4>No analyst-estimate dataset available</h4></div><span>Not estimated</span></div>
    <p>The provider returned no EPS, revenue or revision evidence, so FinTrack does not create a consensus outlook.</p>
  </section>;

  const summary = data.summary || {};
  const periods = data.periods || [];
  const coverage = data.coverage || {};
  const current = periods.find((item) => item.period === "0q") || periods[0] || {};
  const currentEps = current.eps || {};
  const currentRevenue = current.revenue || {};
  const currentRevisions = current.revisionCounts || {};
  const mismatchPeriods = new Set(summary.periodsWithBasisMismatch || []);
  const eps = (value) => {
    const numeric = Number(value);
    return value === null || value === undefined || !Number.isFinite(numeric) ? "—" : numeric.toLocaleString("en-IN", { maximumFractionDigits: 4 });
  };
  const percent = (value, signed = false) => {
    const numeric = Number(value);
    if (value === null || value === undefined || !Number.isFinite(numeric)) return "—";
    return `${signed && numeric > 0 ? "+" : ""}${numeric.toFixed(1)}%`;
  };
  const signedNumber = (value) => {
    const numeric = Number(value);
    return value === null || value === undefined || !Number.isFinite(numeric) ? "—" : `${numeric > 0 ? "+" : ""}${numeric.toFixed(4)}`;
  };
  const revisionClass = (signal) => signal === "net upward" ? "positive" : signal === "net downward" ? "negative" : "neutral";
  const directionClass = (value) => value === null || value === undefined || !Number.isFinite(Number(value)) ? "" : Number(value) >= 0 ? "positive" : "negative";
  const nextYear = periods.find((item) => item.period === "+1y") || {};

  return <section className="estimate-panel" aria-labelledby="analyst-estimate-title">
    <div className="estimate-heading">
      <div><p className="eyebrow">ANALYST ESTIMATES & REVISIONS</p><h4 id="analyst-estimate-title">Forecast ranges, growth expectations and revision breadth</h4></div>
      <span>{data.coverageLevel || "partial"} provider coverage</span>
    </div>
    <div className="estimate-summary-grid">
      <article><small>Current-quarter EPS</small><strong>{eps(currentEps.average)}</strong><span>{eps(currentEps.low)}–{eps(currentEps.high)} range · {currentEps.analystCount || 0} analysts</span></article>
      <article><small>Current-quarter revenue</small><strong>{formatCompactMoney(currentRevenue.average, currency)}</strong><span>{percent(currentRevenue.growthPercent, true)} expected growth</span></article>
      <article className={revisionClass(currentRevisions.signal)}><small>30-day revision breadth</small><strong>{String(currentRevisions.signal || "unavailable").replace(/^./, (letter) => letter.toUpperCase())}</strong><span>{currentRevisions.netLast30Days === null || currentRevisions.netLast30Days === undefined ? "No revision counts" : `${Number(currentRevisions.netLast30Days) > 0 ? "+" : ""}${currentRevisions.netLast30Days} net revisions`}</span></article>
      <article><small>Next-year expected growth</small><strong>{percent(nextYear.eps?.growthPercent, true)} EPS</strong><span>{percent(nextYear.revenue?.growthPercent, true)} revenue</span></article>
    </div>
    <div className="estimate-table-wrap">
      <div className="estimate-card-heading"><strong>Forecast-period consensus evidence</strong><span>Ranges and analyst counts are third-party provider fields</span></div>
      <table className="estimate-table">
        <thead><tr><th>Forecast period</th><th>EPS consensus</th><th>EPS growth</th><th>Revenue consensus</th><th>Revenue growth</th><th>Analyst coverage</th><th>Growth comparison</th></tr></thead>
        <tbody>{periods.map((item) => <tr key={item.period}>
          <td><strong>{item.label}</strong><small>{item.period}</small>{mismatchPeriods.has(item.period) && <em>Trend basis differs</em>}</td>
          <td><strong>{eps(item.eps?.average)}</strong><small>{eps(item.eps?.low)}–{eps(item.eps?.high)}</small></td>
          <td className={directionClass(item.eps?.growthPercent)}>{percent(item.eps?.growthPercent, true)}</td>
          <td><strong>{formatCompactMoney(item.revenue?.average, currency)}</strong><small>{formatCompactMoney(item.revenue?.low, currency)}–{formatCompactMoney(item.revenue?.high, currency)}</small></td>
          <td className={directionClass(item.revenue?.growthPercent)}>{percent(item.revenue?.growthPercent, true)}</td>
          <td><strong>{Math.max(item.eps?.analystCount || 0, item.revenue?.analystCount || 0)}</strong><small>max returned count</small></td>
          <td><strong>{percent(item.growthComparison?.companyPercent, true)}</strong><small>provider index {percent(item.growthComparison?.providerIndexPercent, true)}</small></td>
        </tr>)}</tbody>
      </table>
    </div>
    <div className="estimate-revision-grid">
      {periods.map((item) => {
        const revisions = item.revisionCounts || {};
        const trend = item.epsTrend || {};
        const up = Number(revisions.upLast30Days || 0);
        const down = Number(revisions.downLast30Days || 0);
        const total = up + down;
        const hasCounts = coverage.epsRevisionCounts && revisions.upLast30Days !== null && revisions.upLast30Days !== undefined;
        return <article key={`revision-${item.period}`} className={revisionClass(revisions.signal)}>
          <div className="estimate-revision-heading"><div><small>{item.period}</small><strong>{item.label}</strong></div><span>{revisions.signal || "unavailable"}</span></div>
          {hasCounts ? <>
            <div className="revision-counts"><span><b>{revisions.upLast7Days}</b> up · 7d</span><span><b>{revisions.downLast7Days}</b> down · 7d</span><span><b>{revisions.upLast30Days}</b> up · 30d</span><span><b>{revisions.downLast30Days}</b> down · 30d</span></div>
            <div className="revision-breadth-bar"><i className="up" style={{ width: `${total ? (up / total) * 100 : 50}%` }} /><i className="down" style={{ width: `${total ? (down / total) * 100 : 50}%` }} /></div>
          </> : <p>No up/down revision-count dataset was returned.</p>}
          <div className="eps-trend-strip"><span>EPS trend now <strong>{eps(trend.current)}</strong></span><span>30d ago <strong>{eps(trend.thirtyDaysAgo)}</strong></span><span>Change <strong className={directionClass(trend.change30Days)}>{signedNumber(trend.change30Days)}</strong></span></div>
          {trend.matchesPublishedAverageBasis === false && <p className="estimate-basis-warning">Trend series basis differs from the published EPS estimate range; values are not merged.</p>}
        </article>;
      })}
    </div>
    <p className="estimate-method"><strong>Method:</strong> {data.method} {data.disclaimer}</p>
  </section>;
}

function RiskBenchmarkPanel({ data, symbol, onExplain }) {
  if (!data || data.status === "unavailable") return <section className="risk-benchmark-panel risk-unavailable">
    <div className="risk-heading"><div><p className="eyebrow">RISK & BENCHMARK INTELLIGENCE</p><h3>Historical risk evidence unavailable</h3></div><span>Provider unavailable</span></div>
    <p className="risk-caveat">{data?.message || "The prediction above remains separate from this optional historical comparison."}</p>
  </section>;
  const asset = data.asset || {};
  const comparison = data.comparison;
  const benchmark = data.benchmark;
  const signed = (value) => value === null || value === undefined ? "—" : `${Number(value) > 0 ? "+" : ""}${Number(value).toFixed(2)} pp`;
  const explainRiskMetric = (label, value, hint) => onExplain(label, value, `${hint}. Historical metric context for ${symbol}; reference index ${benchmark?.name || "unavailable"}`);
  return <section className="risk-benchmark-panel" aria-labelledby="risk-benchmark-title">
    <div className="risk-heading">
      <div><p className="eyebrow">RISK & BENCHMARK INTELLIGENCE</p><h3 id="risk-benchmark-title">How has {symbol} behaved versus the broad market?</h3><p>{data.period} · close-to-close evidence</p></div>
      <span className={`risk-band risk-${asset.riskBand || "contained"}`}>{asset.riskBand || "historical"} risk</span>
    </div>
    <div className="risk-layout">
      <div className="risk-chart-card">
        <div className="risk-chart-title"><strong>Normalized performance</strong><button type="button" className="metric-explain-button" onClick={() => onExplain("Normalized performance", "Period start = 100", `Historical metric context for ${symbol}; reference index ${benchmark?.name || "unavailable"}`)}>? Explain</button></div>
        <BenchmarkChart history={data.normalizedHistory || []} symbol={symbol} benchmark={benchmark} />
      </div>
      <div className="risk-metric-grid">
        <RiskMetric label="Period return" value={formatPercent(asset.periodReturnPercent)} hint={`${asset.observations || 0} daily returns`} onExplain={explainRiskMetric} />
        <RiskMetric label="Annualized volatility" value={formatPercent(asset.annualizedVolatilityPercent)} hint="Dispersion, not direction" onExplain={explainRiskMetric} />
        <RiskMetric label="Maximum drawdown" value={formatPercent(asset.maxDrawdownPercent)} hint="Largest peak-to-trough fall" onExplain={explainRiskMetric} />
        <RiskMetric label="95% historical VaR" value={formatPercent(asset.historicalVar95Percent)} hint="Observed one-day loss threshold" onExplain={explainRiskMetric} />
        <RiskMetric label={benchmark ? `Beta vs ${benchmark.symbol}` : "Beta"} value={comparison?.beta ?? "—"} hint={benchmark ? `Correlation ${comparison?.correlation ?? "—"}` : "No self-comparison for an index"} onExplain={explainRiskMetric} />
        <RiskMetric label="Relative return" value={signed(comparison?.relativeReturnPoints)} hint={comparison ? `${comparison.relativePerformance} vs ${benchmark?.name}` : "Broad benchmark not applicable"} onExplain={explainRiskMetric} />
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

function RiskMetric({ label, value, hint, onExplain }) {
  return <article><div className="explainable-metric-heading"><small>{label}</small><button type="button" className="metric-explain-button" onClick={() => onExplain(label, value, hint)} aria-label={`Explain ${label}`}>?</button></div><strong>{value}</strong><span>{hint}</span></article>;
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
