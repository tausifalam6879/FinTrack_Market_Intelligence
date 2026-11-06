import {test} from 'node:test';
import assert from 'node:assert/strict';
import {createResearchSync} from '../src/services/researchSync.js';
import {researchChanges} from '../src/services/researchChanges.js';

function harness(load,values={}) {
  let time=1000,connected=true,id=0;
  const tasks=new Map(),store=new Map(Object.entries(values));
  const queue=createResearchSync({load,storage:{getItem:k=>store.get(k),setItem:(k,v)=>store.set(k,v)},
    now:()=>time,online:()=>connected,schedule:(fn,delay)=>{tasks.set(++id,{fn,at:time+delay});return id;},cancel:key=>tasks.delete(key)});
  return {queue,store,offline:()=>{connected=false;queue.networkChanged();},online:()=>{connected=true;queue.networkChanged();},
    async tick(ms=0){time+=ms;for(let n=0;n<20;n++){const due=[...tasks].filter(([,t])=>t.at<=time);if(!due.length)break;for(const [k,t]of due){tasks.delete(k);t.fn();}await new Promise(resolve=>setImmediate(resolve));}}};
}

test('sync deduplicates active symbols and never runs two jobs together',async()=>{
  const calls=[];let release;
  const h=harness(symbol=>{calls.push(symbol);return symbol==='AAPL'?new Promise(resolve=>{release=()=>resolve({mode:'live'});}):Promise.resolve({mode:'live'});});
  h.queue.enqueue(['AAPL','AAPL','MSFT']);await h.tick();h.queue.enqueue(['AAPL']);
  assert.deepEqual(calls,['AAPL']);assert.equal(h.queue.snapshot().jobs.length,2);
  release();await h.tick();await h.tick(1500);
  assert.deepEqual(calls,['AAPL','MSFT']);assert.ok(h.queue.snapshot().jobs.every(j=>j.status==='done'));h.queue.dispose();
});

test('offline queue resumes after reconnect and preserves an explicit pause',async()=>{
  let count=0;const h=harness(async()=>{count++;return{mode:'live'};});h.offline();h.queue.enqueue(['AAPL']);await h.tick();assert.equal(count,0);
  h.queue.pause();h.online();await h.tick();assert.equal(count,0);
  h.queue.resume();await h.tick();assert.equal(count,1);h.queue.dispose();
});

test('cached fallback is a retry, respects retry-after and stops after three failures',async()=>{
  let count=0;const h=harness(async()=>{count++;return{mode:'cache',error:'Rate limited',retryAfterMs:90000};});
  h.queue.enqueue(['AAPL']);await h.tick();assert.equal(h.queue.snapshot().jobs[0].status,'retry');
  await h.tick(89999);assert.equal(count,1);await h.tick(100);assert.equal(count,2);
  await h.tick(90000);assert.equal(count,3);assert.equal(h.queue.snapshot().jobs[0].status,'failed');
  await h.tick(1000000);assert.equal(count,3);h.queue.dispose();
});

test('pending work and pause survive reload while invalid persisted symbols are ignored',()=>{
  const encoded=JSON.stringify({paused:true,jobs:[{symbol:'AAPL',status:'running',attempts:1},{symbol:'https://bad',status:'queued'}]});
  const h=harness(async()=>({mode:'live'}),{'fintrack.research-sync.v1':encoded});
  assert.equal(h.queue.snapshot().paused,true);assert.equal(h.queue.snapshot().jobs.length,1);assert.equal(h.queue.snapshot().jobs[0].status,'queued');h.queue.dispose();
});

test('outlook comparison reports model changes without inventing a probability or causal attribution',()=>{
  const before={symbol:'AAPL',probabilityUp:55,outlook:'NEUTRAL',model:{modelRunId:'one'},technicalIndicators:{rsi14:40}};
  const after={...before,probabilityUp:60,outlook:'BULLISH',model:{modelRunId:'two'},technicalIndicators:{rsi14:52}};
  const change=researchChanges(before,after);assert.equal(change.delta,5);assert.equal(change.versionChanged,true);assert.equal(change.inputs[0].after,52);
  assert.equal(researchChanges(before,{...after,symbol:'MSFT'}),null);
  assert.equal(researchChanges(before,{...after,probabilityUp:null}).delta,null);
});
