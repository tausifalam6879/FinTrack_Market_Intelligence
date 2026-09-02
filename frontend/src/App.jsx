import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import MarketPulse from "./components/MarketPulse";
import CurrencyDesk from "./components/CurrencyDesk";
import IntelligenceDesk from "./components/IntelligenceDesk";
import NewsDesk from "./components/NewsDesk";
import { marketApi } from "./services/marketApi";

const tabs = [
  { id: "markets", label: "Market Pulse", shortLabel: "Market", icon: "↗" },
  { id: "currency", label: "INR Currency Desk", shortLabel: "Currency", icon: "₹" },
  { id: "news", label: "Market News", shortLabel: "News", icon: "◫" },
  { id: "intelligence", label: "Intelligence & MLOps", shortLabel: "MLOps", icon: "✦" }
];

const validCurrencyQuote = (item) => {
  if (item?.inrValue === null || item?.inrValue === undefined || item?.inrValue === "") return false;
  const parsed = Number(item.inrValue);
  return Number.isFinite(parsed) && parsed > 0;
};

const displayCurrencyQuote = (item) => validCurrencyQuote(item)
  ? Number(item.inrValue).toLocaleString("en-IN", { maximumFractionDigits: 2 })
  : "—";

const networkProviderContext = (online = window.navigator.onLine) => ({
  provider: online ? "Gemini" : "Ollama",
  status: online ? "online" : "offline mode"
});

const configuredProviderLabel = (provider, online) => {
  const normalized = String(provider || "").trim().toLowerCase();
  if (normalized === "ollama" || normalized === "local") return "Ollama";
  if (normalized === "gemini") return online ? "Gemini" : "Ollama";
  if (normalized === "hybrid" || normalized === "auto") return online ? "Gemini" : "Ollama";
  return online ? "Gemini" : "Ollama";
};

const answerProviderContext = (meta = {}) => {
  const provider = String(meta.llmProvider || "").trim().toLowerCase();
  const status = String(meta.llmStatus || "").trim().toLowerCase();
  const verifiedFallback = meta.llmUsed === false || meta.llmAnswerAccepted === false || ["offline", "grounding_fallback"].includes(status);
  if (verifiedFallback) return { provider: "Verified fallback", status: "verified" };
  if (provider === "ollama" || provider === "local") return { provider: "Ollama", status: "answered" };
  if (provider === "gemini") return { provider: "Gemini", status: "answered" };
  return { provider: "Verified fallback", status: "verified" };
};

const tabDetails = {
  markets: {
    video: "./media/market-pulse.mp4", eyebrow: "LIVE MARKET PULSE", title: "See the market before you react.",
    copy: "A moving snapshot of indices, companies and sector momentum — built for observation, not impulsive calls.",
    facts: ["Live watchlist", "Sector movement", "Price alerts"]
  },
  currency: {
    video: "./media/currency-and-mlops.mp4", clipStart: 0, clipEnd: 5, eyebrow: "INR CURRENCY DESK", title: "Global currency moves, in rupees.",
    copy: "Compare global currencies with INR and understand the rate behind an international price.",
    facts: ["160+ currencies", "INR conversion", "Searchable directory"]
  },
  news: {
    video: "./media/market-news.mp4", eyebrow: "MARKET NEWS DESK", title: "Headlines with context, not noise.",
    copy: "Browse current market stories, see their themes and open the original source when it matters.",
    facts: ["Current headlines", "Topic filters", "Source links"]
  },
  intelligence: {
    video: "./media/currency-and-mlops.mp4", clipStart: 5, clipEnd: 10, eyebrow: "OPEN INTELLIGENCE", title: "Research a company with evidence.",
    copy: "Combine market data, transparent model signals, company evidence and concise AI explanations.",
    facts: ["ML monitoring", "Company research", "Evidence-first answers"]
  }
};

