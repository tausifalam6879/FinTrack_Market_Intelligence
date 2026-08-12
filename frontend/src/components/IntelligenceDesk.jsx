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
      if (loadSequenceRef.current === requestId) setResult(nextResult);
    } catch {
      if (!silent && loadSequenceRef.current === requestId) setError(`Research for ${normalized} is temporarily unavailable.`);
    } finally {
      if (loadSequenceRef.current === requestId) setLoading(false);
    }
    await Promise.allSettled([monitoringRequest, experimentsRequest, documentsRequest]);
  };

  useEffect(() => { load(initialSymbol, false, true); }, [initialSymbol]);

  const analysis = result?.data;
  const history = useMemo(() => analysis?.history || [], [analysis]);
  const modelComparisons = analysis?.model?.modelsCompared || [];
  const featureImportance = analysis?.model?.featureImportance || [];
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

function ModelRegistryPanel({ status, loading, error, activeModel }) {
  const approved = status?.approvedModel;
  const latest = status?.latestModelRun;
  const monitoring = status?.predictionMonitoring;
  const approvedServing = status?.servingMode === "approved_artifact";
  return <section className={`registry-panel ${approvedServing ? "registry-approved" : "registry-fallback"}`} aria-labelledby="registry-title">
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
