import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
import market_intelligence as market


class ExperimentalDirectionTests(unittest.TestCase):
    def setUp(self):
        market.clear_market_cache()

    def test_estimate_is_bounded_and_explicitly_unapproved(self):
        rng = np.random.default_rng(12)
        frame = pd.DataFrame({'Close': 100 * np.cumprod(1 + rng.normal(.0005, .015, 300))},
                             index=pd.bdate_range('2024-01-01', periods=300))
        result = market._experimental_direction(frame)
        self.assertGreaterEqual(result['probabilityUp'], 0)
        self.assertLessEqual(result['probabilityUp'], 100)
        self.assertEqual(result['model']['servingMode'], 'experimental_runtime')
        self.assertEqual(result['model']['quality'], 'unapproved')
        self.assertGreater(result['model']['holdoutRows'], 30)
        self.assertLess(result['model']['trainingRows'], 300 - result['model']['holdoutRows'])

    def test_insufficient_or_single_class_history_does_not_invent_result(self):
        self.assertIsNone(market._experimental_direction(pd.DataFrame({'Close': range(1, 40)})))
        self.assertIsNone(market._experimental_direction(pd.DataFrame({'Close': range(1, 301)})))

    def test_ai_fallback_discloses_experimental_status(self):
        answer = market._verified_tool_answer('outlook', {'name': 'Example'},
                    {'symbol': 'TEST', 'experimental': True, 'probabilityUp': 52}, [], {})
        self.assertIn('Experimental estimate only', answer)
        self.assertIn('not approved', answer)

    def test_news_feed_cache_avoids_repeated_provider_calls(self):
        with patch.object(market, 'market_news', return_value={'articles': [
                {'title': 'Example headline', 'publishedAt': '2026-01-01'}]}) as provider:
            first = market.market_news_feed(20)
            calls = provider.call_count
            second = market.market_news_feed(20)
        self.assertEqual(provider.call_count, calls)
        self.assertEqual(first['generatedAt'], second['generatedAt'])
