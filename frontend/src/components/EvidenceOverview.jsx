const valid=v=>typeof v==='number'&&Number.isFinite(v);
export default function EvidenceOverview({analysis,company,mode}) {
  const positive=[],negative=[];
  const growth=company?.financials?.growth;
  if(valid(growth?.revenueGrowthPercent)) {
    (growth.revenueGrowthPercent>=0?positive:negative).push(`Reported revenue growth is ${growth.revenueGrowthPercent}%.`);
  }
  if(valid(growth?.earningsGrowthPercent)) {
    (growth.earningsGrowthPercent>=0?positive:negative).push(`Reported earnings growth is ${growth.earningsGrowthPercent}%.`);
  }
  const probability=analysis.probabilityUp;
  const separation=valid(probability)?Math.abs(probability-50):null;
  if(valid(probability)&&probability>=58)positive.push(`The model's rise probability is ${probability}%; it remains an uncertain forecast.`);
  if(valid(probability)&&probability<=42)negative.push(`The model's fall probability is ${(100-probability).toFixed(1)}%; it remains an uncertain forecast.`);
  const liquidity=company?.financials?.balanceSheet?.currentRatio;
  if(valid(liquidity)&&liquidity<1)negative.push(`Current ratio is ${liquidity}; reported current liabilities exceed current assets. Industry context matters.`);
  return <section className="portfolio-panel" aria-label="Research factors and evidence quality">
    <h3>Positive factors, negative factors and uncertainties</h3>
    <div className="metric-grid">{[['Positive factors',positive],['Negative factors',negative]].map(([title,items])=><article key={title}><h4>{title}</h4>{items.length?<ul>{items.map(item=><li key={item}>{item}</li>)}</ul>:<p>No qualifying factor found in the available fields. This does not establish that none exists.</p>}</article>)}</div>
    <h4>How strong is the direction signal?</h4>
    <p>{separation==null?'Probability unavailable.':`The rise probability is ${probability}%, ${separation.toFixed(1)} percentage points from 50%. ${separation<8?'The model has little directional separation.':'The model leans toward one direction.'}`} This distance is not a measure of proven forecast reliability.</p>
    <p>Measured balanced accuracy: {valid(analysis.model?.balancedAccuracy)?`${analysis.model.balancedAccuracy}%`:'Unavailable'}. Market conditions can change; reported financial periods can differ; missing data is not a neutral signal.</p>
    <h4>Evidence provenance</h4>
    <p>Price mode: {mode} · Price/model session: {analysis.modelDataDate||analysis.dataAsOf||'Unavailable'} · Model: {analysis.model?.type||'Unavailable'} · Prediction generated: {analysis.generatedAt||'Unavailable'}.</p>
    <p>Company source: {company?.source||'Unavailable'} · Company data updated: {company?.generatedAt||company?.dataAsOf||'Unavailable'}. A response marked live can still contain delayed provider data; use the timestamps.</p>
  </section>;
}
