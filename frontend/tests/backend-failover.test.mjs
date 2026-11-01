import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const primary = 'https://primary.example';
const backup = 'https://backup.example';
function harness(handler, enabled = true) {
  let now = 100000;
  const calls = [];
  const env = { VITE_MARKET_API_BASE_URL: primary,
    VITE_MARKET_FALLBACK_API_BASE_URL: backup,
    VITE_MARKET_FAILOVER_ENABLED: String(enabled) };
  let source = readFileSync(new URL('../src/services/marketApi.js', import.meta.url), 'utf8')
    .replace(/^import .*;\r?\n/, 'const bundledSnapshot = {};\n')
    .replaceAll('import.meta.env', JSON.stringify(env))
    .replace('export const marketApi', 'const marketApi');
  source += '\nglobalThis.check = { request, marketApi };';
  const context = vm.createContext({
    AbortController, TypeError, URLSearchParams,
    Date: { now: () => now },
    window: { setTimeout, clearTimeout },
    fetch: async (url, options) => {
      calls.push({ url, options });
      return handler(url, options);
    },
  });
  vm.runInContext(source, context);
  return { ...context.check, calls, advance: () => { now += 60001; } };
}
const response = (status = 200) => ({ ok: status === 200, status,
  headers: { get: () => null }, json: async () => ({ answer: 'Evidence' }),
  text: async () => 'Unavailable' });

test('healthy Google primary never calls backup', async () => {
  const h = harness(() => response());
  const data = await h.request('/market/analysis');
  assert.equal(h.calls.length, 1);
  assert.ok(h.calls[0].url.startsWith(primary));
  assert.equal(data._delivery.fallback, false);
});

test('outage switches sequentially, skips failed primary briefly, then recovers', async () => {
  let failed = true;
  const h = harness(url => response(url.startsWith(primary) && failed ? 503 : 200));
  assert.equal((await h.request('/market/analysis'))._delivery.fallback, true);
  assert.deepEqual(h.calls.map(c => c.url), [primary + '/market/analysis', backup + '/market/analysis']);
  await h.request('/market/news-feed');
  assert.equal(h.calls[2].url, backup + '/market/news-feed');
  h.advance(); failed = false;
  assert.equal((await h.request('/market/analysis'))._delivery.fallback, false);
  assert.equal(h.calls[3].url, primary + '/market/analysis');
});

test('network and timeout failures can use backup', async () => {
  for (const timeout of [false, true]) {
    const h = harness(url => {
      if (url.startsWith(primary)) {
        const error = new TypeError('Disconnected');
        if (timeout) error.name = 'AbortError';
        throw error;
      }
      return response();
    });
    assert.equal((await h.request('/market/analysis'))._delivery.fallback, true);
  }
});

test('client errors and rate limits do not use backup', async () => {
  for (const status of [400, 401, 403, 404, 422, 429]) {
    const h = harness(() => response(status));
    await assert.rejects(h.request('/market/analysis'));
    assert.equal(h.calls.length, 1);
  }
});

test('read-only AI and comparison payloads reach backup unchanged after failure', async () => {
  for (const path of ['/market/agent', '/market/compare', '/market/documents/ask']) {
    const h = harness(url => response(url.startsWith(primary) ? 502 : 200));
    const body = { symbol: 'AAPL', message: 'Explain the business' };
    await h.request(path, { method: 'POST', body });
    assert.equal(h.calls.length, 2);
    assert.equal(h.calls[1].options.body, JSON.stringify(body));
  }
});

test('document preparation is never replayed on backup', async () => {
  const h = harness(() => response(503));
  await assert.rejects(h.marketApi.prepareDocuments('AAPL'));
  assert.equal(h.calls.length, 1);
});

test('Google edge HTML rejection can fail over while application 403 cannot', async () => {
  const h = harness(url => url.startsWith(primary) ? {
    ...response(403),
    headers: { get: key => key === 'Content-Type' ? 'text/html; charset=UTF-8' : null },
    text: async () => '<html>Your client does not have permission to get URL /market/analysis</html>',
  } : response());
  assert.equal((await h.request('/market/analysis'))._delivery.fallback, true);
  assert.equal(h.calls.length, 2);
});

test('two failed servers return an error, with no unbounded retries', async () => {
  const h = harness(() => response(503));
  await assert.rejects(h.request('/market/news-feed'));
  assert.equal(h.calls.length, 2);
});

test('feature stays off in other builds unless explicitly enabled', async () => {
  const h = harness(() => response(503), false);
  await assert.rejects(h.request('/market/analysis', { retry: false }));
  assert.equal(h.calls.length, 1);
});
