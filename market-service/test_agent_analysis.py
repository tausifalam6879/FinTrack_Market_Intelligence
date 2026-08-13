import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from market_intelligence import (
    _build_analysis_brief,
    _extract_requested_date,
    _historical_session,
    _infer_symbol,
    _llm_grounding_issue,
    _verified_tool_answer,
)


class AgentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "price": 24774.30,
            "changePercent": 1.67,
        }
        self.prediction = {
            "name": "Nifty 50",
            "outlook": "NEUTRAL",
            "probabilityUp": 53.3,
            "probabilityDown": 46.7,
            "dataAsOf": "2026-08-03T10:00:00+00:00",
            "expectedRange": {
                "low": 24508.78,
                "high": 25039.82,
                "currency": "INR",
            },
            "newsFactor": {
                "sentimentLabel": "mixed/neutral",
            },
            "model": {
                "balancedAccuracy": 51.6,
                "walkForwardFolds": 5,
                "quality": "weak",
            },
            "riskBenchmark": {
                "status": "available",
                "asset": {
                    "periodReturnPercent": 12.4,
                    "annualizedVolatilityPercent": 18.25,
                    "maxDrawdownPercent": -11.6,
                    "historicalVar95Percent": 1.72,
                },
                "benchmark": {"symbol": "^NSEI", "name": "Nifty 50"},
                "comparison": {
                    "relativeReturnPoints": 3.4,
                    "beta": 0.91,
                    "correlation": 0.76,
                    "trackingErrorPercent": 9.8,
                },
            },
        }

    def test_extracts_common_historical_date_formats(self):
        self.assertEqual(date(2026, 7, 15), _extract_requested_date("15 July 2026 ko Nifty kaisa tha?"))
        self.assertEqual(date(2026, 7, 15), _extract_requested_date("Nifty on 2026-07-15"))
        self.assertEqual(date(2026, 7, 15), _extract_requested_date("15/07/2026 market behaviour"))

    def test_explicitly_selected_company_is_not_replaced_by_benchmark_words(self):
        self.assertEqual(
            "RELIANCE.NS",
            _infer_symbol("Reliance ka beta Nifty benchmark ke against batao", "RELIANCE.NS"),
        )
        self.assertEqual("^NSEI", _infer_symbol("Nifty ka outlook", None))

    def test_historical_session_returns_transparent_arithmetic(self):
        frame = pd.DataFrame(
            {
                "Open": [99.0, 102.0, 104.0],
                "High": [102.0, 107.0, 106.0],
                "Low": [98.0, 101.0, 102.0],
                "Close": [101.0, 105.0, 103.0],
                "Volume": [1000, 1200, 1100],
            },
            index=pd.to_datetime(["2026-07-14", "2026-07-15", "2026-07-16"]),
        )
        with patch("market_intelligence._history", return_value=frame):
            result = _historical_session("^NSEI", date(2026, 7, 15))

        self.assertTrue(result["exactSession"])
        self.assertEqual("2026-07-15", result["sessionDate"])
        self.assertEqual(105.0, result["close"])
        self.assertAlmostEqual(3.96, result["changePercent"], places=2)
        self.assertEqual("2026-07-16", result["nextSession"]["date"])
        self.assertAlmostEqual(-1.90, result["nextSession"]["changePercent"], places=2)

    def test_analysis_brief_precalculates_range_scenarios(self):
        brief = _build_analysis_brief(self.snapshot, self.prediction)

        self.assertEqual(53.3, brief["probabilityUp"])
        self.assertEqual(46.7, brief["probabilityDown"])
        self.assertEqual(3.3, brief["distanceFromNeutralPoints"])
        self.assertAlmostEqual(-1.07, brief["expectedDownsidePercent"], places=2)
        self.assertAlmostEqual(1.07, brief["expectedUpsidePercent"], places=2)
        self.assertFalse(brief["modelHasReliableDirectionalEdge"])

    def test_verified_fallback_contains_analysis_sections_and_warning(self):
        answer = _verified_tool_answer(
            "Nifty ka scenario aur calculation samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction"],
            {"factors": []},
        )

        for heading in (
            "Seedha jawab",
            "Verified figures",
            "Calculation aur scenario",
            "Assumptions aur confidence",
            "Final assessment",
        ):
            self.assertIn(heading, answer)
        self.assertIn("reliable directional edge nahi", answer)
        self.assertIn("53.3%", answer)
        self.assertIn("personalized buy/sell advice", answer)

    def test_verified_fallback_answers_risk_question_from_calculated_evidence(self):
        answer = _verified_tool_answer(
            "Nifty ka beta, drawdown aur historical VaR risk samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction"],
            {"factors": []},
        )

        self.assertIn("Historical risk and benchmark evidence", answer)
        self.assertIn("annualized volatility 18.25%", answer)
        self.assertIn("Maximum drawdown -11.6%", answer)
        self.assertIn("beta 0.91", answer)
        self.assertIn("future loss limit", answer)

    def test_generated_risk_answer_must_include_the_specifically_requested_beta(self):
        base_answer = (
            "Weak model warning. Annualized volatility is 18.25 percent and the Nifty 50 is the benchmark. "
            + ("Evidence-based explanation. " * 12)
        )
        issue = _llm_grounding_issue(
            base_answer,
            "Nifty benchmark risk aur beta samjhao",
            self.prediction,
            {"factors": []},
        )
        accepted = _llm_grounding_issue(
            base_answer + " Calculated beta is 0.91.",
            "Nifty benchmark risk aur beta samjhao",
            self.prediction,
            {"factors": []},
        )

        self.assertEqual("missing requested beta evidence", issue)
        self.assertIsNone(accepted)


if __name__ == "__main__":
    unittest.main()
