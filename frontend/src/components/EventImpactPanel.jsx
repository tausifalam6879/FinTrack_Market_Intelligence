import {useEffect,useRef,useState} from 'react';
import {marketApi} from '../services/marketApi';
export default function EventImpactPanel({symbol}) {
  const [date,setDate]=useState(''),[result,setResult]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const sequence=useRef(0);
  useEffect(()=>{sequence.current++;setResult(null);setBusy(false);setError('');return()=>{sequence.current++;};},[symbol]);
  const run=async e=>{e.preventDefault();const id=++sequence.current;setBusy(true);setError('');setResult(null);
    try{const data=await marketApi.eventImpact(symbol,date);if(id===sequence.current)setResult(data);}
    catch{if(id===sequence.current)setError('Event window unavailable. Select a date within available history, with a prior trading session.');}
    finally{if(id===sequence.current)setBusy(false);}
  };
  return <section className="portfolio-panel" aria-label="Event impact analysis"><h3>Explore a dated event</h3>
    <p>Choose a date from a verified announcement to inspect subsequent price movements. FinTrack does not verify the event or infer that it caused the movement.</p>
    <form className="portfolio-form" onSubmit={run}><label>Event date<input required type="date" value={date} max={new Date().toISOString().slice(0,10)} onChange={e=>setDate(e.target.value)} /></label><button disabled={busy}>{busy?'Loading event window…':'Analyze event window'}</button></form>
    {error&&<p role="alert">{error}</p>}
    {result&&<><p>Selected date: {result.eventDate} · Baseline session: {result.baselineDate} · Baseline close: {result.baselinePrice} · Benchmark: {result.benchmarkSymbol||'Unavailable'}</p>
      <div className="comparison-table-wrap"><table className="comparison-table"><thead><tr><th>Sessions</th><th>Date</th><th>Close</th><th>Return</th><th>Benchmark return</th><th>Excess return (points)</th></tr></thead><tbody>{result.windows.map(w=><tr key={w.sessions}><th>{w.sessions}</th><td>{w.date||'Unavailable'}</td><td>{w.price??'Unavailable'}</td><td>{w.returnPercent==null?'Unavailable':`${w.returnPercent}%`}</td><td>{w.benchmarkReturnPercent==null?'Unavailable':`${w.benchmarkReturnPercent}%`}</td><td>{w.excessReturnPoints??'Unavailable'}</td></tr>)}</tbody></table></div>
      <p>{result.method}</p><p>{result.limitations}</p></>}
  </section>;
}
