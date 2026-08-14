import unittest

import pandas as pd

from market_intelligence import _ownership_intelligence


class OwnershipIntelligenceTests(unittest.TestCase):
    def test_normalizes_major_holders_concentration_and_insider_activity(self):
        major = pd.DataFrame(
            {"Value": [0.05, 0.60, 0.65, 100]},
            index=[
                "insidersPercentHeld", "institutionsPercentHeld",
                "institutionsFloatPercentHeld", "institutionsCount",
            ],
        )
        institutions = pd.DataFrame([
            {"Date Reported": pd.Timestamp("2026-06-30"), "Holder": "Alpha Capital", "pctHeld": 0.10, "Shares": 1000, "Value": 10000, "pctChange": 0.02},
            {"Date Reported": pd.Timestamp("2026-03-31"), "Holder": "Beta Partners", "pctHeld": 0.05, "Shares": 500, "Value": 5000, "pctChange": -0.01},
        ])
        funds = pd.DataFrame([
            {"Date Reported": pd.Timestamp("2026-03-31"), "Holder": "Index Fund", "pctHeld": 0.03, "Shares": 300, "Value": 3000, "pctChange": 0.01},
        ])
        transactions = pd.DataFrame([
            {"Start Date": pd.Timestamp("2026-07-01"), "Insider": "Jane Doe", "Position": "Director", "Text": "Purchase at price 10", "Shares": 200, "Value": 2000, "Ownership": "D"},
            {"Start Date": pd.Timestamp("2026-08-01"), "Insider": "John Doe", "Position": "Officer", "Text": "Sale at price 12", "Shares": 500, "Value": 6000, "Ownership": "D"},
        ])
        purchases = pd.DataFrame([
            {"Insider Purchases Last 6m": "Purchases", "Shares": 200, "Trans": 1},
            {"Insider Purchases Last 6m": "Sales", "Shares": 500, "Trans": 1},
            {"Insider Purchases Last 6m": "Net Shares Purchased (Sold)", "Shares": -300, "Trans": 2},
            {"Insider Purchases Last 6m": "Total Insider Shares Held", "Shares": 10000, "Trans": None},
            {"Insider Purchases Last 6m": "% Net Shares Purchased (Sold)", "Shares": -0.03, "Trans": None},
        ])
        roster = pd.DataFrame([
            {"Name": "John Doe", "Position": "Officer", "Most Recent Transaction": "Sale", "Latest Transaction Date": pd.Timestamp("2026-08-01"), "Shares Owned Directly": 9000},
        ])

        result = _ownership_intelligence(major, institutions, funds, transactions, purchases, roster)

        self.assertEqual("available", result["status"])
        self.assertEqual("broad", result["coverageLevel"])
        self.assertEqual(5.0, result["majorOwnership"]["insidersPercentHeld"])
        self.assertEqual(60.0, result["majorOwnership"]["institutionsPercentHeld"])
        self.assertEqual(100, result["majorOwnership"]["institutionsCount"])
        self.assertEqual(15.0, result["concentration"]["topInstitutionsPercentHeld"])
        self.assertEqual(3.0, result["concentration"]["topFundsPercentHeld"])
        self.assertEqual("net selling", result["insiderSummary"]["netActivity"])
        self.assertEqual(-300.0, result["insiderSummary"]["netSharesPurchased"])
        self.assertEqual(-3.0, result["insiderSummary"]["netSharesPercent"])
        self.assertEqual("2026-08-01", result["latestInsiderTransactionDate"])
        self.assertEqual("sale", result["recentInsiderTransactions"][0]["type"])
        self.assertEqual("purchase", result["recentInsiderTransactions"][1]["type"])

    def test_missing_holder_datasets_return_honest_unavailable_state(self):
        result = _ownership_intelligence(None, None, None, None, None, None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["institutionalHolders"])
        self.assertEqual([], result["recentInsiderTransactions"])
        self.assertIn("does not estimate", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