export default function App() {
  const [activeTab, setActiveTab] = useState("markets");
  const [researchSymbol, setResearchSymbol] = useState("^NSEI");
  const [draggingTab, setDraggingTab] = useState(false);
  const [sliderStyle, setSliderStyle] = useState({ left: 8, width: 0 });
  const [marketQuotes, setMarketQuotes] = useState([]);
  const [rotatingQuoteIndex, setRotatingQuoteIndex] = useState(0);
  const [marketMenuOpen, setMarketMenuOpen] = useState(false);
  const [marketContext, setMarketContext] = useState(() => {
    const currencyData = marketApi.seed.currencies()?.data;
    const currencies = currencyData?.currencies || [];
    const analysis = marketApi.seed.analysis("^NSEI")?.data;
    return {
      usd: currencies.find((item) => item.code === "USD" && validCurrencyQuote(item)) || null,
      gold: analysis?.macroFactor?.factors?.find((item) => item.factor === "Gold") || null,
      currencyCount: Object.keys(currencyData?.referenceRates || {}).length,
      currencyAsOf: currencyData?.generatedAt || null
    };
  });
  const [newsContext, setNewsContext] = useState(() => {
    const news = marketApi.seed.newsFeed()?.data;
    return { count: news?.articles?.length || 0, generatedAt: news?.generatedAt || null };
  });
  const [operationsContext, setOperationsContext] = useState(() => ({ ...networkProviderContext(), database: "Checking" }));
  const tabbarRef = useRef(null);
  const tabRefs = useRef([]);
  const dragRef = useRef(null);
  const visualVideoRef = useRef(null);

  const activeIndex = Math.max(0, tabs.findIndex((tab) => tab.id === activeTab));
  const activeSection = tabDetails[activeTab];
  const rotatingQuote = marketQuotes[rotatingQuoteIndex % Math.max(1, marketQuotes.length)];

  const applyCurrencyContext = useCallback((response) => {
    const data = response?.data || response;
    if (!data) return;
    setMarketContext((current) => ({
      ...current,
      usd: data.currencies?.find((item) => item.code === "USD" && validCurrencyQuote(item)) || current.usd,
      currencyCount: Object.keys(data.referenceRates || {}).length || current.currencyCount,
      currencyAsOf: data.generatedAt || current.currencyAsOf
    }));
  }, []);

  const applyNewsContext = useCallback((response) => {
    const data = response?.data || response;
    if (!data) return;
    setNewsContext({ count: data.articles?.length || 0, generatedAt: data.generatedAt || null });
  }, []);

  const refreshMarketIndicators = useCallback(async (refresh = false) => {
    const [currencyResult, analysisResult] = await Promise.allSettled([
      marketApi.currencies(refresh),
      marketApi.analysis("^NSEI", refresh)
    ]);
    if (currencyResult.status === "fulfilled") applyCurrencyContext(currencyResult.value);
    if (analysisResult.status === "fulfilled") {
      const gold = analysisResult.value?.data?.macroFactor?.factors?.find((item) => item.factor === "Gold");
      if (gold) setMarketContext((current) => ({ ...current, gold }));
    }
  }, [applyCurrencyContext]);

  useEffect(() => {
    if (marketQuotes.length < 2) return undefined;
    const intervalId = window.setInterval(() => {
      setRotatingQuoteIndex((current) => {
        const jump = 1 + Math.floor(Math.random() * (marketQuotes.length - 1));
        return (current + jump) % marketQuotes.length;
      });
    }, 6000);
    return () => window.clearInterval(intervalId);
  }, [marketQuotes.length]);

  useEffect(() => {
    refreshMarketIndicators(false);
    marketApi.newsFeed(false, 20).then(applyNewsContext).catch(() => undefined);
    marketApi.operationsStatus().then((status) => setOperationsContext((current) => {
      const online = window.navigator.onLine;
      return {
        ...current,
        provider: configuredProviderLabel(status?.dependencies?.languageModel?.provider, online),
        status: online ? status?.dependencies?.languageModel?.status || status?.status || "ready" : "offline mode",
        database: status?.dependencies?.database?.backend || "Database"
      };
    })).catch(() => setOperationsContext((current) => ({ ...current, ...networkProviderContext() })));
  }, [applyNewsContext, refreshMarketIndicators]);

  useEffect(() => {
    const syncNetworkProvider = () => setOperationsContext((current) => ({ ...current, ...networkProviderContext() }));
    window.addEventListener("online", syncNetworkProvider);
    window.addEventListener("offline", syncNetworkProvider);
    return () => {
      window.removeEventListener("online", syncNetworkProvider);
      window.removeEventListener("offline", syncNetworkProvider);
    };
  }, []);

  const applyAnswerProvider = useCallback((meta) => {
    setOperationsContext((current) => ({ ...current, ...answerProviderContext(meta) }));
  }, []);

  useEffect(() => {
    if (!marketMenuOpen) return undefined;
    const closeOnEscape = (event) => { if (event.key === "Escape") setMarketMenuOpen(false); };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [marketMenuOpen]);

  useEffect(() => {
    const video = visualVideoRef.current;
    if (!video) return undefined;
    const start = activeSection.clipStart || 0;
    const end = activeSection.clipEnd;
    const begin = () => {
      video.currentTime = start;
      video.play().catch(() => undefined);
    };
    const restartClip = () => { if (end && video.currentTime >= end) video.currentTime = start; };
    const restartVideo = () => {
      video.currentTime = start;
      video.play().catch(() => undefined);
    };
    const keepVideoInline = () => {
      if (document.pictureInPictureElement === video && document.exitPictureInPicture) {
        document.exitPictureInPicture().catch(() => undefined);
      }
      if (
        video.webkitPresentationMode
        && video.webkitPresentationMode !== "inline"
        && video.webkitSetPresentationMode
      ) {
        video.webkitSetPresentationMode("inline");
      }
    };
    video.addEventListener("loadedmetadata", begin, { once: true });
    video.addEventListener("timeupdate", restartClip);
    video.addEventListener("ended", restartVideo);
    video.addEventListener("enterpictureinpicture", keepVideoInline);
    video.addEventListener("webkitpresentationmodechanged", keepVideoInline);
    video.load();
    if (video.readyState >= 1) begin();
    return () => {
      video.removeEventListener("loadedmetadata", begin);
      video.removeEventListener("timeupdate", restartClip);
      video.removeEventListener("ended", restartVideo);
      video.removeEventListener("enterpictureinpicture", keepVideoInline);
      video.removeEventListener("webkitpresentationmodechanged", keepVideoInline);
    };
  }, [activeSection]);

  useLayoutEffect(() => {
    const positionSlider = () => {
      const activeButton = tabRefs.current[activeIndex];
      if (!activeButton) return;
      setSliderStyle({ left: activeButton.offsetLeft, width: activeButton.offsetWidth });
    };

    positionSlider();
    window.addEventListener("resize", positionSlider);
    return () => window.removeEventListener("resize", positionSlider);
  }, [activeIndex]);

  const beginTabDrag = (event, index) => {
    event.currentTarget.setPointerCapture?.(event.pointerId);
    dragRef.current = { pointerId: event.pointerId, moved: false };
    setDraggingTab(true);
    setActiveTab(tabs[index].id);
  };

  const moveTabDrag = (event) => {
    if (!dragRef.current || !tabbarRef.current) return;
    const barRect = tabbarRef.current.getBoundingClientRect();
    const pointerX = event.clientX - barRect.left + tabbarRef.current.scrollLeft;
    let closestIndex = 0;
    let closestDistance = Number.POSITIVE_INFINITY;

    tabRefs.current.forEach((button, index) => {
      if (!button) return;
      const distance = Math.abs(pointerX - (button.offsetLeft + button.offsetWidth / 2));
      if (distance < closestDistance) {
        closestDistance = distance;
        closestIndex = index;
      }
    });

    dragRef.current.moved = true;
    setActiveTab(tabs[closestIndex].id);
  };

  const endTabDrag = (event) => {
    if (dragRef.current?.pointerId === event.pointerId) {
      event.currentTarget.releasePointerCapture?.(event.pointerId);
    }
    dragRef.current = null;
    setDraggingTab(false);
  };

  const handleTabKey = (event, index) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const direction = event.key === 'ArrowRight' ? 1 : -1;
    const nextIndex = (index + direction + tabs.length) % tabs.length;
    setActiveTab(tabs[nextIndex].id);
    tabRefs.current[nextIndex]?.focus();
  };

  const openResearch = (symbol) => { setResearchSymbol(symbol); setActiveTab("intelligence"); window.scrollTo({ top: 0, behavior: "smooth" }); };

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand-cluster">
        {activeTab === "markets" && <button className="market-menu-toggle" type="button" aria-label="Open Market Pulse menu" aria-expanded={marketMenuOpen} onClick={() => setMarketMenuOpen(true)}><span /><span /><span /></button>}
        <a className="brand" href="#top" aria-label="FinTrack Market Intelligence home"><img className="brand-mark" src="./fintrack-mark.svg" alt="" /><span><strong>FinTrack</strong><small>Market Intelligence</small></span></a>
      </div>
      <nav ref={tabbarRef} className={`tabbar topbar-tabs${draggingTab ? " dragging" : ""}`} aria-label="Dashboard sections" role="tablist">
        <span className="tab-slider" style={{ left: sliderStyle.left, width: sliderStyle.width }} aria-hidden="true" />
        {tabs.map((tab, index) => <button
          key={tab.id}
          ref={(node) => { tabRefs.current[index] = node; }}
          type="button"
          role="tab"
          aria-label={tab.label}
          aria-selected={activeTab === tab.id}
          className={activeTab === tab.id ? "active" : ""}
          onClick={() => setActiveTab(tab.id)}
          onPointerDown={(event) => beginTabDrag(event, index)}
          onPointerMove={moveTabDrag}
          onPointerUp={endTabDrag}
          onPointerCancel={endTabDrag}
          onKeyDown={(event) => handleTabKey(event, index)}
          title={activeTab === tab.id ? "Drag this selector left or right" : `Open ${tab.label}`}
        ><span>{tab.icon}</span><b>{tab.shortLabel}</b></button>)}
      </nav>
      {activeTab === "markets" && <div className="navbar-market-context">
        {rotatingQuote && <button className="navbar-quote" key={rotatingQuote.symbol} onClick={() => openResearch(rotatingQuote.symbol)} aria-label={`Open ${rotatingQuote.name} research`}>
          <span><small>MARKET NOW</small><strong>{rotatingQuote.name}</strong></span>
          <span><b>{Number(rotatingQuote.price).toLocaleString("en-IN", { maximumFractionDigits: 2 })}</b><em className={Number(rotatingQuote.changePercent) >= 0 ? "positive" : "negative"}>{Number(rotatingQuote.changePercent) >= 0 ? "+" : ""}{rotatingQuote.changePercent}%</em></span>
        </button>}
        {marketContext.gold && <div className="market-context-tile" aria-label="Verified gold market move"><small>GOLD MOVE</small><strong className={Number(marketContext.gold.changePercent) >= 0 ? "positive" : "negative"}>{Number(marketContext.gold.changePercent) >= 0 ? "+" : ""}{marketContext.gold.changePercent}%</strong></div>}
        {marketContext.usd && <div className="market-context-tile" aria-label="Verified US dollar to Indian rupee rate"><small>USD/INR</small><strong>₹{displayCurrencyQuote(marketContext.usd)}</strong></div>}
      </div>}
      {activeTab === "currency" && <div className="navbar-market-context" aria-label="Currency desk status">
        {marketContext.usd && <div className="market-context-tile"><small>USD/INR NOW</small><strong>₹{displayCurrencyQuote(marketContext.usd)}</strong></div>}
        <div className="market-context-tile"><small>RATE DIRECTORY</small><strong>{marketContext.currencyCount || "—"} pairs</strong></div>
      </div>}
      {activeTab === "news" && <div className="navbar-market-context" aria-label="News desk status">
        <div className="market-context-tile"><small>HEADLINES</small><strong>{newsContext.count || "—"} verified</strong></div>
        <div className="market-context-tile"><small>FEED CHECKED</small><strong>{newsContext.generatedAt ? new Date(newsContext.generatedAt).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" }) : "Loading"}</strong></div>
      </div>}
      {activeTab === "intelligence" && <div className="navbar-market-context" aria-label="Intelligence service status">
        <div className="market-context-tile"><small>AI PROVIDER</small><strong>{operationsContext.provider}</strong></div>
        <div className="market-context-tile"><small>SERVICE</small><strong className={operationsContext.status === "ready" || operationsContext.status === "configured" ? "positive" : ""}>{operationsContext.status}</strong></div>
      </div>}
      <div className={`public-chip${activeTab === "markets" ? " compact" : ""}`} title="Public research dashboard"><span /><b>{activeTab === "markets" ? "Public" : "Public dashboard"}</b></div>
    </header>

    {activeTab === "markets" && <>
      <button className={`market-drawer-backdrop${marketMenuOpen ? " open" : ""}`} aria-label="Close Market Pulse menu" tabIndex={marketMenuOpen ? 0 : -1} onClick={() => setMarketMenuOpen(false)} />
      <aside className={`market-side-drawer${marketMenuOpen ? " open" : ""}`} aria-hidden={!marketMenuOpen}>
        <div className="market-drawer-heading"><div><small>FINTRACK</small><strong>Market Pulse</strong></div><button aria-label="Close Market Pulse menu" onClick={() => setMarketMenuOpen(false)}>×</button></div>
        <nav aria-label="Market Pulse navigation">
          <p>MARKET VIEW</p>
          <a href="#market-overview" onClick={() => setMarketMenuOpen(false)}><span>⌂</span><b>Overview</b><small>Live market status</small></a>
          <a href="#daily-market" onClick={() => setMarketMenuOpen(false)}><span>⌁</span><b>Daily chart</b><small>Inspect each close</small></a>
          <a href="#market-statistics" onClick={() => setMarketMenuOpen(false)}><span>▦</span><b>Market statistics</b><small>Board breadth</small></a>
          <p>RESEARCH TOOLS</p>
          <a href="#company-search" onClick={() => setMarketMenuOpen(false)}><span>⌕</span><b>Find a company</b><small>Search by name</small></a>
          <a href="#risk-alerts" onClick={() => setMarketMenuOpen(false)}><span>!</span><b>Risk alerts</b><small>Downside monitor</small></a>
          <a href="#global-markets" onClick={() => setMarketMenuOpen(false)}><span>◎</span><b>Global indices</b><small>Major markets</small></a>
        </nav>
        <p className="market-drawer-note">These links open real sections on this page. Quotes may be delayed.</p>
      </aside>
    </>}

    <main id="top" className={activeTab === "markets" ? "market-page-active" : activeTab === "intelligence" ? "intelligence-page-active" : ""}>
      {activeTab === "markets" && marketQuotes.length > 0 && <MarketOpeningRibbon quotes={marketQuotes} onResearch={openResearch} />}
      <section className="hero">
        <div>
          <p className="eyebrow">NO LOGIN · NO PERSONAL DATA</p>
          <h1>{activeSection.title}</h1>
          <p className="hero-copy">{activeSection.copy}</p>
          <div className="hero-pills">{activeSection.facts.map((fact) => <span key={fact}>{fact}</span>)}</div>
        </div>
        <div className="hero-visual">
          <video
            ref={visualVideoRef}
            key={activeTab}
            className="hero-video"
            src={activeSection.video}
            autoPlay
            muted
            playsInline
            disablePictureInPicture
            disableRemotePlayback
            controlsList="nodownload noremoteplayback nopictureinpicture"
            preload="auto"
            loop={!activeSection.clipEnd}
            aria-label={`${tabs[activeIndex].label} visual preview`}
          />
        </div>
      </section>

      {activeTab === "markets" && <MarketPulse onResearch={openResearch} onQuotesChange={setMarketQuotes} onMarketContextRefresh={refreshMarketIndicators} />}
      {activeTab === "currency" && <CurrencyDesk onDataChange={applyCurrencyContext} />}
      {activeTab === "news" && <NewsDesk onResearch={openResearch} onDataChange={applyNewsContext} />}
      {activeTab === "intelligence" && <IntelligenceDesk initialSymbol={researchSymbol} onProviderChange={applyAnswerProvider} />}
    </main>

    <footer><div><strong>FinTrack Market Intelligence</strong><p>Public educational research dashboard. No account or personal finance data is collected.</p></div><p>Market data may be delayed. Not investment advice.</p></footer>
  </div>;
}

function MarketOpeningRibbon({ quotes, onResearch }) {
  const items = useMemo(() => quotes.slice(0, 14), [quotes]);
  const renderItems = (duplicate = false) => items.map((quote) => {
    const positive = Number(quote.changePercent) >= 0;
    return <button key={`${duplicate ? "copy" : "main"}-${quote.symbol}`} tabIndex={duplicate ? -1 : 0} aria-hidden={duplicate || undefined} onClick={() => onResearch(quote.symbol)}>
      <strong>{quote.name}</strong><span>{Number(quote.price).toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span><em className={positive ? "positive" : "negative"}>{positive ? "+" : ""}{quote.changePercent}%</em>
    </button>;
  });
  return <section className="market-opening-ribbon" aria-label="Live rotating market quotes">
    <div className="market-ribbon-label"><span>LIVE</span><strong>Market board</strong><small>Hover to pause</small></div>
    <div className="market-ribbon-window"><div className="market-ribbon-track"><div>{renderItems(false)}</div><div aria-hidden="true">{renderItems(true)}</div></div></div>
  </section>;
}
