const number = value => value == null || value === '' ? null : Number.isFinite(Number(value)) ? Number(value) : null;
export function researchChanges(previous, current) {
  if(!previous || !current || previous.symbol!==current.symbol)return null;
  const before=number(previous.probabilityUp), after=number(current.probabilityUp);
  const reasons=[];
  const versionChanged=(previous.model?.modelRunId||previous.model?.type)!==(current.model?.modelRunId||current.model?.type)
    || previous.model?.datasetVersion!==current.model?.datasetVersion;
  if(versionChanged)reasons.push('Model or training dataset changed');
  if(previous.model?.servingMode!==current.model?.servingMode)reasons.push('Prediction serving mode changed');
  if(previous.dataAsOf!==current.dataAsOf)reasons.push('Newer observation timestamp');
  const inputs=[];
  for(const [key,label] of [['rsi14','RSI'],['sma20','SMA20'],['dailyVolatility20d','Daily volatility']]) {
    const a=number(previous.technicalIndicators?.[key]),b=number(current.technicalIndicators?.[key]);
    if(a!==null&&b!==null&&Math.abs(a-b)>1e-8)inputs.push({label,before:a,after:b});
  }
  const probabilityChanged=before!==after;
  if(!probabilityChanged&&!versionChanged&&!inputs.length&&previous.outlook===current.outlook)return null;
  return {before,after,delta:before!==null&&after!==null ? Math.round((after-before)*10)/10:null,
    previousOutlook:previous.outlook,currentOutlook:current.outlook,reasons,inputs,versionChanged,
    previousAsOf:previous.dataAsOf,currentAsOf:current.dataAsOf};
}
