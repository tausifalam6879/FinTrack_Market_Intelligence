import unittest
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from market_intelligence import (
    FEATURE_LABELS,
    _candidate_models,
    _features,
    _local_feature_explanation,
    _prediction_audit,
    _prediction_audit_lock,
    _record_prediction,
    _walk_forward_model_comparison,
    prediction_audit,
)


class PredictionPipelineTests(unittest.TestCase):
    def setUp(self):
        generator = np.random.default_rng(42)
        rows = 280
        index = pd.bdate_range("2025-01-01", periods=rows)
        cyclical_signal = np.sin(np.arange(rows) / 8) * 0.002
        returns = cyclical_signal + generator.normal(0.0004, 0.008, rows)
        close = 100 * np.cumprod(1 + returns)
        self.frame = pd.DataFrame({
            "Open": close * (1 + generator.normal(0, 0.001, rows)),
            "High": close * 1.006,
            "Low": close * 0.994,
            "Close": close,
            "Volume": generator.integers(700_000, 1_400_000, rows),
        }, index=index)

    def test_walk_forward_compares_three_models_without_shuffle(self):
        features = _features(self.frame)
        dataset = features.copy()
        dataset["target"] = (self.frame["Close"].shift(-1) > self.frame["Close"]).astype(int)
        dataset = dataset.iloc[:-1].dropna()

        result = _walk_forward_model_comparison(dataset, list(FEATURE_LABELS))

        self.assertEqual(3, len(result["comparisons"]))
        self.assertGreaterEqual(result["selected"]["folds"], 4)
        self.assertIn(result["selected"]["id"], {
            "logistic_regression", "random_forest", "hist_gradient_boosting",
        })
        for item in result["comparisons"]:
            self.assertGreaterEqual(item["balancedAccuracy"], 0)
            self.assertLessEqual(item["balancedAccuracy"], 1)
            self.assertGreater(item["testRows"], 0)

    def test_prediction_audit_evaluates_previous_session(self):
        symbol = "AUDIT-TEST"
        with _prediction_audit_lock:
            _prediction_audit.pop(symbol, None)

        def payload(close, date, outlook):
            return {
                "symbol": symbol,
                "generatedAt": datetime.now(timezone.utc).isoformat(),
                "outlook": outlook,
                "probabilityUp": 63.0,
                "lastClose": close,
                "expectedRange": {"low": close * 0.98, "high": close * 1.02, "currency": "INR"},
                "model": {"type": "Random Forest"},
            }

        _record_prediction(payload(100, "2026-08-03", "BULLISH"), "2026-08-03")
        _record_prediction(payload(102, "2026-08-04", "NEUTRAL"), "2026-08-04")
        audit = prediction_audit(symbol)

        self.assertEqual(2, len(audit["records"]))
        evaluated = next(item for item in audit["records"] if item["modelDataDate"] == "2026-08-03")
        self.assertEqual("evaluated", evaluated["status"])
        self.assertEqual("UP", evaluated["actualDirection"])
        self.assertTrue(evaluated["correct"])
        self.assertEqual(100.0, audit["observedAccuracy"])

    def test_local_explanation_reports_directional_counterfactual_impacts(self):
        features = _features(self.frame)
        dataset = features.copy()
        dataset["target"] = (self.frame["Close"].shift(-1) > self.frame["Close"]).astype(int)
        dataset = dataset.iloc[:-1].dropna()
        columns = list(FEATURE_LABELS)
        model = _candidate_models()["logistic_regression"]["estimator"]
        model.fit(dataset[columns], dataset["target"])

        explanation = _local_feature_explanation(
            model,
            features.dropna().iloc[-1:],
            dataset,
            columns,
            reliability_weight=0.75,
        )

        self.assertEqual(7, len(explanation["contributions"]))
        self.assertEqual("current two-year model-dataset median", explanation["referenceSource"])
        self.assertIn("probability sensitivity", explanation["method"])
        self.assertTrue(explanation["summary"])
        for contribution in explanation["contributions"]:
            self.assertIn(contribution["direction"], {"supports_up", "supports_down", "neutral"})
            self.assertIn("adjustedProbabilityImpactPoints", contribution)
            self.assertTrue(contribution["currentDisplay"])


if __name__ == "__main__":
    unittest.main()
