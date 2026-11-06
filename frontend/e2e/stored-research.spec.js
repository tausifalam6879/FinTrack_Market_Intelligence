import { test, expect } from '@playwright/test';
import fs from 'node:fs';
const snapshot = JSON.parse(fs.readFileSync(new URL('../src/data/bundledMarketSnapshot.json', import.meta.url), 'utf8'));
const analysis = (symbol, price = 124) => ({...snapshot.analysis['^NSEI'], symbol, name: `Stored ${symbol}`, lastClose: price, dataAsOf: '2026-10-23T00:00:00Z'});

async function routes(page, handler) {
  await page.route('**/market/**', async route => {
    const url = new URL(route.request().url());
    const reply = body => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
    if (await handler?.(route, url, reply)) return;
    if (url.pathname.endsWith('/overview')) return reply(snapshot.overview);
    if (url.pathname.endsWith('/analysis')) return reply(analysis(url.searchParams.get('symbol') || '^NSEI'));
    if (url.pathname.endsWith('/stored-research')) return reply({items: []});
    if (url.pathname.endsWith('/experiments')) return reply({runs: []});
    if (url.pathname.endsWith('/documents')) return reply({items: []});
    return reply({});
  });
}

test('browser-cached company is selectable immediately while its fresh request is pending', async ({page}) => {
  await page.addInitScript(data => localStorage.setItem('fintrack.market.intelligence.v1.analysis.LOCAL.NS', JSON.stringify({data, savedAt:'2026-10-23T00:00:00Z'})), analysis('LOCAL.NS'));
  let finish;
  await routes(page, async (route, url, reply) => {
    if (url.pathname.endsWith('/analysis') && url.searchParams.get('symbol') === 'LOCAL.NS') {
      await new Promise(resolve => { finish = resolve; setTimeout(resolve, 5000); });
      if (!page.isClosed()) await reply(analysis('LOCAL.NS', 130));
      return true;
    }
  });
  await page.goto('/');
  await page.getByRole('tab', {name:/Intelligence & MLOps/i}).click();
  await page.getByRole('textbox', {name:'Company name or market ticker'}).fill('LOCAL.NS');
  await page.getByRole('button', {name:'Run research'}).click();
  await expect(page.locator('.analysis-hero')).toContainText('LOCAL.NS', {timeout:1000});
  await expect(page.getByRole('button', {name:'Refreshing research…'})).toBeEnabled();
  await expect.poll(() => Boolean(finish)).toBe(true);
  finish();
  await expect(page.getByRole('button', {name:'Run research'})).toBeEnabled();
});

test('MySQL-only preview appears before slow online research and upgrades when fresh evidence arrives', async ({page}) => {
  let finish;
  let monitoringStarted = false;
  await routes(page, async (route, url, reply) => {
    const symbol = url.searchParams.get('symbol');
    if (url.pathname.endsWith('/stored-research')) {
      await reply(symbol ? {analysis:{data:analysis(symbol),savedAt:'2026-10-23T00:00:00Z'},mode:'stored'} : {items:[{symbol:'DBONLY',name:'Database Company'}]});
      return true;
    }
    if (url.pathname.endsWith('/model-status') && symbol === 'DBONLY') monitoringStarted = true;
    if (url.pathname.endsWith('/analysis') && symbol === 'DBONLY') {
      await new Promise(resolve => { finish = resolve; setTimeout(resolve, 5000); });
      if (!page.isClosed()) await reply(analysis('DBONLY', 140));
      return true;
    }
  });
  await page.goto('/');
  await page.getByRole('tab', {name:/Intelligence & MLOps/i}).click();
  await page.getByRole('textbox', {name:'Company name or market ticker'}).fill('Database Company');
  await page.getByRole('button', {name:'Run research'}).click();
  await expect(page.locator('.analysis-hero')).toContainText('DBONLY', {timeout:1500});
  await expect(page.getByRole('status').filter({hasText:'Showing previously stored research'})).toBeVisible();
  expect(monitoringStarted).toBe(true);
  await expect.poll(() => Boolean(finish)).toBe(true);
  finish();
  await expect(page.getByRole('status').filter({hasText:'Showing previously stored research'})).toHaveCount(0);
});

test('offline browser still calls the loopback API for stored data and sends preferLocal to AI', async ({page}) => {
  let aiBody;
  const hosts = [];
  await page.addInitScript(() => Object.defineProperty(navigator,'onLine',{get:()=>false}));
  await routes(page, async (route, url, reply) => {
    hosts.push(url.hostname);
    if (url.pathname.endsWith('/agent')) {
      aiBody=route.request().postDataJSON();
      await reply({answer:'Stored company evidence is available offline.',llmProvider:'ollama',llmStatus:'connected'});
      return true;
    }
  });
  await page.goto('/');
  await page.getByRole('tab', {name:/Intelligence & MLOps/i}).click();
  await expect(page.locator('.analysis-hero')).toBeVisible();
  await page.locator('.agent-launcher').click();
  await page.getByPlaceholder('Ask in simple words…').fill('Explain these stored indicators');
  await page.getByRole('button', {name:'Send',exact:true}).click();
  await expect(page.locator('.chat-message.assistant')).toContainText('Stored company evidence is available offline.');
  expect(aiBody.preferLocal).toBe(true);
  expect(hosts.every(host => host === 'localhost' || host === '127.0.0.1')).toBe(true);
});
