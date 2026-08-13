import { useLayoutEffect, useRef, useState } from "react";
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

export default function App() {
  const [activeTab, setActiveTab] = useState("markets");
  const [researchSymbol, setResearchSymbol] = useState("^NSEI");
  const [draggingTab, setDraggingTab] = useState(false);
  const [sliderStyle, setSliderStyle] = useState({ left: 8, width: 0 });
  const tabbarRef = useRef(null);
  const tabRefs = useRef([]);
  const dragRef = useRef(null);

  const activeIndex = Math.max(0, tabs.findIndex((tab) => tab.id === activeTab));

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
          <h1>Markets and currencies,<br/><span>explained with evidence.</span></h1>
          <p className="hero-copy">A focused public dashboard for global indices, company quotes, INR exchange rates, market news and grounded AI research.</p>
          <div className="hero-pills"><span>24 market instruments</span><span>160+ currencies</span><span>Current headlines</span><span>Timestamped evidence</span></div>
        </div>
        <div className="hero-visual" aria-hidden="true"><div className="orb orb-one"/><div className="orb orb-two"/><div className="visual-card"><small>Research principle</small><strong>Verify the source.<br/>Read the timestamp.<br/>Understand uncertainty.</strong><span>Never a guaranteed buy/sell call.</span></div></div>
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
