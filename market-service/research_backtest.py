"""Fixed-model, chronological research simulation; no model selection on test returns."""
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from market_intelligence import _features, _history, _sanitize_symbol, _cache_get, _cache_put

router=APIRouter(prefix='/market', tags=['Research backtest'])

def simulate_backtest(frame, cost_bps=10):
    if not 0 <= cost_bps <= 100:
        raise ValueError('Trading cost must be between 0 and 100 basis points per side.')
    frame=frame.sort_index()
    if frame.index.has_duplicates or 'Open' not in frame:
        raise ValueError('Unique dated open prices are required.')
    if not np.isfinite(frame['Open']).all() or (frame['Open']<=0).any():
        raise ValueError('Execution prices must be finite and positive.')
    features=_features(frame)
    # Signal at close t, execution at open t+1, valuation at open t+2.
    returns=frame['Open'].shift(-2)/frame['Open'].shift(-1)-1
    dataset=features.copy()
    dataset['outcome']=returns
    dataset['target']=(returns>0).astype(int)
    dataset=dataset.replace([np.inf,-np.inf],np.nan).dropna()
    if len(dataset)<140: raise ValueError('At least 140 clean feature rows are needed.')
    if (dataset['outcome']<=-1).any(): raise ValueError('Invalid non-positive execution prices.')
    columns=list(features.columns)
    probabilities=[]; actual=[]; audits=[]; signals=[]
    for start in range(100,len(dataset),20):
        train=dataset.iloc[:start-1]
        test=dataset.iloc[start:start+20]
        if train['target'].nunique()<2: raise ValueError('Training needs both up and down outcomes.')
        model=make_pipeline(StandardScaler(),LogisticRegression(max_iter=500,random_state=42,solver='liblinear'))
        model.fit(train[columns],train['target'])
        probabilities.extend(model.predict_proba(test[columns])[:,1].tolist())
        actual.extend(test['outcome'].tolist())
        signals.extend(test.index.strftime('%Y-%m-%d').tolist())
        audits.append({'trainingThrough':train.index[-1].strftime('%Y-%m-%d'),
                      'firstSignal':test.index[0].strftime('%Y-%m-%d'),'trainingRows':len(train)})
    position=(np.asarray(probabilities)>=0.55).astype(float)
    turnover=np.abs(np.diff(np.r_[0,position]))
    costs=turnover*cost_bps/10000
    costs[-1]+=position[-1]*cost_bps/10000
    strategy=position*np.asarray(actual)-costs
    equity=np.r_[1,np.cumprod(1+strategy)]
    benchmark=np.r_[1,np.cumprod(1+np.asarray(actual))]
    peak=np.maximum.accumulate(equity)
    deviation=float(np.std(strategy,ddof=1))
    return {'status':'available','model':'Fixed logistic regression','thresholdPercent':55,
      'observations':len(actual),'from':signals[0],'through':signals[-1],
      'strategyReturnPercent':round((equity[-1]-1)*100,2),
      'benchmarkReturnPercent':round((benchmark[-1]-1)*100,2),
      'maximumDrawdownPercent':round(float(np.min(equity/peak-1))*100,2),
      'sharpeZeroRiskFree':round(float(np.mean(strategy))/deviation*np.sqrt(252),3) if deviation>1e-12 else None,
      'accuracyPercent':round(float(np.mean((np.asarray(probabilities)>=.5)==(np.asarray(actual)>0)))*100,2),
      'exposurePercent':round(float(np.mean(position))*100,2),'costBpsPerSide':cost_bps,
      'audit':audits,'curve':[{'signalDate':d,'strategy':round(float(equity[i+1]),5),
         'benchmark':round(float(benchmark[i+1]),5)} for i,d in enumerate(signals)],
      'method':'Expanding training; refit every 20 observations. Signals at close, trades at next open, returns to following open. Training excludes unobserved outcomes. Long or cash, 10 bps default per trade side including final exit. Buy-and-hold benchmark before costs.',
      'limitations':'Historical research simulation, not the deployed model or actual portfolio returns. Unadjusted prices may be distorted by corporate actions. No dividends, taxes, financing or market impact. Sharpe assumes zero cash return and 252 observations per year.'}

@router.get('/backtest')
def backtest(symbol: str=Query(min_length=1,max_length=20)):
    try:
        symbol=_sanitize_symbol(symbol)
        key=f'research-backtest:{symbol}'
        cached=_cache_get(key,3600)
        if cached is not None:return cached
        frame=_history(symbol,'2y')
        result=simulate_backtest(frame)
        result['symbol']=symbol
        result['dataSource']=frame.attrs.get('fintrack_source','Market provider price history')
        return _cache_put(key,result)
    except ValueError as error:
        raise HTTPException(status_code=422,detail=str(error)) from error
