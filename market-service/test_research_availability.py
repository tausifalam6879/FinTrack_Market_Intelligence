import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
import market_intelligence as market


class ResearchAvailabilityTests(unittest.TestCase):
    def test_missing_prediction_brief_does_not_invent_neutral_probability(self):
        brief = market._build_analysis_brief({"price": 125}, {"predictionAvailable": False})
        self.assertIsNone(brief["probabilityUp"])
        self.assertIsNone(brief["probabilityDown"])
        self.assertNotIn("expectedUpsidePoints", brief)

    def test_company_summary_labels_values_and_preserves_zero_and_negative_returns(self):
        answer = market._verified_tool_answer(
            "Explain fundamentals", {"name": "Example", "currency": "INR"},
            {"symbol": "INFY.NS", "predictionAvailable": False}, [], {},
            company_profile={"fundamentals": {"marketCap": 1000000, "trailingPE": 13.94,
                "earningsGrowth": 0, "dividendYield": None, "returnOnEquity": float("nan")},
                "performance": {"oneMonth": -5.89}},
        )
        self.assertIn("Market capitalization: 1,000,000.00 INR", answer)
        self.assertIn("Trailing price-to-earnings ratio: 13.94×", answer)
        self.assertIn("Reported earnings growth: 0.00%", answer)
        self.assertIn("One month: -5.89%", answer)
        self.assertNotIn("Dividend yield:", answer)
        self.assertNotIn("Return on equity:", answer)
        self.assertNotIn('"fundamentals"', answer)

    def test_evidence_only_answer_includes_company_and_news_without_forecast(self):
        answer = market._verified_tool_answer(
            "Explain this company", {"name": "Example", "price": 125, "currency": "USD", "dataAsOf": "2026-10-11"},
            {"symbol": "AAPL", "predictionAvailable": False}, [], {},
            company_profile={"sector": "Technology", "fundamentals": {"revenue": 100}},
            news_payload={"articles": [{"title": "Example announces results", "publisher": "Example publisher"}]},
        )
        self.assertIn("Technology", answer)
        self.assertIn("Example announces results", answer)
        self.assertIn("Prediction is unavailable", answer)
        self.assertNotIn("50% chance", answer)

    def test_missing_model_keeps_observed_research_without_fake_probability(self):
        frame = pd.DataFrame({"Close": range(100, 220)}, index=pd.date_range("2025-01-01", periods=120))
        missing = HTTPException(503, {"code": "MODEL_UNAVAILABLE", "message": "Offline approval required."})
        with patch.object(market, "market_prediction", side_effect=missing), \
             patch.object(market, "_history", return_value=frame), \
             patch.object(market, "market_snapshot", return_value={"name": "Example", "currency": "USD", "dataAsOf": "2025-04-30"}), \
             patch.object(market, "market_risk_context", return_value={}), \
             patch.object(market, "_persist_research_history", return_value=120) as persist:
            result = market.market_research_analysis("AAPL")
        self.assertFalse(result["predictionAvailable"])
        self.assertIsNone(result["probabilityUp"])
        self.assertIsNone(result["expectedRange"]["low"])
        self.assertEqual(len(result["history"]), 90)
        persist.assert_called_once()

    def test_approved_payload_is_preserved(self):
        payload = {"probabilityUp": 58}
        with patch.object(market, "market_prediction", return_value=payload):
            self.assertIs(market.market_research_analysis("AAPL"), payload)

    def test_other_errors_are_not_hidden(self):
        with patch.object(market, "market_prediction", side_effect=HTTPException(429, "Busy")):
            with self.assertRaises(HTTPException) as raised:
                market.get_market_analysis("AAPL")
        self.assertEqual(raised.exception.status_code, 429)
