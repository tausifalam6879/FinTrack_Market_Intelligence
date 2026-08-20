import { useEffect, useLayoutEffect, useRef, useState } from "react";
import MarketPulse from "./components/MarketPulse";
import CurrencyDesk from "./components/CurrencyDesk";
import IntelligenceDesk from "./components/IntelligenceDesk";
import NewsDesk from "./components/NewsDesk";

const tabs = [
  { id: "markets", label: "Market Pulse", icon: "↗" },
  { id: "currency", label: "INR Currency Desk", icon: "₹" },
  { id: "news", label: "Market News", icon: "◫" },
  { id: "intelligence", label: "Intelligence & MLOps", icon: "✦" }
];

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
  const tabbarRef = useRef(null);
  const tabRefs = useRef([]);
  const dragRef = useRef(null);
  const visualVideoRef = useRef(null);

  const activeIndex = Math.max(0, tabs.findIndex((tab) => tab.id === activeTab));
  const activeSection = tabDetails[activeTab];

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
    video.addEventListener("loadedmetadata", begin, { once: true });
    video.addEventListener("timeupdate", restartClip);
    video.addEventListener("ended", restartVideo);
    video.load();
    if (video.readyState >= 1) begin();
    return () => {
      video.removeEventListener("loadedmetadata", begin);
      video.removeEventListener("timeupdate", restartClip);
      video.removeEventListener("ended", restartVideo);
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
      <a className="brand" href="#top" aria-label="FinTrack Market Intelligence home"><span className="brand-mark">F</span><span><strong>FinTrack</strong><small>Market Intelligence</small></span></a>
      <div className="public-chip"><span /> Public research dashboard</div>
    </header>

    <main id="top">
      <section className="hero">
        <div>
          <p className="eyebrow">NO LOGIN · NO PERSONAL DATA</p>
          <h1>{activeSection.title}</h1>
          <p className="hero-copy">{activeSection.copy}</p>
          <div className="hero-pills">{activeSection.facts.map((fact) => <span key={fact}>{fact}</span>)}</div>
        </div>
        <div className="hero-visual">
          <video ref={visualVideoRef} key={activeTab} className="hero-video" src={activeSection.video} muted playsInline preload="auto" loop={!activeSection.clipEnd} aria-label={`${tabs[activeIndex].label} visual preview`} />
        </div>
      </section>

      <nav ref={tabbarRef} className={`tabbar${draggingTab ? " dragging" : ""}`} aria-label="Dashboard sections" role="tablist">
        <span className="tab-slider" style={{ left: sliderStyle.left, width: sliderStyle.width }} aria-hidden="true" />
        {tabs.map((tab, index) => <button
          key={tab.id}
          ref={(node) => { tabRefs.current[index] = node; }}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          className={activeTab === tab.id ? "active" : ""}
          onClick={() => setActiveTab(tab.id)}
          onPointerDown={(event) => beginTabDrag(event, index)}
          onPointerMove={moveTabDrag}
          onPointerUp={endTabDrag}
          onPointerCancel={endTabDrag}
          onKeyDown={(event) => handleTabKey(event, index)}
          title={activeTab === tab.id ? "Drag this selector left or right" : `Open ${tab.label}`}
        ><span>{tab.icon}</span>{tab.label}</button>)}
      </nav>

      {activeTab === "markets" && <MarketPulse onResearch={openResearch} />}
      {activeTab === "currency" && <CurrencyDesk />}
      {activeTab === "news" && <NewsDesk onResearch={openResearch} />}
      {activeTab === "intelligence" && <IntelligenceDesk initialSymbol={researchSymbol} />}
    </main>

    <footer><div><strong>FinTrack Market Intelligence</strong><p>Public educational research dashboard. No account or personal finance data is collected.</p></div><p>Market data may be delayed. Not investment advice.</p></footer>
  </div>;
}
