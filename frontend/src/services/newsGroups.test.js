import test from 'node:test';
import assert from 'node:assert/strict';
import {groupHeadlines} from './newsGroups.js';
const item=title=>({title,relatedSymbol:'TCS.NS',publishedAt:'2026-09-01T12:00:00Z'});
test('groups repeated headlines while retaining publishers',()=>{
  const groups=groupHeadlines([{...item('Company announces strong quarterly revenue growth'),publisher:'A'},{...item('Company announces strong quarterly revenue growth!'),publisher:'B'}]);
  assert.equal(groups.length,1);assert.equal(groups[0].articles.length,2);
});
test('preserves different numbers, negations, symbols and dates',()=>{
  for(const other of [item('Company announces revenue growth of 20 percent'),item('Company announces no revenue growth of 10 percent'),{...item('Company announces revenue growth of 10 percent'),relatedSymbol:'AAPL'},{...item('Company announces revenue growth of 10 percent'),publishedAt:'2026-09-02'}])
    assert.equal(groupHeadlines([item('Company announces revenue growth of 10 percent'),other]).length,2);
});
