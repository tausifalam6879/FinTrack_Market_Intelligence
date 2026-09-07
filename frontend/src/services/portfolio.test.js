import test from 'node:test';
import assert from 'node:assert/strict';
import {validateHolding,portfolioSummary} from './portfolio.js';
const h=(symbol='TCS.NS',currency='INR')=>({symbol,currency,quantity:10,buyPrice:3200});
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
