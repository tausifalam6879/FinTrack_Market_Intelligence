// Real browser -> built React app -> recovered gateway -> recovered database.
// No request fixtures or bundled data may satisfy the research assertion.
import { chromium } from '@playwright/test';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
const [gateway, symbol] = process.argv.slice(2);
if (!gateway || !symbol) throw new Error('Gateway URL and recovered symbol required');
const root = path.resolve('dist');
const server = http.createServer((req, res) => {
  if (req.url.startsWith('/api/')) {
    const upstream = http.request(new URL(req.url.slice(4), gateway), {method:req.method, headers:{'content-type':'application/json'}}, reply => {
      res.writeHead(reply.statusCode, {'content-type':reply.headers['content-type'] || 'application/json'});
      reply.pipe(res);
    });
    upstream.on('error', () => {res.writeHead(502); res.end('Recovered gateway unavailable');});
    req.pipe(upstream);
    return;
  }
  const file = path.resolve(root, '.' + new URL(req.url,'http://localhost').pathname);
  if (file !== root && !file.startsWith(root + path.sep)) {res.writeHead(403);res.end();return;}
  const target = file === root || file.endsWith(path.sep) ? path.join(root,'index.html') : file;
  if (!fs.existsSync(target)) {res.writeHead(404);res.end();return;}
  const mime={'.html':'text/html','.js':'application/javascript','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp'};
  res.setHeader('Content-Type',mime[path.extname(target)] || 'application/octet-stream');
  fs.createReadStream(target).pipe(res);
});
await new Promise(resolve => server.listen(4173,'127.0.0.1',resolve));
const browser = await chromium.launch({headless:true,args:['--no-sandbox']});
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  const errors=[];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:4173');
  await page.getByRole('tab',{name:'Intelligence & MLOps',exact:true}).click();
  await page.getByRole('textbox',{name:'Company name or market ticker'}).fill(symbol);
  const responsePromise=page.waitForResponse(response => {
    const url=new URL(response.url());
    return url.pathname==='/api/market/analysis' && url.searchParams.get('symbol')===symbol;
  },{timeout:150000});
  await page.getByRole('button',{name:'Run research',exact:true}).click();
  const response=await responsePromise;
  if (!response.ok()) throw new Error('Recovered analysis returned HTTP '+response.status());
  const result=await response.json();
  if(result.symbol!==symbol || !result.history?.length) throw new Error('No restored research history returned');
  const renderedSymbol=page.locator('#research-summary .asset-label');
  await renderedSymbol.waitFor({timeout:30000});
  if ((await renderedSymbol.textContent()).trim()!==symbol) throw new Error('Rendered research symbol mismatch');
  if(errors.length) throw new Error('Browser JavaScript error');
  fs.mkdirSync('/tmp/recovery-browser',{recursive:true});
  await page.screenshot({path:'/tmp/recovery-browser/research.png',fullPage:true});
  console.log(JSON.stringify({status:'browser_recovery_verified',symbol,historyRows:result.history.length,
    servingMode:result.model?.servingMode,scope:'Built React UI through recovered gateway; real analysis response, no mocked data'}));
} finally {await browser.close(); server.close();}
