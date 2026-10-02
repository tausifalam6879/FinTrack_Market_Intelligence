import unittest
from unittest.mock import MagicMock, patch
import market_intelligence as market


class NewsFallbackTests(unittest.TestCase):
    def setUp(self):
        market.clear_market_cache_prefix('news:')

    def test_empty_primary_uses_rss(self):
        with patch.object(market.yf, 'Ticker') as ticker, patch.object(market, '_rss_news') as rss:
            ticker.return_value.news = []
            rss.return_value = [{'title': 'Company earnings rise', 'link': 'https://example.com/news'}]
            result = market.market_news('AAPL')
            self.assertEqual(len(result['articles']), 1)
            rss.assert_called_once_with('AAPL')

    def test_both_fail_returns_no_invented_articles(self):
        with patch.object(market.yf, 'Ticker', side_effect=RuntimeError('failed')), patch.object(market, '_rss_news', side_effect=ValueError('invalid')):
            self.assertEqual(market.market_news('AAPL')['articles'], [])

    def test_valid_primary_does_not_call_rss(self):
        with patch.object(market.yf, 'Ticker') as ticker, patch.object(market, '_rss_news') as rss:
            ticker.return_value.news = [{'title': 'Company report'}]
            self.assertEqual(len(market.market_news('AAPL')['articles']), 1)
            rss.assert_not_called()

    def test_rss_parses_dates_and_skips_unsafe_links(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'<rss><channel><item><title>Report</title><link>https://example.com/a</link><pubDate>Fri, 02 Oct 2026 10:00:00 GMT</pubDate></item><item><title>Bad</title><link>javascript:alert(1)</link></item></channel></rss>'
        with patch.object(market, 'urlopen', return_value=response):
            items = market._rss_news('AAPL')
            self.assertEqual(len(items), 1)
            self.assertIn('2026-10-02', items[0]['content']['pubDate'])
