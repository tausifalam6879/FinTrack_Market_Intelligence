import test from 'node:test';
import assert from 'node:assert/strict';
import {alertMatches} from './smartAlerts.js';
test('alert rules respect thresholds and unavailable data',()=>{
  assert.equal(alertMatches({condition:'price_below',threshold:100},{lastClose:99}),true);
  assert.equal(alertMatches({condition:'price_below',threshold:100},{lastClose:100}),false);
  assert.equal(alertMatches({condition:'rsi_below',threshold:30},{technicalIndicators:{rsi14:29}}),true);
  assert.equal(alertMatches({condition:'probability_above',threshold:70},{probabilityUp:71}),true);
  assert.equal(alertMatches({condition:'probability_above',threshold:70},{}),null);
  assert.equal(alertMatches({condition:'toString',threshold:0},{probabilityUp:71}),null);
});
