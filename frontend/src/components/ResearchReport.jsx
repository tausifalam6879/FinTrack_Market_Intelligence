import {useEffect,useRef,useState} from 'react';
import {marketApi} from '../services/marketApi';

const value=(v,suffix='')=>v==null?'Unavailable':`${typeof v==='number'?v.toLocaleString('en-IN',{maximumFractionDigits:2}):v}${suffix}`;
const safeUrl=url=>/^https?:\/\//i.test(String(url||''))?url:null;

export default function ResearchReport({analysis,company,peers,documents,mode}) {
  const [summary,setSummary]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const request=useRef(0);
  const reportRef=useRef(null),printCopy=useRef(null);
  useEffect(()=>{request.current++;setSummary(null);setBusy(false);setError('');return ()=>{request.current++;document.body.classList.remove('print-fintrack-report');printCopy.current?.remove();};},[analysis.symbol]);
  const generate=async()=>{
    const id=++request.current;setBusy(true);setError('');
    try {
      const response=await marketApi.agent({symbol:analysis.symbol,preferLocal:!navigator.onLine,
        message:'Give a concise research summary of this company. Explain financial performance, profitability, debt and liquidity, model uncertainty and main risks using available evidence. Do not invent missing figures or give buy or sell advice.',recentMessages:[]});
      if(id===request.current)setSummary(response);
    }catch{if(id===request.current)setError('AI explanation is unavailable. The evidence report below can still be printed.');}
    finally{if(id===request.current)setBusy(false);}
  };
  const print=()=>{
    printCopy.current?.remove();
    const copy=reportRef.current.cloneNode(true);
    copy.className='fintrack-report-print-copy';
    copy.querySelector('.report-controls')?.remove();
    document.body.appendChild(copy);printCopy.current=copy;
    document.body.classList.add('print-fintrack-report');
    const cleanup=()=>{document.body.classList.remove('print-fintrack-report');copy.remove();};
    window.addEventListener('afterprint',cleanup,{once:true});
    try{window.print();}catch{cleanup();}
  };
  const financials=company?.financials||{};
  const parts=[
    ['Company overview',company?.summary || 'Company profile unavailable.'],
    ['Market position',`Last close: ${value(analysis.lastClose ?? analysis.price)} ${analysis.expectedRange?.currency||''}. Sector: ${company?.sector||'Unavailable'}.`],
    ['Price trend',`One-month return: ${value(company?.performance?.oneMonth,'%')}. One-year return: ${value(company?.performance?.oneYear,'%')}.`],
    ['Technical indicators',`RSI (14): ${value(analysis.technicalIndicators?.rsi14)}. SMA20: ${value(analysis.technicalIndicators?.sma20)}. SMA50: ${value(analysis.technicalIndicators?.sma50)}.`],
    ['Financial performance',`Revenue growth: ${value(financials.growth?.revenueGrowthPercent,'%')}. Earnings growth: ${value(financials.growth?.earningsGrowthPercent,'%')}.`],
    ['Profitability',`Operating margin: ${value(financials.profitability?.operatingMarginPercent,'%')}. Return on equity: ${value(financials.profitability?.returnOnEquityPercent,'%')}.`],
    ['Debt and liquidity',`Current ratio: ${value(financials.balanceSheet?.currentRatio)}. Quick ratio: ${value(financials.balanceSheet?.quickRatio)}. Total debt: ${value(financials.balanceSheet?.totalDebt)} ${company?.quote?.currency||''}.`],
    ['Peer comparison',peers?.peers?.length ? peers.peers.map(p=>`${p.name||p.symbol}: P/E ${value(p.trailingPE)}, price/book ${value(p.priceToBook)}`).join('; ') : 'Peer evidence unavailable.'],
    ['News evidence',`Available article count: ${value(analysis.newsFactor?.articleCount)}. Sentiment label: ${analysis.newsFactor?.sentimentLabel||'Unavailable'}. Headlines and full article context should be reviewed separately.`],
    ['ML analysis',`Model: ${analysis.model?.type||'Unavailable'}. Next-session rise probability: ${value(analysis.probabilityUp,'%')}. Balanced accuracy: ${value(analysis.model?.balancedAccuracy,'%')}. Brier score: ${value(analysis.model?.brierScore)}. Probability is not a guarantee.`],
    ['Risk factors',`Recent daily volatility: ${value(analysis.technicalIndicators?.dailyVolatility20d,'%')}. Estimates can be wrong; stale prices, incomplete filings and changing market conditions reduce reliability.`],
    ['Key observations',summary?.answer || 'Use Generate AI explanation for an optional explanation of the available evidence. Missing values have not been filled with estimates.']
  ];
  return <section ref={reportRef} className="portfolio-panel research-report" aria-label="Structured research report">
    <h3>{analysis.name||analysis.symbol} — Research report</h3>
    <p>{analysis.symbol} · Data mode: {mode} · Model price date: {analysis.modelDataDate||analysis.dataAsOf||'Unavailable'}</p>
    <div className="report-controls"><button onClick={generate} disabled={busy}>{busy?'Generating explanation…':'Generate AI explanation'}</button> <button onClick={print}>Print / Save report PDF</button></div>
    {error&&<p role="alert">{error}</p>}
    {summary&&<p>Explanation provider: {summary.llmProvider||'Verified fallback'} · {summary.llmStatus||'Status unavailable'}. The explanation may use newer evidence than the displayed snapshot.</p>}
    {parts.map(([title,text],i)=><section key={title}><h4>{i+1}. {title}</h4><p style={{whiteSpace:'pre-wrap'}}>{text}</p></section>)}
    <section><h4>13. Sources and dates</h4><p>Company source: {company?.source||'Unavailable'} · Updated: {company?.generatedAt||company?.dataAsOf||'Unavailable'}. Quote date: {analysis.dataAsOf||'Unavailable'}.</p>
      {(documents||[]).map(d=><p key={d.id}>{d.title} · {d.reportingPeriod||'Period unavailable'} {safeUrl(d.sourceUrl)&&<a href={safeUrl(d.sourceUrl)} target="_blank" rel="noreferrer">Open source</a>}</p>)}
      {summary?.citations?.map((c,i)=><p key={i}>{c.title} · page {c.page} {safeUrl(c.sourceUrl)&&<a href={safeUrl(c.sourceUrl)} target="_blank" rel="noreferrer">Cited evidence</a>}</p>)}
    </section>
    <p>Educational research report. Provider figures can cover different reporting periods; verify original filings before comparing them.</p>
  </section>;
}
