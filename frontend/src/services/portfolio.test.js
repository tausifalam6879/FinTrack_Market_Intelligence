import test from 'node:test';
import assert from 'node:assert/strict';
import {validateHolding,portfolioSummary,portfolioScenario,portfolioRisk,portfolioQuote} from './portfolio.js';
const h=(symbol='TCS.NS',currency='INR')=>({symbol,currency,quantity:10,buyPrice:3200});
test('uses the API last close with its actual session date',()=>{
  const quote=portfolioQuote({mode:'cache',data:{lastClose:3400,modelDataDate:'2026-09-04',dataAsOf:'2026-09-07',expectedRange:{currency:'INR'}}});
  assert.equal(quote.price,3400);assert.equal(quote.asOf,'2026-09-04');assert.equal(quote.mode,'cache');
});
test('computes unrealized profit and return',()=>{
  const [g]=portfolioSummary([h()],{'TCS.NS':{price:3400,currency:'INR'}});
  assert.equal(g.investment,32000);assert.equal(g.value,34000);assert.equal(g.pnl,2000);assert.equal(g.returnPercent,6.25);
});
test('never combines different currencies',()=>{
  const groups=portfolioSummary([h(),h('AAPL','USD')],{});
  assert.equal(groups.length,2);assert.ok(groups.every(g=>g.value===null));
});
test('missing or mismatched quotes do not become zero-value holdings',()=>{
  for(const quote of [{price:null,currency:'INR'},{price:4000,currency:'USD'},{price:NaN,currency:'INR'}]) {
    const [g]=portfolioSummary([h()],{'TCS.NS':quote});
    assert.equal(g.pnl,null);assert.equal(g.returnPercent,null);assert.equal(g.missing,1);
  }
});
test('rejects invalid holdings and indices',()=>{
  for(const invalid of [{quantity:-1},{quantity:''},{buyPrice:Infinity},{symbol:'^NSEI'},{currency:''}])
    assert.throws(()=>validateHolding({...h(),...invalid}));
});
test('supports fractional quantities and negative returns',()=>{
  const [g]=portfolioSummary([{...h(),quantity:0.5}],{'TCS.NS':{price:1600,currency:'INR'}});
  assert.equal(g.pnl,-800);assert.equal(g.returnPercent,-50);
});

test('scenario changes only selected holdings and validates shocks',()=>{
  const [g]=portfolioSummary([h(),h('INFY.NS')],{'TCS.NS':{price:3400,currency:'INR'},'INFY.NS':{price:1000,currency:'INR'}});
  const result=portfolioScenario(g,'TCS.NS',-10);
  assert.equal(result.value,40600);assert.equal(result.impact,-3400);
  assert.equal(portfolioScenario(g,'all',-100).value,0);
  assert.throws(()=>portfolioScenario(g,'all',-101));
  assert.equal(portfolioScenario({...g,value:null},'all',-10),null);
});

test('risk aligns dates and returns a correct correlation matrix',()=>{
  const history=Array.from({length:25},(_,i)=>({date:`2026-08-${String(i+1).padStart(2,'0')}`,close:100+i+(i%2)}));
  const [g]=portfolioSummary([h(),h('INFY.NS')],{'TCS.NS':{price:3400,currency:'INR',history},'INFY.NS':{price:1000,currency:'INR',history:history.slice(2)}});
  const risk=portfolioRisk(g);
  assert.equal(risk.status,'available');assert.equal(risk.observations,22);
  assert.ok(Math.abs(risk.correlation[0][1]-1)<1e-10);
  assert.equal(risk.maxDrawdownPercent,0);
  assert.equal(risk.historicalVar95Percent,0);
  assert.ok(risk.volatilityPercent>0);
});

test('risk refuses short samples and undefined constant-price correlations',()=>{
  const history=Array.from({length:21},(_,i)=>({date:`2026-08-${String(i+1).padStart(2,'0')}`,close:100}));
  let [g]=portfolioSummary([h()],{'TCS.NS':{price:100,currency:'INR',history}});
  assert.equal(portfolioRisk(g).correlation[0][0],null);
  [g]=portfolioSummary([h()],{'TCS.NS':{price:100,currency:'INR',history:history.slice(1)}});
  assert.equal(portfolioRisk(g).status,'insufficient_history');
});
