import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {createServer} from 'vite';

const server = await createServer({server: {middlewareMode: true}, appType: 'custom'});
try {
  const {default: Panel} = await server.ssrLoadModule('/src/components/EventImpactPanel.jsx');
  const render = catalysts => renderToStaticMarkup(React.createElement(Panel, {symbol: 'TEST', catalysts}));
  const future = {date: '2099-12-10', type: 'dividend', label: 'Dividend payment'};
  const past = {date: '2020-10-10', type: 'earnings', label: 'Earnings release'};
  const futureOnly = render({events: [future]});
  assert.match(futureOnly, /Upcoming events/);
  assert.match(futureOnly, /No past event dates supplied/);
  assert.doesNotMatch(futureOnly, /<select/);
  assert.match(futureOnly, /<button disabled=""/);
  const mixed = render({events: [future, past]});
  const dropdown = mixed.match(/<select[\s\S]*?<\/select>/)[0];
  assert.match(dropdown, /2020-10-10/);
  assert.doesNotMatch(dropdown, /2099-12-10/);
  assert.match(render(undefined), /No past event dates supplied/);
  console.log('Event panel: future-only, mixed, empty and initial button state passed.');
} finally {
  await server.close();
}
