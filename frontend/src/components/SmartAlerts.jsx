import {useEffect,useState} from 'react';
import {marketApi} from '../services/marketApi';
import {ALERT_EVENT,CONDITIONS,readAlerts,saveAlerts,alertMatches} from '../services/smartAlerts';

export function useSmartAlertMonitor(){
  useEffect(()=>{
    let stopped=false,running=false,queued=false;
    const check=async()=>{
      if(stopped)return;
      if(running){queued=true;return;}
      running=true;
      try {
        const rules=readAlerts();
        for(const symbol of [...new Set(rules.map(r=>r.symbol))]){
          if(stopped)break;
          let result=null;
          try{result=await marketApi.analysis(symbol);}catch{/* Record unavailable status below. */}
          if(stopped)break;
          const current=readAlerts();
          const next=current.map(rule=>{
            if(rule.symbol!==symbol||!rules.some(r=>r.id===rule.id))return rule;
            const match=result?.mode==='live'?alertMatches(rule,result.data):null;
            const now=new Date().toISOString();
            if(match===true&&rule.active!==true&&typeof Notification!=='undefined'&&Notification.permission==='granted'){
              try{new Notification('FinTrack research alert',{body:`${symbol}: ${CONDITIONS[rule.condition]} ${rule.threshold}. Verify the quote date in FinTrack.`,tag:rule.id});}catch{/* In-app status remains available. */}
            }
            return {...rule,lastChecked:now,status:match==null?'Quote unavailable or cached':match?'Condition met':'Condition not met',
              active:match==null?rule.active:match,
              quoteDate:result?.data?.modelDataDate||result?.data?.dataAsOf||rule.quoteDate,
              triggeredAt:match===true&&rule.active!==true?now:rule.triggeredAt};
          });
          try{saveAlerts(next,false);}catch{/* Browser can deny persistent storage. */}
        }
      }finally{running=false;if(queued&&!stopped){queued=false;void check();}}
    };
    void check();const timer=window.setInterval(check,15*60*1000);
    window.addEventListener(ALERT_EVENT,check);
    return()=>{stopped=true;clearInterval(timer);window.removeEventListener(ALERT_EVENT,check);};
  },[]);
}

export default function SmartAlerts({symbol,currency}){
  const [rules,setRules]=useState(readAlerts),[condition,setCondition]=useState('price_below'),[threshold,setThreshold]=useState(''),[error,setError]=useState('');
  useEffect(()=>{const sync=()=>setRules(readAlerts());window.addEventListener(ALERT_EVENT,sync);window.addEventListener('fintrack-alert-status',sync);return()=>{window.removeEventListener(ALERT_EVENT,sync);window.removeEventListener('fintrack-alert-status',sync);};},[]);
  const add=e=>{e.preventDefault();const n=Number(threshold);
    if(!threshold.trim()||!Number.isFinite(n)||n<0||(condition!=='price_below'&&n>100)){setError('Enter a nonnegative threshold; RSI and probability must be at most 100.');return;}
    const current=readAlerts();if(current.length>=12){setError('Up to 12 rules are supported.');return;}
    if(current.some(r=>r.symbol===symbol&&r.condition===condition&&r.threshold===n)){setError('This rule already exists.');return;}
    try{saveAlerts([...current,{id:crypto.randomUUID(),symbol,condition,threshold:n,status:'Waiting for check'}]);setError('');}catch{setError('Browser storage is unavailable; the rule could not be saved.');}
  };
  const notify=async()=>{if(typeof Notification==='undefined'){setError('Notifications are not supported in this browser.');return;}try{const permission=await Notification.requestPermission();setError(permission==='granted'?'Notifications enabled.':'Notifications are not enabled. Rule status is still shown here.');}catch{setError('Notifications are unavailable.');}};
  return <section className="portfolio-panel" aria-label="Smart research alerts"><h3>Smart research alerts</h3>
    <p>Checks saved rules every 15 minutes while FinTrack is open. Browser background throttling may delay checks. Prices use the available quote or last close, in {currency||'the quoted currency'}.</p>
    <form className="portfolio-form" onSubmit={add}><strong>{symbol}</strong><label>Alert condition<select value={condition} onChange={e=>setCondition(e.target.value)}>{Object.entries(CONDITIONS).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><label>Alert threshold<input type="number" step="any" min="0" required value={threshold} onChange={e=>setThreshold(e.target.value)} /></label><button>Add alert rule</button></form>
    <button onClick={notify}>Enable browser notifications</button>
    {error&&<p role="status">{error}</p>}
    {rules.map(rule=><article key={rule.id}><p>{rule.symbol}: {CONDITIONS[rule.condition]} {rule.threshold} · {rule.status}. Quote date: {rule.quoteDate||'Not checked'}. Last checked: {rule.lastChecked||'Pending'}.</p><button onClick={()=>{try{saveAlerts(readAlerts().filter(r=>r.id!==rule.id));}catch{setError('Could not remove the saved rule.');}}} aria-label={`Remove alert ${rule.symbol} ${rule.condition} ${rule.threshold}`}>Remove rule</button></article>)}
    <p>Newly met conditions trigger once, then re-arm after the condition clears. No email or closed-browser monitoring is enabled.</p>
  </section>;
}
