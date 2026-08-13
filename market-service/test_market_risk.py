import unittest

import numpy as np
import pandas as pd

from market_intelligence import _benchmark_for_symbol, calculate_market_risk_context


class MarketRiskTests(unittest.TestCase):
    @staticmethod
    def _frame(daily_returns: np.ndarray) -> pd.DataFrame:
        index = pd.bdate_range("2025-08-01", periods=len(daily_returns) + 1)
        close = 100 * np.cumprod(np.concatenate(([1.0], 1 + daily_returns)))
        return pd.DataFrame({"Close": close}, index=index)

    def test_exchange_suffix_selects_broad_benchmark_without_company_allowlist(self):
        self.assertEqual("^NSEI", _benchmark_for_symbol("ANYSYMBOL.NS"))
        self.assertEqual("^BSESN", _benchmark_for_symbol("500325.BO"))
        self.assertEqual("^FTSE", _benchmark_for_symbol("RANDOM.L"))
        self.assertEqual("^N225", _benchmark_for_symbol("7203.T"))
        self.assertEqual("^GSPC", _benchmark_for_symbol("UNLISTEDUS"))
        self.assertIsNone(_benchmark_for_symbol("^NSEI"))

    def test_risk_context_calculates_aligned_relative_metrics_and_chart(self):
        benchmark_returns = np.array([
            0.002 if index % 5 else -0.003 for index in range(260)
        ], dtype=float)
        asset_returns = (benchmark_returns * 1.25) + np.array([
            0.0008 if index % 3 else -0.0004 for index in range(260)
        ], dtype=float)

        result = calculate_market_risk_context(
            "DYNAMIC.NS",
            self._frame(asset_returns),
            benchmark_frame=self._frame(benchmark_returns),
            benchmark_symbol="^NSEI",
        )

        self.assertEqual("available", result["status"])
        self.assertEqual("Nifty 50", result["benchmark"]["name"])
        self.assertEqual(252, result["asset"]["observations"])
        self.assertGreater(result["comparison"]["beta"], 1.0)
        self.assertGreater(result["comparison"]["correlation"], 0.9)
        self.assertGreater(result["asset"]["annualizedVolatilityPercent"], 0)
        self.assertLessEqual(result["asset"]["maxDrawdownPercent"], 0)
        self.assertGreaterEqual(result["asset"]["historicalVar95Percent"], 0)
        self.assertEqual(90, len(result["normalizedHistory"]))
        self.assertTrue(all(point["benchmark"] is not None for point in result["normalizedHistory"]))

    def test_index_gets_standalone_risk_without_fake_self_comparison(self):
        returns = np.array([0.001 if index % 4 else -0.002 for index in range(80)])
        result = calculate_market_risk_context("^NSEI", self._frame(returns))

        self.assertEqual("standalone", result["status"])
        self.assertIsNone(result["benchmark"])
        self.assertIsNone(result["comparison"])
        self.assertTrue(all(point["benchmark"] is None for point in result["normalizedHistory"]))


if __name__ == "__main__":
    unittest.main()
