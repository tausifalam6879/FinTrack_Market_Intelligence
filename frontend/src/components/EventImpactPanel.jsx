import {useEffect,useRef,useState} from 'react';
import {marketApi} from '../services/marketApi';
import {eventDates} from '../services/eventDates';
export default function EventImpactPanel({symbol,catalysts}) {
  const [date,setDate]=useState(''),[result,setResult]=useState(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const sequence=useRef(0);
  const today=new Date().toISOString().slice(0,10);
  const events=eventDates(catalysts,today);
  const pastEvents=events.filter(event=>!event.future);
  const upcomingEvents=events.filter(event=>event.future);
  const changeDate=value=>{sequence.current++;setDate(value);setResult(null);setBusy(false);setError('');};
  useEffect(()=>{sequence.current++;setDate('');setResult(null);setBusy(false);setError('');return()=>{sequence.current++;};},[symbol]);
  const run=async e=>{e.preventDefault();const id=++sequence.current;setBusy(true);setError('');setResult(null);
    try{const data=await marketApi.eventImpact(symbol,date);if(id===sequence.current)setResult(data);}
    catch{if(id===sequence.current)setError('Event window unavailable. Select a date within available history, with a prior trading session.');}
    finally{if(id===sequence.current)setBusy(false);}
  };
  return <section className="portfolio-panel" aria-label="Event impact analysis"><h3>Explore a dated event</h3>
    <p>Choose a date from a verified announcement to inspect subsequent price movements. FinTrack does not verify the event or infer that it caused the movement.</p>
    {upcomingEvents.length>0 && <div className="event-upcoming">
      <h4>Upcoming events</h4>
      <p>These dates are in the future. Price movements can only be analyzed after the event.</p>
      <ul>{upcomingEvents.map(event=><li key={event.key}><time dateTime={event.date}>{event.date}</time><span>{event.label||event.type||'Company event'}</span><small>Upcoming · no results yet</small></li>)}</ul>
    </div>}
    <form className="portfolio-form event-date-form" onSubmit={run}>
      {pastEvents.length>0 ? <label>Past provider event dates<select aria-label="Past provider event dates" value={pastEvents.some(event=>event.date===date)?date:''} onChange={e=>changeDate(e.target.value)}><option value="">Select a past event or enter a date</option>{pastEvents.map(event=><option key={event.key} value={event.date}>{event.date} — {event.label||event.type||'Company event'}</option>)}</select></label>
        : <p className="event-empty">No past event dates supplied for this company. Enter a confirmed past announcement date below.</p>}
      <label>Announcement date<input required type="date" value={date} max={today} onChange={e=>changeDate(e.target.value)} /></label>
      <button disabled={busy||!date||date>today}>{busy?'Loading event window…':'Analyze event window'}</button>
    </form>
    <p className="event-source">Source: {catalysts?.source||'Company data provider'}. Dates can change; confirm the announcement timing. For an after-market announcement, use the next trading session.</p>
    {error&&<p role="alert">{error}</p>}
    {result&&<><p>Selected date: {result.eventDate} · Baseline session: {result.baselineDate} · Baseline close: {result.baselinePrice} · Benchmark: {result.benchmarkSymbol||'Unavailable'}</p>
      <div className="comparison-table-wrap"><table className="comparison-table"><thead><tr><th>Sessions</th><th>Date</th><th>Close</th><th>Return</th><th>Benchmark return</th><th>Excess return (points)</th></tr></thead><tbody>{result.windows.map(w=><tr key={w.sessions}><th>{w.sessions}</th><td>{w.date||'Unavailable'}</td><td>{w.price??'Unavailable'}</td><td>{w.returnPercent==null?'Unavailable':`${w.returnPercent}%`}</td><td>{w.benchmarkReturnPercent==null?'Unavailable':`${w.benchmarkReturnPercent}%`}</td><td>{w.excessReturnPoints??'Unavailable'}</td></tr>)}</tbody></table></div>
      <p>{result.method}</p><p>{result.limitations}</p></>}
  </section>;
}
