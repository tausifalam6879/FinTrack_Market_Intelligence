"""Descriptive event-window returns, without causal attribution."""
from datetime import date
import math
from fastapi import APIRouter, HTTPException, Query
from market_intelligence import _history, _sanitize_symbol

router=APIRouter(prefix='/market',tags=['Event research'])

def event_window(frame,event_date,benchmark=None):
    selected=date.fromisoformat(event_date)
    if selected>date.today():raise ValueError('Select a past event date.')
    close=frame['Close'].sort_index()
    if close.index.has_duplicates:raise ValueError('Duplicate sessions in price history.')
    dates=[i.date() for i in close.index]
    after=[i for i,d in enumerate(dates) if d>=selected]
    if not after or after[0]==0:raise ValueError('History must include the session before and after the event date.')
    first=after[0];base=float(close.iloc[first-1]);base_date=dates[first-1]
    if not math.isfinite(base) or base<=0:raise ValueError('Invalid baseline price.')
    benchmark_prices={i.date():float(v) for i,v in benchmark['Close'].items()} if benchmark is not None else {}
    rows=[]
    for sessions in (1,5,20):
        index=first+sessions-1
        if index>=len(close):
            rows.append({'sessions':sessions,'status':'not_yet_available'});continue
        price=float(close.iloc[index]);end=dates[index]
        if not math.isfinite(price) or price<=0:
            rows.append({'sessions':sessions,'status':'invalid_price'});continue
        asset_return=(price/base-1)*100
        b0=benchmark_prices.get(base_date);b1=benchmark_prices.get(end)
        benchmark_return=(b1/b0-1)*100 if b0 and b1 and math.isfinite(b0) and math.isfinite(b1) and b0>0 and b1>0 else None
        rows.append({'sessions':sessions,'status':'available','date':end.isoformat(),'price':round(price,4),
          'returnPercent':round(asset_return,3),'benchmarkReturnPercent':round(benchmark_return,3) if benchmark_return is not None else None,
          'excessReturnPoints':round(asset_return-benchmark_return,3) if benchmark_return is not None else None})
    return {'eventDate':event_date,'baselineDate':base_date.isoformat(),'baselinePrice':base,'firstSession':dates[first].isoformat(),'windows':rows,
      'method':'Returns from the last close before the selected date to the first, fifth and twentieth session on or after it. Benchmark uses exactly matching dates. Excess return is the percentage-point difference, not a risk-adjusted causal estimate.',
      'limitations':'The selected date is supplied by the user, not a verified announcement timestamp. After-hours releases may require selecting the next session. Raw closing prices can be affected by splits and exclude dividends. Price changes do not prove that an event caused them.'}

@router.get('/event-impact')
def event_impact(symbol:str=Query(min_length=1,max_length=20),event_date:str=Query(pattern=r'^\d{4}-\d{2}-\d{2}$')):
    try:
        symbol=_sanitize_symbol(symbol)
        benchmark_symbol='^NSEI' if symbol.endswith('.NS') else '^BSESN' if symbol.endswith('.BO') else '^GSPC' if symbol.isascii() and symbol.isalpha() and len(symbol)<=5 else None
        frame=_history(symbol,'2y');benchmark=None
        if benchmark_symbol:
            try:benchmark=_history(benchmark_symbol,'2y')
            except Exception:pass
        result=event_window(frame,event_date,benchmark)
        return {**result,'symbol':symbol,'benchmarkSymbol':benchmark_symbol if benchmark is not None else None}
    except (ValueError,KeyError) as error:raise HTTPException(status_code=422,detail=str(error)) from error
