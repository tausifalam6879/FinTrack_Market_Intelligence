import unittest

import pandas as pd

from market_intelligence import _earnings_quality_intelligence, _financial_statement_trends


class EarningsQualityIntelligenceTests(unittest.TestCase):
    def setUp(self):
        columns = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31"])
        self.income = pd.DataFrame(
            {
                columns[0]: [100.0, 20.0], columns[1]: [90.0, 18.0], columns[2]: [80.0, 16.0],
            },
            index=["Total Revenue", "Net Income"],
        )
        self.cash = pd.DataFrame(
            {
                columns[0]: [30.0, 24.0, -6.0, -5.0, -4.0, 1.0, -8.0, 10.0, 2.0, -3.0],
                columns[1]: [24.0, 19.0, -5.0, -4.0, -3.0, 1.0, -7.0, 8.0, 1.0, -2.0],
                columns[2]: [20.0, 16.0, -4.0, -3.0, -2.0, 1.0, -6.0, 7.0, 1.0, -1.0],
            },
            index=[
                "Operating Cash Flow", "Free Cash Flow", "Capital Expenditure",
                "Cash Dividends Paid", "Repurchase Of Capital Stock", "Issuance Of Capital Stock",
                "Repayment Of Debt", "Issuance Of Debt", "Net Issuance Payments Of Debt",
                "Net Common Stock Issuance",
            ],
        )

    def test_aligns_cash_conversion_and_capital_allocation_without_composite_score(self):
        trends = _financial_statement_trends(self.income, None, self.cash, None)
        result = _earnings_quality_intelligence(
            {"currency": "USD", "sector": "Technology", "industry": "Networking"},
            trends, self.cash,
        )

        self.assertEqual("available", result["status"])
        self.assertEqual("broad", result["coverageLevel"])
        latest = result["annual"][-1]
        self.assertEqual("2025-12-31", latest["period"])
        self.assertEqual(150.0, latest["operatingCashConversionPercent"])
        self.assertEqual(120.0, latest["freeCashFlowConversionPercent"])
        self.assertEqual(9.0, latest["shareholderCashReturns"])
        self.assertEqual(37.5, latest["shareholderReturnsToFreeCashFlowPercent"])
        self.assertEqual(15.0, latest["freeCashFlowAfterShareholderReturns"])
        self.assertEqual(20.0, latest["capitalExpenditureToOperatingCashFlowPercent"])
        self.assertNotIn("score", result["summary"])
        self.assertFalse(result["financialSectorCaution"])

    def test_non_positive_income_keeps_conversion_unavailable_and_flags_bank_context(self):
        columns = pd.to_datetime(["2025-03-31"])
        income = pd.DataFrame({columns[0]: [100.0, -4.0]}, index=["Total Revenue", "Net Income"])
        cash = pd.DataFrame(
            {columns[0]: [12.0, 8.0, -4.0, -20.0, 25.0]},
            index=["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure", "Repayment Of Debt", "Issuance Of Debt"],
        )
        trends = _financial_statement_trends(income, None, cash, None)
        result = _earnings_quality_intelligence(
            {"sector": "Financial Services", "industry": "Banks - Regional"}, trends, cash,
        )

        self.assertIsNone(result["annual"][0]["operatingCashConversionPercent"])
        self.assertIn("non-positive", result["annual"][0]["conversionBasis"])
        self.assertTrue(result["financialSectorCaution"])
        self.assertIn("not directly comparable", result["disclaimer"])

    def test_positive_reversal_in_outflow_row_is_not_reclassified_as_spending(self):
        columns = pd.to_datetime(["2025-12-31"])
        income = pd.DataFrame({columns[0]: [50.0, 5.0]}, index=["Total Revenue", "Net Income"])
        cash = pd.DataFrame(
            {columns[0]: [7.0, 6.0, -1.0, 2.0]},
            index=["Operating Cash Flow", "Free Cash Flow", "Capital Expenditure", "Cash Dividends Paid"],
        )
        trends = _financial_statement_trends(income, None, cash, None)
        result = _earnings_quality_intelligence({}, trends, cash)

        self.assertIsNone(result["annual"][0]["dividendsPaid"])
        self.assertIsNone(result["annual"][0]["shareholderCashReturns"])

    def test_missing_statements_return_honest_unavailable_state(self):
        result = _earnings_quality_intelligence({}, {"annual": []}, None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["annual"])
        self.assertIn("does not estimate", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
