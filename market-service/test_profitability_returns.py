import unittest

import pandas as pd

from market_intelligence import _profitability_returns_intelligence


class ProfitabilityReturnsIntelligenceTests(unittest.TestCase):
    def setUp(self):
        columns = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31"])
        self.income = pd.DataFrame(
            {
                columns[0]: [150.0, 66.0, 24.0, 24.0, 18.0, 24.0, 6.0],
                columns[1]: [120.0, 50.0, 18.0, 18.0, 12.0, 16.0, 4.0],
                columns[2]: [100.0, 40.0, 15.0, 15.0, 10.0, 13.0, 3.0],
            },
            index=[
                "Total Revenue", "Gross Profit", "Operating Income", "EBIT",
                "Net Income", "Pretax Income", "Tax Provision",
            ],
        )
        self.balance = pd.DataFrame(
            {
                columns[0]: [150.0, 75.0, 30.0, 15.0],
                columns[1]: [120.0, 60.0, 25.0, 12.0],
                columns[2]: [100.0, 50.0, 20.0, 10.0],
            },
            index=[
                "Total Assets", "Stockholders Equity", "Total Debt",
                "Cash Cash Equivalents And Short Term Investments",
            ],
        )

    def test_calculates_margins_average_balance_returns_dupont_and_roic(self):
        result = _profitability_returns_intelligence(
            {"currency": "USD", "sector": "Technology", "industry": "Software"},
            self.income,
            self.balance,
        )

        self.assertEqual("available", result["status"])
        self.assertEqual("broad", result["coverageLevel"])
        latest = result["annual"][-1]
        self.assertEqual(44.0, latest["grossMarginPercent"])
        self.assertEqual(16.0, latest["operatingMarginPercent"])
        self.assertEqual(12.0, latest["netMarginPercent"])
        self.assertEqual(25.0, latest["effectiveTaxRatePercent"])
        self.assertEqual(135.0, latest["averageTotalAssets"])
        self.assertEqual(67.5, latest["averageStockholdersEquity"])
        self.assertEqual(13.33, latest["returnOnAssetsPercent"])
        self.assertEqual(26.67, latest["returnOnEquityPercent"])
        self.assertEqual(1.111, latest["assetTurnoverRatio"])
        self.assertEqual(2.0, latest["equityMultiplierRatio"])
        self.assertEqual(18.0, latest["nopat"])
        self.assertEqual(81.5, latest["averageInvestedCapital"])
        self.assertEqual(22.09, latest["returnOnInvestedCapitalPercent"])
        self.assertEqual(1.0, latest["operatingMarginChangePoints"])
        self.assertEqual(4.85, latest["returnOnEquityChangePoints"])
        self.assertIn("average beginning and ending", result["method"])

    def test_financial_company_keeps_roa_roe_but_withholds_industrial_roic(self):
        result = _profitability_returns_intelligence(
            {"sector": "Financial Services", "industry": "Banks - Regional"},
            self.income,
            self.balance,
        )

        latest = result["annual"][-1]
        self.assertTrue(result["financialSectorCaution"])
        self.assertEqual(13.33, latest["returnOnAssetsPercent"])
        self.assertEqual(26.67, latest["returnOnEquityPercent"])
        self.assertIsNone(latest["returnOnInvestedCapitalPercent"])
        self.assertIn("intentionally withheld", result["disclaimer"])

    def test_single_period_reports_margins_without_inventing_average_balance_returns(self):
        period = pd.to_datetime(["2025-03-31"])
        income = pd.DataFrame(
            {period[0]: [200.0, 80.0, 30.0, 20.0]},
            index=["Total Revenue", "Gross Profit", "Operating Income", "Net Income"],
        )
        balance = pd.DataFrame(
            {period[0]: [250.0, 100.0]},
            index=["Total Assets", "Stockholders Equity"],
        )

        result = _profitability_returns_intelligence({}, income, balance)
        latest = result["annual"][0]

        self.assertEqual("partial", result["coverageLevel"])
        self.assertEqual(40.0, latest["grossMarginPercent"])
        self.assertEqual(15.0, latest["operatingMarginPercent"])
        self.assertIsNone(latest["returnOnAssetsPercent"])
        self.assertIsNone(latest["returnOnEquityPercent"])
        self.assertIsNone(latest["returnOnInvestedCapitalPercent"])

    def test_missing_statements_return_honest_unavailable_state(self):
        result = _profitability_returns_intelligence({}, None, None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["annual"])
        self.assertIn("does not estimate", result["disclaimer"])

    def test_skipped_fiscal_year_does_not_create_false_average_balance_return(self):
        columns = pd.to_datetime(["2025-12-31", "2023-12-31"])
        income = pd.DataFrame(
            {columns[0]: [150.0, 18.0], columns[1]: [100.0, 10.0]},
            index=["Total Revenue", "Net Income"],
        )
        balance = pd.DataFrame(
            {columns[0]: [150.0, 75.0], columns[1]: [100.0, 50.0]},
            index=["Total Assets", "Stockholders Equity"],
        )

        result = _profitability_returns_intelligence({}, income, balance)
        latest = result["annual"][-1]

        self.assertFalse(latest["previousBalanceComparable"])
        self.assertIsNone(latest["averageTotalAssets"])
        self.assertIsNone(latest["returnOnAssetsPercent"])
        self.assertIsNone(latest["returnOnEquityPercent"])


if __name__ == "__main__":
    unittest.main()
