import test from 'node:test';
import assert from 'node:assert/strict';
import {eventDates} from './eventDates.js';
test('provider dates are validated, deduplicated and future dates marked', () => {
  const rows = eventDates({events: [
    {type:'earnings', date:'2026-08-01'}, {type:'earnings', date:'2026-10-01'},
    {type:'earnings', date:'2026-02-30'}, {date:'bad'},
  ], earningsHistory:[{date:'2026-08-01',status:'reported'}, {date:'2026-05-01',status:'reported'}, {date:'2026-04-01',status:'estimate'}]}, '2026-09-08');
  assert.deepEqual(rows.map(r=>r.date), ['2026-10-01','2026-08-01','2026-05-01']);
  assert.equal(rows[0].future,true);
  assert.equal(rows[1].future,false);
  assert.deepEqual(eventDates(null),[]);
});
