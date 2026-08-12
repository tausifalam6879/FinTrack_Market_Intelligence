import unittest
from unittest.mock import Mock, patch

from company_catalog import _clean_query, search_companies


class CompanyCatalogTests(unittest.TestCase):
    def test_search_returns_only_unique_equities(self):
        response = Mock()
        response.quotes = [
            {
                "symbol": "EXAMPLE.NS",
                "quoteType": "EQUITY",
                "longname": "Example Industries Limited",
                "exchDisp": "NSE",
                "sectorDisp": "Industrials",
            },
            {"symbol": "^EXAMPLE", "quoteType": "INDEX", "shortname": "Example Index"},
            {"symbol": "EXAMPLE.NS", "quoteType": "EQUITY", "shortname": "Duplicate"},
        ]

        with patch("company_catalog.yf.Search", return_value=response):
            result = search_companies("Example Industries", 8)

        self.assertEqual("live", result["mode"])
        self.assertEqual(1, result["count"])
        self.assertEqual("EXAMPLE.NS", result["items"][0]["symbol"])
        self.assertEqual("Example Industries Limited", result["items"][0]["name"])

    def test_provider_failure_uses_verified_board_fallback(self):
        with patch("company_catalog.yf.Search", side_effect=RuntimeError("offline")):
            result = search_companies("Reliance", 5)

        self.assertEqual("fallback", result["mode"])
        self.assertEqual("RELIANCE.NS", result["items"][0]["symbol"])

    def test_name_search_prefers_indian_listing_without_overriding_exact_ticker(self):
        response = Mock()
        response.quotes = [
            {"symbol": "INFY", "quoteType": "EQUITY", "longname": "Infosys Limited", "exchDisp": "NYSE"},
            {"symbol": "INFY.NS", "quoteType": "EQUITY", "longname": "Infosys Limited", "exchDisp": "NSE"},
        ]

        with patch("company_catalog.yf.Search", return_value=response):
            by_name = search_companies("Infosys", 5)
        self.assertEqual("INFY.NS", by_name["items"][0]["symbol"])

        with patch("company_catalog.yf.Search", return_value=response):
            by_ticker = search_companies("INFY", 5)
        self.assertEqual("INFY", by_ticker["items"][0]["symbol"])

    def test_query_is_normalized_and_validated(self):
        self.assertEqual("Tata Motors", _clean_query("  Tata   Motors  "))
        with self.assertRaises(ValueError):
            _clean_query("A")

    def test_wrong_nse_suffix_retries_as_company_name(self):
        empty = Mock()
        empty.quotes = []
        cisco = Mock()
        cisco.quotes = [{
            "symbol": "CSCO",
            "quoteType": "EQUITY",
            "longname": "Cisco Systems, Inc.",
            "exchDisp": "NASDAQ",
        }]
        with patch("company_catalog.yf.Search", side_effect=[empty, cisco]) as provider:
            result = search_companies("CISCO.NS", 5)

        self.assertEqual(2, provider.call_count)
        self.assertTrue(result["correctionApplied"])
        self.assertEqual("CISCO", result["resolvedQuery"])
        self.assertEqual("CSCO", result["items"][0]["symbol"])


if __name__ == "__main__":
    unittest.main()
