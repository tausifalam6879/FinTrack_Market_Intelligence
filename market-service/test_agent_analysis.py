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

    def test_catalyst_fallback_labels_external_target_and_earnings_date(self):
        company = {
            "catalysts": {
                "status": "available",
                "events": [{
                    "type": "earnings", "label": "Earnings release",
                    "date": "2026-11-12", "status": "upcoming",
                }],
                "analystConsensus": {
                    "recommendation": "Buy", "analystCount": 22,
                    "targetMean": 132.59, "targetGapPercent": 18.33,
                },
                "surpriseSummary": {"reportedQuarters": 5, "beats": 5, "misses": 0},
            }
        }
        answer = _verified_tool_answer(
            "Next earnings date aur analyst price target batao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []},
            company_profile=company,
        )

        self.assertIn("2026-11-12", answer)
        self.assertIn("mean target 132.59", answer)
        self.assertIn("FinTrack ML prediction se separate", answer)

    def test_generated_catalyst_answer_must_include_requested_target_and_date(self):
        company = {
            "catalysts": {
                "events": [{"type": "earnings", "date": "2026-11-12"}],
                "analystConsensus": {"targetMean": 132.59},
            }
        }
        base = "Weak model warning with detailed evidence. " * 12
        issue = _llm_grounding_issue(
            base,
            "Next earnings date aur analyst target batao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + " External mean target 132.59 and earnings date 2026-11-12.",
            "Next earnings date aur analyst target batao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )

        self.assertEqual("missing requested analyst target evidence", issue)
        self.assertIsNone(accepted)

    def test_news_fallback_reports_distribution_sources_and_title_only_boundary(self):
        news = {
            "intelligence": {
                "status": "available", "sentimentLabel": "positive", "sentimentScore": 0.22,
                "articleCount": 5, "sourceCount": 3, "coverage": "moderate", "freshness": "fresh",
                "distribution": {"positive": 3, "mixed/neutral": 1, "negative": 1},
                "themes": [{"theme": "Earnings & outlook", "articleCount": 2}],
            },
            "articles": [{
                "title": "Cisco beats earnings expectations", "publisher": "Evidence Wire",
                "publishedAt": "2026-08-14T08:00:00Z", "sentimentLabel": "positive",
            }],
        }
        answer = _verified_tool_answer(
            "Cisco recent news sentiment and themes batao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "market_news"],
            {"factors": []},
            news_payload=news,
        )

        self.assertIn("Company headline intelligence", answer)
        self.assertIn("3 positive, 1 mixed/neutral, 1 negative", answer)
        self.assertIn("5 headlines from 3 publishers", answer)
        self.assertIn("title-keyword evidence", answer)

    def test_generated_news_answer_must_include_grounded_tone_and_requested_theme(self):
        news = {
            "intelligence": {
                "status": "available", "sentimentLabel": "positive",
                "themes": [{"theme": "Earnings & outlook", "articleCount": 3}],
            }
        }
        base = "Weak model warning with detailed evidence and source limitations. " * 10
        issue = _llm_grounding_issue(
            base,
            "Recent news sentiment and theme batao",
            self.prediction,
            {"factors": []},
            news_payload=news,
        )
        accepted = _llm_grounding_issue(
            base + " Headline sentiment is positive and the leading theme is Earnings & outlook.",
            "Recent news sentiment and theme batao",
            self.prediction,
            {"factors": []},
            news_payload=news,
        )

        self.assertEqual("missing requested headline sentiment evidence", issue)
        self.assertIsNone(accepted)


if __name__ == "__main__":
    unittest.main()
