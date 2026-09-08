export const ALERTS_KEY='fintrack.smart-alerts.v1';
export const ALERT_EVENT='fintrack-alert-rules-changed';
export const CONDITIONS={price_below:'Price below',rsi_below:'RSI below',probability_above:'Rise probability above'};
export function alertMatches(rule,data) {
  const raw=rule.condition==='price_below'?(data.price??data.lastClose):rule.condition==='rsi_below'?data.technicalIndicators?.rsi14:data.probabilityUp;
  if(raw==null||!Number.isFinite(Number(raw)))return null;
  if(!Object.hasOwn(CONDITIONS,rule.condition)||!Number.isFinite(Number(rule.threshold)))return null;
  return rule.condition==='probability_above'?Number(raw)>Number(rule.threshold):Number(raw)<Number(rule.threshold);
}
export function readAlerts(){try{const rules=JSON.parse(localStorage.getItem(ALERTS_KEY)||'[]');return Array.isArray(rules)?rules.filter(r=>r&&typeof r.id==='string'&&typeof r.symbol==='string'&&Object.hasOwn(CONDITIONS,r.condition)&&Number.isFinite(Number(r.threshold))).slice(0,12):[];}catch{return [];}}
export function saveAlerts(rules,changed=true){localStorage.setItem(ALERTS_KEY,JSON.stringify(rules));window.dispatchEvent(new Event(changed?ALERT_EVENT:'fintrack-alert-status'));}
