import { useEffect, useRef, useState } from 'react';
import { marketApi } from '../services/marketApi';
import { PORTFOLIO_KEY, portfolioSummary, validateHolding, portfolioScenario, portfolioRisk, portfolioQuote as quoteFrom } from '../services/portfolio';

const readHoldings = () => {
  try {
    const value=JSON.parse(localStorage.getItem(PORTFOLIO_KEY) || '[]');
    if (!Array.isArray(value)) return [];
    const unique=new Map();
    for (const item of value.slice(0,100)) {
      try { const h=validateHolding(item); unique.set(h.symbol,h); } catch { /* Ignore malformed records. */ }
    }
    return [...unique.values()];
  } catch { return []; }
};
const money = (value,currency) => value == null ? 'Unavailable' : new Intl.NumberFormat('en-IN',
  {style:'currency',currency,maximumFractionDigits:2}).format(value);

export default function PortfolioPanel({ analysis, mode }) {
  const [holdings,setHoldings]=useState(readHoldings);
  const [quotes,setQuotes]=useState({});
  const [quantity,setQuantity]=useState('');
  const [buyPrice,setBuyPrice]=useState('');
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const mounted=useRef(true);
  useEffect(()=>{mounted.current=true; return ()=>{mounted.current=false;};},[]);
  useEffect(()=>{
    const existing=holdings.find(h=>h.symbol===analysis.symbol);
    setQuantity(existing ? String(existing.quantity) : '');
    setBuyPrice(existing ? String(existing.buyPrice) : '');
  },[analysis.symbol,holdings]);
  useEffect(()=>{
    const seeds={};
    for (const h of holdings) {
      const seed=marketApi.seed.analysis(h.symbol);
      if(seed) seeds[h.symbol]=quoteFrom(seed);
    }
    setQuotes(current=>({...seeds,...current,[analysis.symbol]:{...current[analysis.symbol],...quoteFrom({data:analysis,mode})}}));
  },[analysis,mode,holdings]);
  const save = next => {
    try { localStorage.setItem(PORTFOLIO_KEY,JSON.stringify(next)); setError(''); }
    catch { setError('Browser storage is unavailable. Changes will last only until this page closes.'); }
    setHoldings(next);
  };
  const submit = event => {
    event.preventDefault();
    try {
      const holding=validateHolding({symbol:analysis.symbol,name:analysis.name,
        currency:analysis.expectedRange?.currency,quantity,buyPrice});
      if(holdings.length>=100 && !holdings.some(h=>h.symbol===holding.symbol)) throw new Error('Up to 100 holdings are supported.');
      save([...holdings.filter(h=>h.symbol!==holding.symbol),holding]);
    } catch(e) {setError(e.message);}
  };
  const refresh = async () => {
    setBusy(true); setError('');
    let failed=0;
    // Keep quote requests bounded; holdings and purchase prices never leave the browser.
    for(let i=0;i<holdings.length;i+=3) {
      if(!mounted.current) return;
      const batch=await Promise.allSettled(holdings.slice(i,i+3).map(async h=>{
        const [analysisResult,companyResult]=await Promise.allSettled([marketApi.analysis(h.symbol,true),marketApi.company(h.symbol)]);
        if(analysisResult.status!=='fulfilled') throw analysisResult.reason;
        const quote=quoteFrom(analysisResult.value);
        if(companyResult.status==='fulfilled') quote.sector=companyResult.value.data?.sector || 'Unknown';
        return [h.symbol,quote];
      }));
      if(!mounted.current) return;
      const updates={};
      batch.forEach(r=>{if(r.status==='fulfilled')updates[r.value[0]]=r.value[1];else failed++;});
      setQuotes(current=>{
        const next={...current};
        for(const h of holdings.slice(i,i+3)) if(!updates[h.symbol] && next[h.symbol]) next[h.symbol]={...next[h.symbol],mode:'cache'};
        return {...next,...updates};
      });
    }
    if(failed)setError(`${failed} quotes could not refresh. Any saved quotes are labelled as cached.`);
    setBusy(false);
  };
  const groups=portfolioSummary(holdings,quotes);
  return <section className="portfolio-panel" aria-label="My portfolio">
    <div className="section-heading split-heading"><div><p className="eyebrow">MY PORTFOLIO</p><h3>Track your holdings</h3>
      <p>Saved in this browser only. Enter your current quantity and average buy price; saving replaces this company's holding.</p></div>
      <button type="button" onClick={refresh} disabled={busy||!holdings.length}>{busy?'Refreshing quotes…':'Refresh portfolio quotes'}</button></div>
    {analysis.symbol.startsWith('^') ? <p>Select a company above to add a holding. Indices cannot be held directly.</p> :
    <form className="portfolio-form" onSubmit={submit}>
      <strong>{analysis.name || analysis.symbol} · {analysis.expectedRange?.currency || 'Currency unavailable'}</strong>
      <label>Quantity<input type="number" step="any" min="0.00000001" required value={quantity} onChange={e=>setQuantity(e.target.value)} /></label>
      <label>Average buy price<input type="number" step="any" min="0.00000001" required value={buyPrice} onChange={e=>setBuyPrice(e.target.value)} /></label>
      <button type="submit" disabled={busy}>Save holding</button>
    </form>}
    {error && <p role="alert">{error}</p>}
    {!holdings.length && <p>No holdings saved yet. Your existing watchlist is available separately.</p>}
    {groups.map(group=><div key={group.currency}>
      <h4>{group.currency} holdings</h4>
      <p>Investment: {money(group.investment,group.currency)} · Quote value: {money(group.value,group.currency)} · Unrealized P/L: {money(group.pnl,group.currency)} · Return: {group.returnPercent==null?'Unavailable':`${group.returnPercent.toFixed(2)}%`}</p>
      {group.missing>0 && <p>{group.missing} holdings have no matching-currency quote. Complete totals are unavailable.</p>}
      <div className="comparison-table-wrap"><table className="comparison-table"><thead><tr><th>Company</th><th>Quantity</th><th>Buy price</th><th>Quote price</th><th>Unrealized P/L</th><th>Quote status</th><th>Action</th></tr></thead>
        <tbody>{group.rows.map(row=><tr key={row.symbol}><th>{row.name}<small>{row.symbol}</small></th><td>{row.quantity}</td><td>{money(row.buyPrice,row.currency)}</td><td>{money(row.price,row.currency)}</td><td>{money(row.pnl,row.currency)}</td><td>{row.quote?.mode || 'Unavailable'}<small>{row.quote?.asOf?new Date(row.quote.asOf).toLocaleString():'No timestamp'}</small></td><td><button type="button" disabled={busy} onClick={()=>save(holdings.filter(h=>h.symbol!==row.symbol))} aria-label={`Remove holding ${row.symbol}`}>Remove</button></td></tr>)}</tbody>
      </table></div>
      <PortfolioAnalytics group={group} />
    </div>)}
    <p>Returns exclude fees, taxes and dividends. Keep quantities and average prices updated after sales or stock splits. Currency totals are separate; quote timestamps show how recent each valuation is.</p>
  </section>;
}

