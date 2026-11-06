import {test,expect} from '@playwright/test';
import fs from 'node:fs';
const snapshot=JSON.parse(fs.readFileSync(new URL('../src/data/bundledMarketSnapshot.json',import.meta.url),'utf8'));
const research=(symbol,p=45)=>({...snapshot.analysis['^NSEI'],symbol,name:symbol,probabilityUp:p,probabilityDown:100-p,outlook:p>=58?'BULLISH':'NEUTRAL',dataAsOf:'2026-10-23T00:00:00Z'});

async function api(page,callback) {
  await page.route('**/market/**',async route=>{
    const url=new URL(route.request().url()),symbol=url.searchParams.get('symbol')||'^NSEI';
    const reply=body=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
    if(await callback?.(url,reply))return;
    if(url.pathname.endsWith('/overview'))return reply(snapshot.overview);
    if(url.pathname.endsWith('/offline-readiness'))return reply({items:[{symbol:'INFY.NS',name:'Infosys',storedBars:250,dataAsOf:'2026-10-23',priceHistoryReady:true,researchSaved:true,localArtifactPresent:false,approvedModelRegistered:false}],localAI:{status:'installed',model:'llama3.2:1b'},generatedAt:'2026-11-04T00:00:00Z'});
    if(url.pathname.endsWith('/stored-research'))return reply(url.searchParams.has('symbol') ? {analysis:{data:research(symbol),savedAt:'2026-10-23'}} : {items:[{symbol:'INFY.NS',name:'Infosys'}]});
    if(url.pathname.endsWith('/analysis'))return reply(research(symbol,65));
    if(url.pathname.endsWith('/experiments'))return reply({runs:[]});
    if(url.pathname.endsWith('/documents'))return reply({items:[]});
    return reply({});
  });
}

test('readiness shows real coverage distinctions and queue pauses offline then syncs on resume',async({page})=>{
  await page.addInitScript(()=>{window.__network=false;Object.defineProperty(navigator,'onLine',{get:()=>window.__network,configurable:true});});
  let refreshes=0;
  await api(page,async(url,reply)=>{
    if(url.pathname.endsWith('/analysis')&&url.searchParams.get('symbol')==='INFY.NS'){refreshes++;await reply(research('INFY.NS',65));return true;}
  });
  await page.goto('/');await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  const panel=page.locator('.research-readiness');await panel.locator(':scope > summary').click();
  await expect(panel).toContainText('1 companies have stored price history');
  await expect(panel).toContainText('llama3.2:1b installed and reachable');
  await panel.getByRole('button',{name:'Sync stored companies',exact:true}).click();
  await expect(panel.locator('.sync-jobs')).toContainText('queued');expect(refreshes).toBe(0);
  await panel.getByRole('button',{name:'Pause sync',exact:true}).click();
  await page.evaluate(()=>{window.__network=true;window.dispatchEvent(new Event('online'));});
  await expect(panel).toContainText('Paused by you');expect(refreshes).toBe(0);
  await panel.getByRole('button',{name:'Resume sync',exact:true}).click();
  await expect(panel.locator('.sync-jobs')).toContainText('done');expect(refreshes).toBe(1);
});

test('advanced details shows a dated next-session audit and changed outlook without fake model attribution',async({page})=>{
  await page.addInitScript(data=>localStorage.setItem('fintrack.market.intelligence.v1.analysis.AAPL',JSON.stringify({data,savedAt:'2026-10-23'})),research('AAPL'));
  await api(page,async(url,reply)=>{
    if(url.pathname.endsWith('/model-status')){
      await reply({predictionMonitoring:{sessionAudit:{evaluated:20,pending:2,retrospectiveExcluded:3,windows:[{window:20,evaluated:20,balancedAccuracy:60,rocAuc:.62,brierScore:.23,baselines:{expandingMajority:{balancedAccuracy:50},previousSessionMomentum:{balancedAccuracy:52}}}],records:[],method:'Synthetic browser fixture for UI verification only.'}}});return true;
    }
  });
  await page.goto('/');await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('textbox',{name:'Company name or market ticker'}).fill('AAPL');
  await page.getByRole('button',{name:'Run research',exact:true}).click();
  await expect(page.locator('.analysis-hero')).toContainText('BULLISH');
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  await expect(page.getByRole('region',{name:'Research changes'})).toContainText('+20 percentage points');
  const audit=page.getByRole('region',{name:'Next session outcome audit'});
  await expect(audit).toContainText('3 late-generated snapshots excluded');await expect(audit).toContainText('60%');
});

