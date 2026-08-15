import unittest
from datetime import date

import pandas as pd

from market_intelligence import _corporate_action_intelligence


class CorporateActionIntelligenceTests(unittest.TestCase):
    def test_normalizes_dividend_totals_completed_year_cagr_and_split_ratio(self):
        dividends = pd.Series(
            [1.0, 1.0, 1.1, 1.1, 1.2, 1.2, 0.65, 0.65],
            index=pd.to_datetime([
                "2023-03-01", "2023-09-01", "2024-03-01", "2024-09-01",
                "2025-03-01", "2025-09-01", "2026-03-01", "2026-08-01",
            ], utc=True),
        )
        splits = pd.Series([1.5], index=pd.to_datetime(["2025-01-15"], utc=True))
        info = {
            "currency": "USD", "quoteType": "EQUITY", "dividendYield": 2.4,
            "trailingAnnualDividendYield": 0.024, "payoutRatio": 0.45,
        }

        result = _corporate_action_intelligence(
            info, dividends, splits, None,
            [{"type": "ex-dividend", "date": "2026-11-01", "status": "upcoming"}],
            today=date(2026, 8, 14),
        )

        self.assertEqual("available", result["status"])
        self.assertEqual("broad", result["coverageLevel"])
        self.assertEqual(2.4, result["snapshot"]["currentYieldPercent"])
        self.assertEqual(45.0, result["snapshot"]["payoutRatioPercent"])
        self.assertEqual(2.5, result["summary"]["trailing12MonthTotalPerShare"])
        self.assertEqual(1.3, result["annualDividends"][0]["totalPerShare"])
        self.assertTrue(result["annualDividends"][0]["isPartialYear"])
        self.assertIsNone(result["annualDividends"][0]["changePercent"])
        self.assertAlmostEqual(9.54, result["summary"]["completedYearDividendCagrPercent"], places=2)
        self.assertEqual("3-for-2", result["recentSplits"][0]["displayRatio"])

    def test_split_only_company_is_partial_without_invented_dividend(self):
        splits = pd.Series([5.0, 3.0], index=pd.to_datetime(["2020-08-31", "2022-08-25"], utc=True))
        result = _corporate_action_intelligence(
            {"currency": "USD", "quoteType": "EQUITY", "payoutRatio": 0.0},
            pd.Series(dtype=float), splits, None, today=date(2026, 8, 14),
        )

        self.assertEqual("available", result["status"])
        self.assertEqual("partial", result["coverageLevel"])
        self.assertEqual([], result["annualDividends"])
        self.assertIsNone(result["summary"]["trailing12MonthTotalPerShare"])
        self.assertIsNone(result["snapshot"]["payoutRatioPercent"])
        self.assertEqual("3-for-1", result["summary"]["latestSplitRatio"])

    def test_missing_provider_data_returns_honest_unavailable_state(self):
        result = _corporate_action_intelligence({}, None, None, None, today=date(2026, 8, 14))

        self.assertEqual("unavailable", result["status"])
        self.assertEqual("unavailable", result["coverageLevel"])
        self.assertEqual([], result["recentDividends"])
        self.assertIn("Missing data is not treated as zero", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
