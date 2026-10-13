"""Staged response checks: no model approvals, training or fabricated fallbacks."""
import math
import sys
from production_smoke_test import request_json

def validate_analysis(data, symbol):
    """Accept legacy approved responses without weakening experimental checks."""
    def require(condition, message):
        if not condition:
            raise ValueError(f'{symbol}: {message}')

    require(data.get('symbol') == symbol, 'Unexpected response symbol')
    require(bool(data.get('history')), 'Research history missing')
    if 'predictionAvailable' in data:
        require(data['predictionAvailable'] is True, 'Prediction explicitly unavailable')
    probability = data.get('probabilityUp')
    require(type(probability) in (int, float) and math.isfinite(probability)
            and 0 <= probability <= 100, 'Invalid prediction probability')
    model = data.get('model') or {}
    mode = model.get('servingMode')
    if mode == 'experimental_runtime':
        require(data.get('predictionAvailable') is True, 'Experimental availability missing')
        require(data.get('experimental') is True, 'Experimental label missing')
        require(model.get('quality') == 'unapproved', 'Experimental quality label missing')
        require((data.get('predictionStatus') or {}).get('code') == 'EXPERIMENTAL_ESTIMATE',
                'Experimental status missing')
    else:
        require(mode == 'approved_artifact', 'Unknown serving mode')
        require(bool(model.get('modelRunId')), 'Approved model run ID missing')
        require(data.get('experimental') is not True, 'Conflicting experimental label')
    return mode


def main():
    base = sys.argv[1].rstrip('/')
    if request_json(base + '/health/ready')['status'] != 'ready':
        raise ValueError('Staged service is not ready')
    news = request_json(base + '/market/news-feed?limit=20')
    if not news.get('articles'):
        raise ValueError('News provider returned no headlines; live traffic unchanged')
    for symbol in ('INFY.NS', 'AAPL', 'RELIANCE.NS'):
        data = request_json(base + '/market/analysis?symbol=' + symbol)
        print(symbol, validate_analysis(data, symbol), flush=True)
    print('Health, news and research response checks passed.')


if __name__ == '__main__':
    main()
