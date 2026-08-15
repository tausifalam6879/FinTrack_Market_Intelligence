import unittest

import pandas as pd

from market_intelligence import _liquidity_debt_intelligence


class LiquidityDebtIntelligenceTests(unittest.TestCase):
    def setUp(self):
        columns = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31"])
        self.balance = pd.DataFrame(
            {
                columns[0]: [40.0, 35.0, 28.0, 70.0, 30.0, 40.0, 80.0, 140.0, 60.0],
                columns[1]: [32.0, 30.0, 25.0, 60.0, 28.0, 32.0, 70.0, 120.0, 50.0],
                columns[2]: [25.0, 26.0, 22.0, 52.0, 26.0, 26.0, 60.0, 105.0, 45.0],
            },
            index=[
                "Cash Cash Equivalents And Short Term Investments", "Total Debt", "Net Debt",
                "Current Assets", "Current Liabilities", "Working Capital",
                "Stockholders Equity", "Total Assets", "Total Liabilities Net Minority Interest",
            ],
        )
        self.income = pd.DataFrame(
            {
                columns[0]: [24.0, 30.0, 3.0], columns[1]: [21.0, 27.0, 3.0], columns[2]: [18.0, 24.0, 3.0],
            },
            index=["EBIT", "EBITDA", "Interest Expense Non Operating"],
        )

    def test_calculates_liquidity_leverage_coverage_and_keeps_net_debt_basis_separate(self):
        result = _liquidity_debt_intelligence(
            {"currency": "USD", "sector": "Technology", "industry": "Software"},
            self.income, self.balance,
        )

        self.assertEqual("available", result["status"])
        self.assertEqual("broad", result["coverageLevel"])
        latest = result["annual"][-1]
        self.assertEqual(-5.0, latest["debtAfterLiquidFunds"])
        self.assertEqual("net cash after liquid funds", latest["balancePosition"])
        self.assertEqual(28.0, latest["providerNetDebt"])
        self.assertTrue(latest["providerNetDebtBasisMismatch"])
        self.assertEqual(2.333, latest["currentRatio"])
        self.assertEqual(0.438, latest["totalDebtToEquityRatio"])
        self.assertEqual(25.0, latest["totalDebtToAssetsPercent"])
        self.assertEqual(8.0, latest["interestCoverageRatio"])
        self.assertEqual(1.167, latest["debtToEbitdaRatio"])
        self.assertIn("2025-12-31", result["summary"]["providerNetDebtBasisMismatchPeriods"])

    def test_financial_company_withholds_industrial_coverage_ratios(self):
        result = _liquidity_debt_intelligence(
            {"sector": "Financial Services", "industry": "Banks - Regional"},
            self.income, self.balance,
        )

        latest = result["annual"][-1]
        self.assertTrue(result["financialSectorCaution"])
        self.assertIsNone(latest["interestCoverageRatio"])
        self.assertIsNone(latest["debtToEbitdaRatio"])
        self.assertIn("intentionally withheld", result["disclaimer"])

    def test_cash_only_fallback_is_explicit_and_missing_current_rows_are_not_invented(self):
        columns = pd.to_datetime(["2025-03-31"])
        balance = pd.DataFrame(
            {columns[0]: [12.0, 20.0, 40.0]},
            index=["Cash And Cash Equivalents", "Total Debt", "Total Assets"],
        )
        result = _liquidity_debt_intelligence({}, None, balance)

        latest = result["annual"][0]
        self.assertEqual("cash and cash equivalents only", latest["liquidityBasis"])
        self.assertEqual(8.0, latest["debtAfterLiquidFunds"])
        self.assertIsNone(latest["currentRatio"])
        self.assertIsNone(latest["workingCapital"])

    def test_missing_balance_sheet_returns_honest_unavailable_state(self):
        result = _liquidity_debt_intelligence({}, None, None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["annual"])
        self.assertIn("does not estimate", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
