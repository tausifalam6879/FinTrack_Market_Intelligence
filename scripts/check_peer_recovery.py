"""Verify dynamic peers through Google and the independent Render gateway."""
import argparse
import json

from production_smoke_test import request_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--primary', default='https://fintrack-gateway-304232323336.asia-south1.run.app')
    parser.add_argument('--backup', default='https://fintrack-market-gateway.onrender.com')
    args = parser.parse_args()
    # Ordinary research ensures the existing companies row is present before
    # retaining evidence. This does not train or approve a model.
    request_json(args.primary.rstrip('/') + '/market/analysis?symbol=AAPL')
    for label, base in [('primary', args.primary), ('backup', args.backup)]:
        data = request_json(base.rstrip('/') + '/market/peer-comparison?symbol=AAPL&refresh=true')
        if data.get('symbol') != 'AAPL' or data.get('status') != 'available' or not data.get('peers'):
            raise RuntimeError(f'{label}: peer recovery not yet available; check the deployed commit and provider access.')
        print(json.dumps({'host': label, 'symbol': data['symbol'], 'peerCount': len(data['peers']),
                          'source': data.get('source'), 'mode': data.get('discoveryMode', 'detailed_screener'),
                          'coverage': data.get('coverageLevel', 'provider_fields'),
                          'observedAt': data.get('generatedAt')}), flush=True)


if __name__ == '__main__':
    main()