function PortfolioAnalytics({group}) {
  const [target,setTarget]=useState('all');
  const [shock,setShock]=useState('-10');
  const selected=target==='all'||group.rows.some(r=>r.symbol===target)?target:'all';
  let scenario=null,scenarioError='';
  try {if(shock.trim())scenario=portfolioScenario(group,selected,shock);}catch(e){scenarioError=e.message;}
  const risk=portfolioRisk(group);
  const ranked=group.rows.filter(r=>r.pnl!=null).sort((a,b)=>b.pnl/b.cost-a.pnl/a.cost);
  const sectors={};
  if(group.value!=null)for(const row of group.rows){const sector=row.quote?.sector || 'Unknown';sectors[sector]=(sectors[sector]||0)+row.value;}
  return <div className="portfolio-analytics">
    {ranked.length>0 && <p>Highest holding return: {ranked[0].symbol} ({(ranked[0].pnl/ranked[0].cost*100).toFixed(2)}%) · Lowest: {ranked.at(-1).symbol} ({(ranked.at(-1).pnl/ranked.at(-1).cost*100).toFixed(2)}%). Based on available quotes and entered buy prices.</p>}
    <h4>Sector allocation by quote value</h4>
    {Object.entries(sectors).map(([sector,value])=><p key={sector}>{sector}: {(value/group.value*100).toFixed(1)}%{sector!=='Unknown'&&value/group.value>0.5?' · More than half of this currency group is in one sector.':''}</p>)}
    <p>Refresh portfolio quotes to load available sector information. Unknown sectors remain visible.</p>
    <h4>What-if price scenario</h4>
    <div className="portfolio-form">
      <label>Scenario holding<select value={selected} onChange={e=>setTarget(e.target.value)}><option value="all">All {group.currency} holdings</option>{group.rows.map(r=><option key={r.symbol} value={r.symbol}>{r.symbol}</option>)}</select></label>
      <label>Price change (%)<input type="number" min="-100" max="1000" step="any" value={shock} onChange={e=>setShock(e.target.value)} /></label>
    </div>
    {scenarioError && <p role="alert">{scenarioError}</p>}
    {scenario ? <p aria-live="polite">Scenario value: {money(scenario.value,group.currency)} · Change: {money(scenario.impact,group.currency)} ({scenario.impactPercent.toFixed(2)}%). Other holdings and exchange rates remain unchanged.</p> : <p>A complete set of quotes and a valid price change are required.</p>}
    <h4>Historical portfolio risk and correlation</h4>
    {risk.status==='available' ? <>
      <p>{risk.observations} common return observations · {risk.from} to {risk.through}</p>
      <p>Annualized volatility: {risk.volatilityPercent.toFixed(2)}% · Simulated maximum drawdown: {risk.maxDrawdownPercent.toFixed(2)}% · Historical 95% loss quantile per observed interval: {risk.historicalVar95Percent.toFixed(2)}%</p>
      <div className="comparison-table-wrap"><table className="comparison-table" aria-label={`${group.currency} return correlation`}><thead><tr><th>Company</th>{risk.symbols.map(s=><th key={s}>{s}</th>)}</tr></thead><tbody>{risk.symbols.map((s,i)=><tr key={s}><th>{s}</th>{risk.correlation[i].map((value,j)=><td key={risk.symbols[j]}>{value==null?'Unavailable':value.toFixed(2)}</td>)}</tr>)}</tbody></table></div>
      <p>Correlation near +1 means prices moved together; near −1 means they moved in opposite directions during this sample.</p>
    </> : <p>Risk metrics need quotes for every holding and at least 21 common historical price dates. Refresh portfolio quotes to load available history.</p>}
    <p>Historical simulation uses today's value weights rebalanced at each common observation, with 252 intervals per year. It is not your actual account history. Missing trading dates, unadjusted prices and a short sample can distort results. No fees, dividends or future-loss guarantee are included.</p>
  </div>;
}
