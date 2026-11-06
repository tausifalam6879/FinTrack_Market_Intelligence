const STORAGE_KEY = 'fintrack.research-sync.v1';
const validSymbol = value => /^[A-Z0-9.^=&-]{1,20}$/.test(value);

// Read-only refresh queue. One job runs at a time; retries remain bounded and
// persist across page reloads. Timers and network state are injected for tests.
export function createResearchSync({load, storage, online = () => true, now = () => Date.now(),
  schedule = setTimeout, cancel = clearTimeout, lock = fn => fn(), onSuccess = () => {}}) {
  let saved;
  try { saved = JSON.parse(storage?.getItem(STORAGE_KEY) || '{}'); } catch { saved = {}; }
  let jobs = (Array.isArray(saved.jobs) ? saved.jobs : []).filter(j => validSymbol(j.symbol) &&
    ['queued','running','retry','done','failed'].includes(j.status)).slice(-50)
    .map(j => {
      const attempts=Math.max(0,Math.min(3,Number(j.attempts)||0));
      const status=attempts>=3&&['queued','running','retry'].includes(j.status) ? 'failed' : j.status==='running' ? 'queued' : j.status;
      return {symbol:j.symbol,status,attempts,nextAt:Number(j.nextAt)||0,updatedAt:Number(j.updatedAt)||0,error:String(j.error||'').slice(0,250)};
    });
  let paused = Boolean(saved.paused), busy = false, timer = null, disposed = false;
  const listeners = new Set();
  const snapshot = () => ({jobs:jobs.map(j=>({...j})), paused, busy, online:online()});
  const publish = () => {
    try { storage?.setItem(STORAGE_KEY,JSON.stringify({jobs,paused})); } catch { /* Session-only queue still works. */ }
    for (const listener of listeners) listener(snapshot());
  };
  const later = delay => {
    if (timer) cancel(timer);
    if (!disposed) timer = schedule(() => {timer=null;void pump();},delay);
  };
  async function pump() {
    if (disposed || busy || paused || !online()) return;
    const job = jobs.find(j => ['queued','retry'].includes(j.status) && j.nextAt <= now());
    if (!job) {
      const waiting = jobs.filter(j => ['queued','retry'].includes(j.status));
      if (waiting.length) later(Math.max(100,Math.min(...waiting.map(j=>j.nextAt))-now()));
      return;
    }
    busy=true;
    let acquired = false;
    try {
      await lock(async () => {
        acquired=true;
        if (!online() || paused) return;
        job.status='running';job.attempts+=1;publish();
        try {
          const result=await load(job.symbol);
          if (result.error || result.mode !== 'live') {
            const error=new Error(result.error || 'Only stored data is available; fresh evidence has not arrived.');
            error.retryAfterMs=result.retryAfterMs;throw error;
          }
          job.status='done';job.error='';job.updatedAt=now();
          try { onSuccess(job.symbol,result); } catch { /* Refresh succeeded independently of UI callbacks. */ }
        } catch (error) {
          job.error=String(error.message || 'Refresh unavailable').slice(0,250);
          job.status=job.attempts < 3 ? 'retry' : 'failed';
          job.nextAt=now()+Math.max(Number(error.retryAfterMs)||0,30000*2**(job.attempts-1));
        }
      });
    } finally {
      busy=false;publish();later(acquired ? 1500 : 5000);
    }
  }
  const api = {
    snapshot,
    subscribe(listener) {listeners.add(listener);return()=>listeners.delete(listener);},
    enqueue(symbols) {
      for(const raw of symbols) {
        const symbol=String(raw||'').trim().toUpperCase();if(!validSymbol(symbol))continue;
        const existing=jobs.find(j=>j.symbol===symbol);
        if(existing && ['queued','running','retry'].includes(existing.status))continue;
        if(existing) jobs=jobs.filter(j=>j!==existing);
        if(jobs.length>=50) {
          const complete=jobs.findIndex(j=>['done','failed'].includes(j.status));
          if(complete<0)break;jobs.splice(complete,1);
        }
        jobs.push({symbol,status:'queued',attempts:0,nextAt:0,updatedAt:0,error:''});
      }
      publish();later(0);
    },
    pause() {paused=true;publish();},
    resume() {paused=false;publish();later(0);},
    networkChanged() {publish();if(online())later(0);},
    dispose() {disposed=true;if(timer)cancel(timer);listeners.clear();},
  };
  later(0);
  return api;
}

let shared;
export function browserResearchSync(load) {
  if (!shared) {
    let storage;try{storage=window.localStorage;}catch{/* Optional browser storage. */}
    shared=createResearchSync({load,storage,online:()=>navigator.onLine !== false,
      lock:fn=>navigator.locks ? navigator.locks.request('fintrack-research-sync',{ifAvailable:true},lease=>lease ? fn() : undefined) : fn(),
      onSuccess:(symbol,result)=>window.dispatchEvent(new CustomEvent('fintrack:research-updated',{detail:{symbol,result}}))});
    window.addEventListener('online',()=>shared.networkChanged());
    window.addEventListener('offline',()=>shared.networkChanged());
  }
  return shared;
}
