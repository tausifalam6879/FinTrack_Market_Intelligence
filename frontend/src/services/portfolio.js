export const PORTFOLIO_KEY = 'fintrack.portfolio.v1';

export const portfolioQuote = result => ({price:result.data.price ?? result.data.lastClose,
  currency:result.data.expectedRange?.currency,
  asOf:result.data.price!=null ? result.data.dataAsOf : result.data.modelDataDate || result.data.dataAsOf,
  mode:result.mode, history:result.data.history || []});

export function validateHolding(input) {
  const quantity = Number(input.quantity);
  const buyPrice = Number(input.buyPrice);
  const symbol = String(input.symbol || '').trim().toUpperCase();
  const currency = String(input.currency || '').trim().toUpperCase();
  if (!/^[A-Z0-9][A-Z0-9.&=-]{0,19}$/.test(symbol)) throw new Error('Select a company before saving a holding.');
  if (!/^[A-Z]{3}$/.test(currency)) throw new Error('A known quote currency is required.');
  if (!Number.isFinite(quantity) || quantity <= 0 || quantity > 1e9) throw new Error('Quantity must be greater than zero and at most one billion.');
  if (!Number.isFinite(buyPrice) || buyPrice <= 0 || buyPrice > 1e12) throw new Error('Average buy price must be greater than zero and at most one trillion.');
  return { symbol, currency, quantity, buyPrice, name: String(input.name || symbol).slice(0,200) };
}

export function portfolioSummary(holdings, quotes) {
  const groups = {};
  for (const holding of holdings) {
    const h = validateHolding(holding);
    const group = groups[h.currency] ||= { currency:h.currency, investment:0, value:0, missing:0, rows:[] };
    const quote = quotes[h.symbol];
    const price = Number(quote?.price);
    const available = quote?.price != null && Number.isFinite(price) && price > 0 && quote.currency === h.currency;
    const cost = h.quantity * h.buyPrice;
    const value = available ? h.quantity * price : null;
    group.investment += cost;
    if (available) group.value += value; else group.missing += 1;
    group.rows.push({...h, price:available ? price : null, cost, value, pnl:available ? value-cost : null, quote});
  }
  return Object.values(groups).map(g => ({...g, value:g.missing ? null : g.value,
    pnl:g.missing ? null : g.value-g.investment,
    returnPercent:g.missing ? null : (g.value/g.investment-1)*100}));
}

export function portfolioScenario(group, target, changePercent) {
  const shock=Number(changePercent);
  if(!Number.isFinite(shock)||shock < -100||shock > 1000) throw new Error('Enter a price change between -100% and 1000%.');
  if(group.value==null) return null;
  const affected=group.rows.filter(r=>target==='all'||r.symbol===target);
  if(!affected.length) return null;
  const impact=affected.reduce((sum,r)=>sum+r.value*shock/100,0);
  return {value:group.value+impact,impact,impactPercent:impact/group.value*100};
}

const mean=xs=>xs.reduce((a,b)=>a+b,0)/xs.length;
const covariance=(a,b)=>{
  const ma=mean(a),mb=mean(b);
  return a.reduce((sum,x,i)=>sum+(x-ma)*(b[i]-mb),0)/(a.length-1);
};

export function portfolioRisk(group) {
  if(group.value==null||!group.rows.length) return {status:'missing_quotes'};
  const series=group.rows.map(row=>new Map((row.quote?.history||[])
    .filter(p=>/^\d{4}-\d{2}-\d{2}$/.test(p.date)&&p.close!=null&&Number.isFinite(Number(p.close))&&Number(p.close)>0)
    .map(p=>[p.date,Number(p.close)])));
  const dates=[...series[0].keys()].filter(date=>series.every(s=>s.has(date))).sort();
  if(dates.length<21) return {status:'insufficient_history',observations:Math.max(0,dates.length-1)};
  const returns=series.map(s=>dates.slice(1).map((date,i)=>s.get(date)/s.get(dates[i])-1));
  const weights=group.rows.map(r=>r.value/group.value);
  const aggregate=dates.slice(1).map((_,i)=>returns.reduce((sum,r,j)=>sum+r[i]*weights[j],0));
  let wealth=1,peak=1,drawdown=0;
  for(const r of aggregate){wealth*=1+r;peak=Math.max(peak,wealth);drawdown=Math.min(drawdown,wealth/peak-1);}
  const sorted=[...aggregate].sort((a,b)=>a-b);
  const qIndex=(sorted.length-1)*0.05,lower=Math.floor(qIndex),upper=Math.ceil(qIndex);
  const quantile=sorted[lower]+(sorted[upper]-sorted[lower])*(qIndex-lower);
  return {status:'available',observations:aggregate.length,from:dates[0],through:dates.at(-1),
    volatilityPercent:Math.sqrt(Math.max(0,covariance(aggregate,aggregate))*252)*100,
    maxDrawdownPercent:drawdown*100,historicalVar95Percent:Math.max(0,-quantile)*100,
    symbols:group.rows.map(r=>r.symbol),
    correlation:returns.map(a=>returns.map(b=>{
      const denominator=Math.sqrt(covariance(a,a)*covariance(b,b));
      return denominator>1e-15?Math.max(-1,Math.min(1,covariance(a,b)/denominator)):null;
    }))};
}
