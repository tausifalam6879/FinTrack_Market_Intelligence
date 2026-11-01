import time
import unittest
from unittest.mock import Mock, patch

import market_intelligence as market


class ProfileRecoveryTests(unittest.TestCase):
    def setUp(self):
        market.clear_market_cache()

    def tearDown(self):
        market.clear_market_cache()

    def test_provider_error_recovers_exact_listing_metadata_only(self):
        ticker = Mock()
        ticker.get_info.side_effect = RuntimeError('provider unavailable')
        search = Mock(quotes=[{'symbol': 'AAPL', 'sectorDisp': 'Technology',
                              'industryDisp': 'Consumer Electronics', 'longName': 'Apple',
                              'trailingPE': 999}])
        with patch.object(market.yf, 'Search', return_value=search):
            info, evidence = market._company_profile('AAPL', ticker)
        self.assertEqual('Technology', info['sector'])
        self.assertNotIn('trailingPE', info)
        self.assertTrue(evidence['fallbackUsed'])

    def test_similar_company_is_never_used_as_selected_company(self):
        ticker = Mock()
        ticker.get_info.return_value = {}
        with patch.object(market.yf, 'Search', return_value=Mock(quotes=[
                {'symbol': 'OTHER', 'sector': 'Technology'}])):
            info, evidence = market._company_profile('NEWCO', ticker)
        self.assertNotIn('sector', info)
        self.assertFalse(evidence['classificationAvailable'])

    def test_metadata_cache_does_not_restore_old_financial_numbers(self):
        ticker = Mock()
        ticker.get_info.return_value = {'symbol': 'AAPL', 'sector': 'Technology', 'trailingPE': 20}
        market._company_profile('AAPL', ticker)
        ticker.get_info.return_value = {'trailingPE': 22}
        with patch.object(market.yf, 'Search') as search:
            info, evidence = market._company_profile('AAPL', ticker)
        self.assertEqual(22, info['trailingPE'])
        self.assertEqual('Technology', info['sector'])
        self.assertTrue(evidence['fallbackUsed'])
        search.assert_not_called()
        ticker.get_info.return_value = {}
        info, _ = market._company_profile('AAPL', ticker)
        self.assertNotIn('trailingPE', info)

    def test_complete_profile_does_not_add_search_latency(self):
        ticker = Mock()
        ticker.get_info.return_value = {'sector': 'Technology'}
        with patch.object(market.yf, 'Search') as search:
            _, evidence = market._company_profile('AAPL', ticker)
        search.assert_not_called()
        self.assertFalse(evidence['fallbackUsed'])

    def test_unavailable_peer_results_retry_after_thirty_seconds(self):
        market._cache_put('sector-peers:AAPL', {'status': 'unavailable'})
        market._cache['sector-peers:AAPL']['created_at'] = time.time() - 31
        with patch.object(market, '_company_profile', return_value=({}, {})) as profile:
            result = market.sector_peer_intelligence('AAPL')
        profile.assert_called_once()
        self.assertEqual('unavailable', result['status'])
        self.assertIn('could not be retrieved', result['message'])


if __name__ == '__main__':
    unittest.main()
