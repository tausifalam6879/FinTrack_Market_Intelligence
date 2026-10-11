import unittest
from unittest.mock import patch

import pandas as pd
from fastapi import HTTPException
import market_intelligence as market


class ResearchAvailabilityTests(unittest.TestCase):
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
