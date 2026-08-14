import unittest

import pandas as pd

from market_intelligence import _financial_statement_trends


class FinancialStatementTrendTests(unittest.TestCase):
    def setUp(self):
        annual_columns = pd.to_datetime(["2025-03-31", "2024-03-31", "2023-03-31"])
        self.income = pd.DataFrame(
            {
                annual_columns[0]: [150.0, 18.0, 25.0, 60.0],
                annual_columns[1]: [120.0, 12.0, 18.0, 45.0],
                annual_columns[2]: [100.0, 10.0, 15.0, 38.0],
            },
            index=["Total Revenue", "Net Income", "Operating Income", "Gross Profit"],
        )
        self.balance = pd.DataFrame(
            {
                annual_columns[0]: [45.0, 75.0],
                annual_columns[1]: [48.0, 60.0],
                annual_columns[2]: [50.0, 50.0],
            },
            index=["Total Debt", "Stockholders Equity"],
        )
        self.cash_flow = pd.DataFrame(
            {
                annual_columns[0]: [22.0, 16.0, -6.0],
                annual_columns[1]: [16.0, 11.0, -5.0],
                annual_columns[2]: [12.0, 8.0, -4.0],
            },
            index=["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure"],
        )
        quarterly_columns = pd.to_datetime(["2025-06-30", "2025-03-31", "2024-12-31"])
        self.quarterly = pd.DataFrame(
            {
                quarterly_columns[0]: [42.0, 5.0, 7.0],
                quarterly_columns[1]: [39.0, 4.0, 6.0],
                quarterly_columns[2]: [36.0, 3.5, 5.5],
            },
            index=["Total Revenue", "Net Income", "Operating Income"],
        )

    def test_aligns_periods_and_calculates_growth_margin_cash_flow_and_leverage(self):
        result = _financial_statement_trends(
            self.income,
            self.balance,
            self.cash_flow,
            self.quarterly,
        )

        self.assertEqual("available", result["status"])
        self.assertEqual(["2023-03-31", "2024-03-31", "2025-03-31"], [item["period"] for item in result["annual"]])
        latest = result["annual"][-1]
        self.assertEqual(25.0, latest["revenueYoYPercent"])
        self.assertEqual(50.0, latest["netIncomeYoYPercent"])
        self.assertEqual(16.67, latest["operatingMarginPercent"])
        self.assertEqual(10.67, latest["freeCashFlowMarginPercent"])
        self.assertEqual(0.6, latest["debtToEquityRatio"])
        self.assertEqual(-6.25, latest["debtYoYPercent"])
        self.assertAlmostEqual(22.47, result["summary"]["revenueCagrPercent"], places=1)
        self.assertEqual("growing", result["summary"]["revenueTrend"])
        self.assertEqual("growing", result["summary"]["freeCashFlowTrend"])
        self.assertEqual(1.67, result["summary"]["operatingMarginChangePoints"])
        self.assertEqual(3, result["summary"]["quarterlyPeriodCount"])
        self.assertEqual(7.69, result["quarterly"][-1]["revenueQoQPercent"])

    def test_missing_provider_statements_return_honest_unavailable_state(self):
        result = _financial_statement_trends(None, None, None, None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["annual"])
        self.assertEqual({}, result["summary"])
        self.assertIn("does not estimate", result["disclaimer"])

    def test_skipped_quarter_is_not_mislabeled_as_quarter_over_quarter_growth(self):
        columns = pd.to_datetime(["2025-12-31", "2025-06-30"])
        quarterly = pd.DataFrame(
            {columns[0]: [150.0, 15.0, 20.0], columns[1]: [100.0, 10.0, 14.0]},
            index=["Total Revenue", "Net Income", "Operating Income"],
        )

        result = _financial_statement_trends(None, None, None, quarterly)

        self.assertFalse(result["quarterly"][-1]["previousQuarterComparable"])
        self.assertIsNone(result["quarterly"][-1]["revenueQoQPercent"])
        self.assertIsNone(result["quarterly"][-1]["netIncomeQoQPercent"])


if __name__ == "__main__":
    unittest.main()