test('offline training evidence separates failed holdout checks from calibrated selection scores',async({page})=>{
  await api(page,async(url,reply)=>{
    if(url.pathname.endsWith('/model-status')){
      await reply({latestModelRun:{model:'Regularized Logistic Regression',status:'rejected',featureSchema:'ohlcv_v2',
        holdout:{balancedAccuracy:49.1,rocAuc:51.2},qualityGate:{checks:{balancedAccuracyAtLeast52Percent:false,matchesOrBeatsBestNaiveBaseline:false}},
        walkForwardCandidates:[{id:'lr:ohlcv_v2',name:'Regularized Logistic Regression',featureSchema:'ohlcv_v2',featureCount:23,balancedAccuracy:.57,rocAuc:.61,brierScore:.24}]}});return true;
    }
  });
  await page.goto('/');await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  const panel=page.locator('#model-operations');
  await expect(panel).toContainText('Balanced accuracy below 52%');
  await expect(panel).toContainText('holdout balanced accuracy 49.1%');
  await panel.getByText('Offline classifier comparison', {exact:false}).click();
  await expect(panel.locator('.registry-training-evidence')).toContainText('57.0%');
  await expect(panel.locator('.registry-training-evidence')).toContainText('training-only chronological validation');
});

test('market-factor experiment stays separate from serving approval and future outcomes',async({page})=>{
  await api(page,async(url,reply)=>{
    if(url.pathname.endsWith('/model-status')){
      await reply({marketFactorResearch:{benchmarkSymbol:'^NSEI',selected:{featureSchema:'ohlcv_market_v3'},
        matchedControl:{balancedAccuracy:.466},holdout:{balancedAccuracy:.539,rocAuc:.521,start:'2026-02-01',end:'2026-11-02',rows:176},
        shadowOutcome:{status:'pending_future_completed_session'},
        shadowHistory:{evaluated:0,pending:1,excluded:0,balancedAccuracy:null,brierScore:null,records:[{modelDataDate:'2026-11-04',generatedAt:'2026-11-04T17:00:00Z',probabilityUp:.54,status:'pending_future_completed_session'}]},marketDataPolicy:'Strictly earlier session date.',
        limitation:'Retrospective research. Not approved or deployed.'}});return true;
    }
  });
  await page.goto('/');await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  await page.getByText('Market-factor research · awaiting future validation',{exact:true}).click();
  const research=page.locator('details.registry-training-evidence').filter({hasText:'Market-factor research'});
  await expect(research).toContainText('46.6% balanced');await expect(research).toContainText('53.9% balanced');
  await expect(research).toContainText('pending future completed session');
  await expect(research).toContainText('does not replace the serving model');
  await expect(research).toContainText('0 evaluated · 1 pending');
  await expect(research).toContainText('Awaiting both outcome classes');
  await expect(research.locator('.research-shadow-history tbody')).toContainText('54.0%');
  await expect(page.locator('#registry-title')).toHaveText('Approved model unavailable');
});

