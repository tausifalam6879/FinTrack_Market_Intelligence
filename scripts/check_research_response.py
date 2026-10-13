"""Staged response checks: no model approvals, training or fabricated fallbacks."""
import sys
from production_smoke_test import request_json

base = sys.argv[1].rstrip('/')
assert request_json(base + '/health/ready')['status'] == 'ready'
news = request_json(base + '/market/news-feed?limit=20')
assert news.get('articles'), 'News provider returned no headlines; live traffic unchanged'
for symbol in ('INFY.NS', 'AAPL', 'RELIANCE.NS'):
    data = request_json(base + '/market/analysis?symbol=' + symbol)
    assert data.get('history'), 'Research history missing'
    assert data.get('predictionAvailable') is True, 'Expected sufficient history for staged test'
    assert 0 <= data['probabilityUp'] <= 100
    if data['model']['servingMode'] == 'experimental_runtime':
        assert data['experimental'] is True
        assert data['model']['quality'] == 'unapproved'
        assert data['predictionStatus']['code'] == 'EXPERIMENTAL_ESTIMATE'
    else:
        assert data['model']['servingMode'] == 'approved_artifact'
    print(symbol, data['model']['servingMode'], flush=True)
print('Health, news and research response checks passed.')
