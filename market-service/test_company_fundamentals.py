import unittest

from market_intelligence import _company_financial_sections, _fifty_two_week_position


class CompanyFundamentalNormalizationTests(unittest.TestCase):
    def test_financial_sections_preserve_units_and_missing_values(self):
        result = _company_financial_sections({
            "marketCap": 1_000_000,
            "enterpriseValue": 1_200_000,
            "trailingPE": 20,
            "returnOnEquity": 0.145,
            "profitMargins": 0.21,
            "revenueGrowth": 0.085,
            "debtToEquity": 78.4,
            "freeCashflow": 250_000,
            "dividendYield": 0.35,
            "payoutRatio": 0.12,
        })

        self.assertEqual(14.5, result["profitability"]["returnOnEquityPercent"])
        self.assertEqual(21.0, result["profitability"]["profitMarginPercent"])
        self.assertEqual(8.5, result["growth"]["revenueGrowthPercent"])
        self.assertEqual(0.35, result["shareholderReturns"]["dividendYieldPercent"])
        self.assertEqual(12.0, result["shareholderReturns"]["payoutRatioPercent"])
        self.assertIsNone(result["balanceSheet"]["currentRatio"])

    def test_range_position_is_bounded_and_rejects_invalid_ranges(self):
        self.assertEqual(50.0, _fifty_two_week_position(150, 100, 200))
        self.assertEqual(100.0, _fifty_two_week_position(250, 100, 200))
        self.assertEqual(0.0, _fifty_two_week_position(50, 100, 200))
        self.assertIsNone(_fifty_two_week_position(100, 100, 100))
        self.assertIsNone(_fifty_two_week_position(None, 100, 200))


if __name__ == "__main__":
    unittest.main()
