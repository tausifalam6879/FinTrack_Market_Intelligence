import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from fastapi import HTTPException

import market_intelligence as market


class ObservedIndicatorTests(unittest.TestCase):
    def test_rsi_matches_simple_fourteen_session_formula(self):
        close = pd.Series([100, 102, 101, 103, 102, 104, 103, 105, 104, 106, 105, 107, 106, 108, 107])
        result = market._observed_research_indicators(close, 'USD')
        self.assertEqual(result['technicalIndicators']['rsi14'], 66.7)

    def test_monotonic_and_flat_rsi(self):
        for prices, expected in ((range(100, 130), 100), (range(130, 100, -1), 0), ([100] * 30, 50)):
            with self.subTest(expected=expected):
                result = market._observed_research_indicators(pd.Series(prices), 'USD')
                self.assertEqual(result['technicalIndicators']['rsi14'], expected)

    def test_range_matches_observed_volatility(self):
        close = pd.Series([100, 110, 98, 105, 95] * 6)
        result = market._observed_research_indicators(close, 'USD/oz')
        move = max(.005, close.pct_change().tail(20).std() * 1.28)
        self.assertEqual(result['expectedRange']['low'], round(close.iloc[-1] * (1 - move), 2))
        self.assertEqual(result['expectedRange']['high'], round(close.iloc[-1] * (1 + move), 2))
        self.assertEqual(result['expectedRange']['currency'], 'USD/oz')
        self.assertFalse(result['expectedRange']['calibratedConfidenceInterval'])

    def test_short_or_invalid_history_does_not_invent_metrics(self):
        for prices in ([], [100] * 14, [None, np.nan, np.inf, -1, 0]):
            result = market._observed_research_indicators(pd.Series(prices, dtype=float), 'USD')
            self.assertIsNone(result['technicalIndicators']['rsi14'])
            self.assertIsNone(result['expectedRange']['low'])
            self.assertIsNone(result['expectedRange']['high'])

    def test_experimental_response_keeps_observed_metrics(self):
        market.clear_market_cache()
        rng = np.random.default_rng(12)
        frame = pd.DataFrame({'Close': 100 * np.cumprod(1 + rng.normal(.0005, .015, 300))},
                             index=pd.bdate_range('2024-01-01', periods=300))
        missing = HTTPException(503, {'code': 'MODEL_UNAVAILABLE', 'message': 'No approved model'})
        with patch.object(market, 'market_prediction', side_effect=missing), \
             patch.object(market, '_history', return_value=frame), \
             patch.object(market, 'market_snapshot', return_value={'name': 'Example', 'currency': 'USD', 'dataAsOf': '2025-03-01'}), \
             patch.object(market, 'market_risk_context', return_value={}), \
             patch.object(market, '_persist_research_history', return_value=0):
            result = market.market_research_analysis('AAPL')
        self.assertTrue(result['predictionAvailable'])
        self.assertTrue(result['experimental'])
        self.assertIsNotNone(result['technicalIndicators']['rsi14'])
        self.assertLess(result['expectedRange']['low'], result['lastClose'])
        self.assertGreater(result['expectedRange']['high'], result['lastClose'])
        market.clear_market_cache()


if __name__ == '__main__':
    unittest.main()