test('prospective controls show paired samples and keep direction-only error unscored',async({page})=>{
  await api(page,async(url,reply)=>{
    if(url.pathname.endsWith('/model-status')){
      await reply({marketFactorResearch:{benchmarkSymbol:'^NSEI',selected:{featureSchema:'ohlcv_market_v3'},
        matchedControl:{balancedAccuracy:.466},holdout:{balancedAccuracy:.539,rocAuc:.521,start:'2026-02-01',end:'2026-11-02',rows:176},
        shadowOutcome:{status:'pending_future_completed_session'},marketDataPolicy:'Strictly earlier session date.',limitation:'Synthetic UI fixture; not real model performance.',
        shadowHistory:{evaluated:22,pending:1,excluded:1,balancedAccuracy:.591,brierScore:.241,records:[],baselineComparisons:[{
          id:'previous_session_momentum',label:'Previous-session momentum',pairedOutcomes:20,missingBaseline:2,
          model:{balancedAccuracy:.6,brierScore:.24},baseline:{balancedAccuracy:.5,brierScore:null},
          balancedAccuracyDifference:.1,modelOnlyCorrect:4,baselineOnlyCorrect:2
        }]}}});return true;
    }
  });
  await page.goto('/');await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  await page.getByText('Market-factor research · awaiting future validation',{exact:true}).click();
  const paired=page.getByRole('region',{name:'Prospective baseline comparison'});
  await expect(paired).toContainText('20 (2 unavailable)');
  await expect(paired).toContainText('60.0%');await expect(paired).toContainText('50.0%');
  await expect(paired).toContainText('10.0 pp');await expect(paired).toContainText('0.240 / Not scored');
  await expect(paired).toContainText('never triggers automatic promotion');
});

test('factor history shows observation cutoffs without claiming historical training',async({page})=>{
  await api(page,async(url,reply)=>{
    if(url.pathname.endsWith('/model-status')){
      await reply({pointInTimeFactors:{status:'collecting',families:[{
        family:'fundamental',observations:1,first_observed:'2026-11-05T10:00:00+00:00',last_observed:'2026-11-05T10:00:00+00:00'
      }]}});return true;
    }
  });
  await page.goto('/');await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  await page.getByText('Timestamped news and fundamental history',{exact:true}).click();
  const coverage=page.locator('details[aria-label="Timestamped factor history"]');
  await expect(coverage).toContainText('fundamental');await expect(coverage).toContainText('2026-11-05T10:00:00+00:00');
  await expect(coverage).toContainText('Cached research is not backfilled');
  await expect(coverage).toContainText('Existing classifiers are unchanged');
});

test('horizon research labels different targets and keeps weak controls and insufficient history visible',async({page})=>{
  await api(page,async(url,reply)=>{
    if(url.pathname.endsWith('/model-status')){
      await reply({horizonResearch:{featureScope:'Synthetic market-factor UI fixture.',limitation:'Historical research only; no model promoted.',results:[
        {horizonSessions:1,status:'research_only',selected:{name:'Daily research classifier'},purgeGapRows:1,
         holdout:{nonOverlappingOutcomes:178,balancedAccuracy:.49,rocAuc:.50,start:'2026-01-01',end:'2026-11-01'},bestNaiveBalancedAccuracy:.52,balancedAccuracyEdge:-.03},
        {horizonSessions:5,status:'research_only',selected:{name:'Five-session research classifier'},purgeGapRows:5,
         holdout:{nonOverlappingOutcomes:30,balancedAccuracy:.58,rocAuc:.54,start:'2026-01-01',end:'2026-11-01'},bestNaiveBalancedAccuracy:.52,balancedAccuracyEdge:.06},
        {horizonSessions:10,status:'not_evaluable',reason:'Insufficient history for non-overlapping outcomes.'}
      ]}});return true;
    }
  });
  await page.goto('/');await page.getByRole('tab',{name:/Intelligence & MLOps/i}).click();
  await page.getByRole('button',{name:'Advanced model details',exact:true}).click();
  const panel=page.locator('details[aria-label="Research horizon comparison"]');await panel.locator('summary').click();
  await expect(panel).toContainText('A longer-horizon result is not daily accuracy');
  await expect(panel).toContainText('-3.0 pp');await expect(panel).toContainText('6.0 pp');
  await expect(panel).toContainText('5 sessions');await expect(panel).toContainText('Insufficient history');
  await expect(panel).toContainText('The serving prediction remains unchanged');
});
