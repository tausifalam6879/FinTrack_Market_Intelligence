import { useEffect, useRef, useState } from 'react';
import {marketApi} from '../services/marketApi';

export default function BacktestPanel({symbol}) {
  const [result,setResult]=useState(null),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const sequence=useRef(0);
  useEffect(()=>{sequence.current++;setResult(null);setError('');setBusy(false);return ()=>{sequence.current++;};},[symbol]);
  const run=async()=>{
    const id=++sequence.current;setBusy(true);setError('');
    try{const data=await marketApi.backtest(symbol);if(id===sequence.current)setResult(data);}
    catch{if(id===sequence.current)setError('Backtest unavailable. Sufficient dated open prices and the updated API are required.');}
    finally{if(id===sequence.current)setBusy(false);}
  };
  return <section className="portfolio-panel" aria-label="Historical backtest">
    <p className="eyebrow">HISTORICAL RESEARCH SIMULATION</p><h3>Backtest a fixed ML strategy</h3>
    <p>Train only on earlier observations, then simulate long-or-cash decisions. This is a separate fixed-model experiment, not a performance claim for the currently deployed model.</p>
    <button disabled={busy} onClick={run}>{busy?'Running historical simulation…':'Run backtest'}</button>
    {error&&<p role="alert">{error}</p>}
    {result&&<>
      <p>{result.symbol} · {result.model} · {result.observations} evaluated intervals · Signal dates {result.from}–{result.through}</p>
      <div className="metric-grid">
        {[['Strategy return',result.strategyReturnPercent,'%'],['Buy-and-hold return',result.benchmarkReturnPercent,'%'],['Maximum drawdown',result.maximumDrawdownPercent,'%'],['Sharpe (zero cash rate)',result.sharpeZeroRiskFree,''],['Direction accuracy',result.accuracyPercent,'%'],['Market exposure',result.exposurePercent,'%']].map(([label,value,unit])=><article className="metric-card" key={label}><small>{label}</small><strong>{value==null?'Unavailable':`${value}${unit}`}</strong></article>)}
      </div>
      <details><summary>Inspect training windows and assumptions</summary><p>{result.method}</p><p>Source: {result.dataSource}</p><ul>{result.audit?.map(row=><li key={row.firstSignal}>{row.trainingRows} training rows through {row.trainingThrough}; first test signal {row.firstSignal}.</li>)}</ul></details>
      <p>{result.limitations}</p>
    </>}
  </section>;
}
