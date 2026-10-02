import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

test('empty news does not replace last good cache, and poisoned empty cache is rejected', async () => {
  const storage = new Map();
  let source = readFileSync(new URL('../src/services/marketApi.js', import.meta.url), 'utf8');
  source = source.replace(/^import .*;\r?\n/, 'const bundledSnapshot = {};\n')
    .replaceAll('import.meta.env', '({})').replace('export const marketApi', 'const marketApi');
  source += '\nglobalThis.check = { withCache, readCache };';
  const context = vm.createContext({localStorage: {
    getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value),
    removeItem: (key) => storage.delete(key),
  }});
  vm.runInContext(source, context);
  const { withCache, readCache } = context.check;
  await withCache('news-feed', async () => ({articles: [{title: 'Verified headline'}]}));
  const result = await withCache('news-feed', async () => ({articles: []}));
  assert.equal(result.mode, 'cache');
  assert.equal(result.data.articles[0].title, 'Verified headline');
  storage.set('fintrack.market.intelligence.v1.news-feed', JSON.stringify({data: {articles: []}}));
  assert.equal(readCache('news-feed'), null);
  await assert.rejects(withCache('news-feed', async () => ({articles: []})));
});
