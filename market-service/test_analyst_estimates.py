import unittest

import pandas as pd

from market_intelligence import _analyst_estimate_intelligence


class AnalystEstimateIntelligenceTests(unittest.TestCase):
    def test_normalizes_estimate_ranges_revision_breadth_and_trend_history(self):
        earnings = pd.DataFrame({
            "avg": [1.25, 5.0], "low": [1.1, 4.6], "high": [1.4, 5.4],
            "yearAgoEps": [1.0, 4.4], "numberOfAnalysts": [12, 18],
            "growth": [0.25, 0.1364],
        }, index=["0q", "+1y"])
        revenue = pd.DataFrame({
            "avg": [12_000_000_000, 55_000_000_000],
            "low": [11_500_000_000, 50_000_000_000],
            "high": [12_500_000_000, 60_000_000_000],
            "yearAgoRevenue": [10_000_000_000, 48_000_000_000],
            "numberOfAnalysts": [10, 16], "growth": [0.2, 0.1458],
        }, index=["0q", "+1y"])
        revisions = pd.DataFrame({
            "upLast7days": [3, 1], "downLast7Days": [1, 2],
            "upLast30days": [8, 2], "downLast30days": [2, 5],
        }, index=["0q", "+1y"])
        trend = pd.DataFrame({
            "current": [1.25, 3.0], "7daysAgo": [1.23, 3.1],
            "30daysAgo": [1.2, 3.2], "60daysAgo": [1.18, 3.25],
            "90daysAgo": [1.15, 3.3],
        }, index=["0q", "+1y"])
        growth = pd.DataFrame({
            "stockTrend": [0.25, 0.1364], "indexTrend": [0.18, 0.12],
        }, index=["0q", "+1y"])

        result = _analyst_estimate_intelligence(earnings, revenue, revisions, trend, growth)

        self.assertEqual("available", result["status"])
        self.assertEqual("broad", result["coverageLevel"])
        current = result["periods"][0]
        self.assertEqual("Current quarter", current["label"])
        self.assertEqual(1.25, current["eps"]["average"])
        self.assertEqual(25.0, current["eps"]["growthPercent"])
        self.assertEqual(6, current["revisionCounts"]["netLast30Days"])
        self.assertEqual("net upward", current["revisionCounts"]["signal"])
        self.assertEqual(0.05, current["epsTrend"]["change30Days"])
        self.assertTrue(current["epsTrend"]["matchesPublishedAverageBasis"])
        self.assertEqual(["+1y"], result["summary"]["periodsWithBasisMismatch"])

    def test_partial_estimates_are_kept_without_inventing_missing_revisions(self):
        earnings = pd.DataFrame({
            "avg": [2.0], "low": [1.8], "high": [2.2],
            "yearAgoEps": [1.7], "numberOfAnalysts": [4], "growth": [0.1765],
        }, index=["0q"])

        result = _analyst_estimate_intelligence(earnings, None, None, None, None)

        self.assertEqual("available", result["status"])
        self.assertEqual("partial", result["coverageLevel"])
        self.assertEqual(2.0, result["summary"]["currentQuarterEpsAverage"])
        self.assertIsNone(result["summary"]["currentQuarterRevenueAverage"])
        self.assertEqual("unavailable", result["summary"]["currentQuarterRevisionSignal"])
        self.assertFalse(result["coverage"]["epsRevisionCounts"])

    def test_missing_provider_estimates_return_honest_unavailable_state(self):
        result = _analyst_estimate_intelligence(None, None, None, None, None)

        self.assertEqual("unavailable", result["status"])
        self.assertEqual([], result["periods"])
        self.assertEqual({}, result["summary"])
        self.assertIn("does not create estimates", result["disclaimer"])


if __name__ == "__main__":
    unittest.main()
