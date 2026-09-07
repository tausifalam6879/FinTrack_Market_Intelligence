import { useEffect, useRef, useState } from 'react';
import { marketApi } from '../services/marketApi';
import { PORTFOLIO_KEY, portfolioSummary, validateHolding } from '../services/portfolio';

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
const quoteFrom = result => ({price:result.data.price, currency:result.data.expectedRange?.currency,
  asOf:result.data.dataAsOf, mode:result.mode});
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
    setQuotes(current=>({...seeds,...current,[analysis.symbol]:quoteFrom({data:analysis,mode})}));
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
      const batch=await Promise.allSettled(holdings.slice(i,i+3).map(async h=>[h.symbol,quoteFrom(await marketApi.analysis(h.symbol,true))]));
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
    </div>)}
    <p>Returns exclude fees, taxes and dividends. Keep quantities and average prices updated after sales or stock splits. Currency totals are separate; quote timestamps show how recent each valuation is.</p>
  </section>;
}
