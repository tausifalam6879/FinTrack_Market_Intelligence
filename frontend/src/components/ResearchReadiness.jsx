import {useEffect,useState} from 'react';
import {marketApi} from '../services/marketApi';
import {browserResearchSync} from '../services/researchSync';

export default function ResearchReadiness({savedSymbols=[],currentSymbol,onSelect}) {
  const [queue]=useState(()=>browserResearchSync(marketApi.refreshStored));
  const [sync,setSync]=useState(()=>queue.snapshot());
  const [inventory,setInventory]=useState(null);
  const [error,setError]=useState('');
  const savedKey=savedSymbols.join(',');
  useEffect(()=>{
    let active=true;
    const check=()=>marketApi.offlineReadiness().then(result=>{
      if(active){setInventory(result);setError(result.error ? 'Showing the previous readiness check.' : '');}
    }).catch(()=>{if(active)setError('Local readiness check is unavailable. Existing browser research remains usable.');});
    void check();
    const timer=window.setInterval(()=>{if(navigator.onLine!==false&&document.visibilityState==='visible')void check();},60000);
    const unsubscribe=queue.subscribe(setSync);
    const network=()=>{queue.networkChanged();if(navigator.onLine !== false){queue.enqueue(savedSymbols);void check();}};
    const refreshed=()=>{void check();};
    window.addEventListener('online',network);window.addEventListener('offline',network);
    window.addEventListener('fintrack:research-updated',refreshed);
    return()=>{active=false;window.clearInterval(timer);unsubscribe();window.removeEventListener('online',network);window.removeEventListener('offline',network);window.removeEventListener('fintrack:research-updated',refreshed);};
  },[queue,savedKey]);
  const rows=inventory?.data?.items || [];
  const ai=inventory?.data?.localAI;
  const background=inventory?.data?.backgroundResearch;
  const ready=rows.filter(row=>row.priceHistoryReady).length;
  const pending=sync.jobs.filter(job=>['queued','running','retry'].includes(job.status));
  return <details className="research-readiness" aria-label="Offline readiness and background sync"><summary>Offline readiness and background sync <span>{inventory ? `${ready} stored companies` : 'Checking saved data'} · {pending.length} queued</span></summary><section>
    <div className="readiness-heading"><div><h3>Offline readiness</h3><p>{inventory ? `${ready} companies have stored price history. Browser research is available separately.` : 'Checking stored company coverage…'}</p></div><span className="readiness-network">{sync.online ? 'Network available' : 'Offline — stored data stays visible'}</span></div>
    <div className="readiness-summary">
      <span>Full research saved: <strong>{rows.filter(r=>r.researchSaved).length}</strong></span>
      {background && <span>Evidence worker: <strong>{background.status.replaceAll('_',' ')}</strong></span>}
      <span>Local model files: <strong>{rows.filter(r=>r.localArtifactPresent).length}</strong></span>
      <span>Ollama: <strong>{ai?.status==='installed' ? `${ai.model} installed and reachable` : ai?.status || 'Checking…'}</strong></span>
    </div>
    {ai?.status==='installed' && <small>Model warm-up can still take time before the first answer.</small>}
    {error && <p role="status">{error}</p>}
    {inventory?.savedAt && <small>Last readiness check: {new Date(inventory.savedAt).toLocaleString('en-IN')}</small>}
    {inventory?.data?.notice && <p><small>{inventory.data.notice}</small></p>}
    <details><summary>Check stored company coverage ({rows.length})</summary>
      <div className="readiness-table"><table><thead><tr><th>Company</th><th>Last session</th><th>History</th><th>Research</th><th>Approved model</th></tr></thead><tbody>
        {rows.map(row=><tr key={row.symbol}><td><button type="button" onClick={()=>onSelect({symbol:row.symbol,name:row.name,exchange:'Stored'})}>{row.name}<small>{row.symbol}</small></button></td><td>{row.dataAsOf || 'Not stored'}</td><td>{row.storedBars} bars</td><td>{row.researchSaved ? 'Saved' : 'History only'}</td><td>{row.localArtifactPresent ? 'File on this server' : row.approvedModelRegistered ? 'Registered; file not local' : 'Not registered'}</td></tr>)}
      </tbody></table></div>
    </details>
    <div className="research-sync" aria-label="Research sync queue">
      <h4>Background sync</h4>
      <p>{sync.paused ? 'Paused by you.' : !sync.online ? 'Waiting for a connection.' : sync.busy ? 'Refreshing one company. You can keep researching.' : 'Ready.'} {pending.length} queued or retrying.</p>
      <div className="readiness-actions">
        <button type="button" onClick={()=>queue.enqueue(savedSymbols.length ? savedSymbols : [currentSymbol])}>Sync saved companies</button>
        <button type="button" disabled={!rows.length} onClick={()=>queue.enqueue(rows.filter(r=>r.priceHistoryReady).map(r=>r.symbol))}>Sync stored companies</button>
        <button type="button" onClick={()=>sync.paused ? queue.resume() : queue.pause()}>{sync.paused ? 'Resume sync' : 'Pause sync'}</button>
        {sync.jobs.some(j=>j.status==='failed')&&<button type="button" onClick={()=>queue.enqueue(sync.jobs.filter(j=>j.status==='failed').map(j=>j.symbol))}>Retry failed</button>}
      </div>
      {!!sync.jobs.length&&<ul className="sync-jobs">{sync.jobs.slice(-6).reverse().map(job=><li key={job.symbol}><strong>{job.symbol}</strong><span>{job.status}{job.attempts ? ` · attempt ${job.attempts}/3` : ''}</span>{job.error&&<small>{job.error}</small>}</li>)}</ul>}
      <small>Refreshes price and model research one company at a time, up to three attempts with backoff. Saved companies queue again when the network reconnects. Pausing stops the next job.</small>
    </div>
  </section></details>;
}

