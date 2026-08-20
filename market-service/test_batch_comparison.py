import time
import unittest
from unittest.mock import patch

from market_intelligence import MarketComparisonRequest, compare_market_analyses


class BatchComparisonTests(unittest.TestCase):
    @patch("market_intelligence.market_prediction")
    def test_compares_unique_symbols_in_one_parallel_request(self, prediction):
        def result(symbol):
            time.sleep(0.02)
            return {"symbol": symbol, "outlook": "NEUTRAL", "probabilityUp": 50.0}

        prediction.side_effect = result
        response = compare_market_analyses(MarketComparisonRequest(
            symbols=["aapl", "MSFT", "AAPL"], refresh=False,
        ))

        self.assertEqual(["AAPL", "MSFT"], response["symbols"])
        self.assertEqual(["AAPL", "MSFT"], [item["symbol"] for item in response["items"]])
        self.assertFalse(response["partial"])
        self.assertEqual("parallel-fastapi-fallback", response["execution"])

    @patch("market_intelligence.market_prediction")
    def test_partial_failure_keeps_available_comparison_evidence(self, prediction):
        def result(symbol):
            if symbol == "MSFT":
                raise RuntimeError("provider unavailable")
            return {"symbol": symbol, "outlook": "NEUTRAL"}

        prediction.side_effect = result
        response = compare_market_analyses(MarketComparisonRequest(symbols=["AAPL", "MSFT"]))

        self.assertTrue(response["partial"])
        self.assertEqual(["AAPL"], [item["symbol"] for item in response["items"]])
        self.assertEqual("MSFT", response["errors"][0]["symbol"])


if __name__ == "__main__":
    unittest.main()
