import unittest
from datetime import date

import pandas as pd

from market_intelligence import (
    _company_catalysts,
    _company_currency,
    _company_financial_sections,
    _fifty_two_week_position,
)


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

    def test_dynamic_company_uses_provider_iso_currency_instead_of_board_label(self):
        self.assertEqual("USD", _company_currency(
            {"currency": "USD"}, {"currency": "Local currency"}
        ))
        self.assertEqual("JPY", _company_currency({}, {"currency": "JPY"}))
        self.assertEqual("Local currency", _company_currency(
            {}, {"currency": "Local currency"}
        ))
        self.assertEqual("GBp", _company_currency(
            {"currency": "GBp"}, {"currency": "Local currency"}
        ))

    def test_catalysts_keep_analyst_targets_separate_from_reported_surprises(self):
        earnings = pd.DataFrame(
            {
                "EPS Estimate": [2.0, 1.8, 1.7],
                "Reported EPS": [None, 1.9, 1.6],
                "Surprise(%)": [None, 5.56, -5.88],
            },
            index=pd.to_datetime(["2026-10-30", "2026-07-30", "2026-04-30"]),
        )
        result = _company_catalysts(
            {
                "targetLowPrice": 90,
                "targetMeanPrice": 120,
                "targetMedianPrice": 118,
                "targetHighPrice": 140,
                "recommendationMean": 2.1,
                "recommendationKey": "buy",
                "numberOfAnalystOpinions": 12,
            },
            {
                "Earnings Date": [date(2026, 10, 30)],
                "Ex-Dividend Date": date(2026, 8, 10),
                "Earnings Average": 2.0,
                "Revenue Average": 5_000_000,
            },
            earnings,
            100,
            today=date(2026, 8, 14),
        )

        self.assertEqual("available", result["status"])
        self.assertEqual(20.0, result["analystConsensus"]["targetGapPercent"])
        self.assertEqual("Buy", result["analystConsensus"]["recommendation"])
        self.assertEqual(1, result["surpriseSummary"]["beats"])
        self.assertEqual(1, result["surpriseSummary"]["misses"])
        self.assertEqual("upcoming", result["events"][0]["status"])
        self.assertEqual("2026-10-30", result["events"][0]["date"])

    def test_missing_catalyst_evidence_returns_unavailable_without_invention(self):
        result = _company_catalysts({}, {}, None, None, today=date(2026, 8, 14))
        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["events"])
        self.assertEqual(0, result["analystConsensus"]["analystCount"])


if __name__ == "__main__":
    unittest.main()