const format=value=>value==null?'Awaiting outcomes':String(value);
export function NextSessionAudit({audit}) {
  if(!audit)return <section className="next-session-audit"><h3>Next-session outcome audit</h3><p>Waiting for stored prediction evidence.</p></section>;
  return <section className="next-session-audit" aria-label="Next session outcome audit"><h3>Next-session outcome audit</h3>
    <p>{audit.evaluated} scored sessions · {audit.pending} awaiting a completed stored session · {audit.retrospectiveExcluded} late-generated snapshots excluded.</p>
    <div className="readiness-table"><table><thead><tr><th>Window</th><th>Scored</th><th>Balanced accuracy</th><th>ROC AUC</th><th>Brier</th><th>Majority baseline BA</th><th>Momentum baseline BA</th></tr></thead><tbody>
      {(audit.windows||[]).map(row=><tr key={row.window}><td>Last {row.window} outcomes</td><td>{row.evaluated}/{row.window}</td><td>{row.balancedAccuracy==null?'Needs both classes':`${row.balancedAccuracy}%`}</td><td>{format(row.rocAuc)}</td><td>{format(row.brierScore)}</td><td>{format(row.baselines?.expandingMajority?.balancedAccuracy)}</td><td>{format(row.baselines?.previousSessionMomentum?.balancedAccuracy)}</td></tr>)}
    </tbody></table></div>
    <details><summary>View dated outcomes</summary><div className="readiness-table"><table><thead><tr><th>Forecast session</th><th>UP probability</th><th>Actual session</th><th>Actual close</th><th>Result</th></tr></thead><tbody>{(audit.records||[]).map(row=><tr key={row.id}><td>{row.modelDataDate}</td><td>{row.probabilityUp}%</td><td>{row.actualSession||'Pending'}</td><td>{row.actualClose??'—'}</td><td>{row.status==='evaluated' ? row.binaryCorrect?'Correct':'Incorrect' : row.status==='retrospective'?'Historical snapshot; excluded':row.status}</td></tr>)}</tbody></table></div></details>
    <small>{audit.method} Baselines use only information before each outcome. These are observed classification metrics, not trading returns.</small>
  </section>;
}

export function ResearchChangeSummary({change}) {
  if(!change)return null;
  return <section className="research-change" aria-label="Research changes"><h3>What changed in this outlook?</h3>
    <p>{change.previousOutlook} → {change.currentOutlook}{change.delta!=null ? ` · UP probability ${change.delta>0?'+':''}${change.delta} percentage points` : ' · prediction availability changed'}</p>
    {!!change.reasons.length&&<ul>{change.reasons.map(reason=><li key={reason}>{reason}</li>)}</ul>}
    {!!change.inputs.length&&<dl>{change.inputs.map(item=><div key={item.label}><dt>{item.label}</dt><dd>{item.before} → {item.after}</dd></div>)}</dl>}
    <small>Observed input and model changes; this comparison does not establish which change caused the probability difference.{change.versionChanged?' Different model versions are not a market-only comparison.':''}</small>
  </section>;
}
