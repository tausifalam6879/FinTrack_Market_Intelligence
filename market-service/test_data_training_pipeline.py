import tempfile
import unittest
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from data_pipeline import bars_from_frame, dataset_version, validate_ohlcv
from offline_training import train_symbol
from persistence import Database


class DataTrainingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.database = Database(f"sqlite:///{root / 'fintrack-test.db'}")
        self.artifact_dir = root / "artifacts"
        self.database.initialize_schema()

        generator = np.random.default_rng(83)
        rows = 300
        index = pd.bdate_range("2025-01-01", periods=rows)
        signal = np.sin(np.arange(rows) / 9) * 0.003
        returns = signal + generator.normal(0.0005, 0.007, rows)
        close = 100 * np.cumprod(1 + returns)
        opening = close * (1 + generator.normal(0, 0.001, rows))
        self.frame = pd.DataFrame({
            "Open": opening,
            "High": np.maximum(opening, close) * 1.006,
            "Low": np.minimum(opening, close) * 0.994,
            "Close": close,
            "Adj Close": close,
            "Volume": generator.integers(700_000, 1_400_000, rows),
        }, index=index)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_validation_rejects_impossible_rows_and_version_is_deterministic(self):
        damaged = self.frame.iloc[:5].copy()
        damaged.iloc[2, damaged.columns.get_loc("High")] = 1
        clean = validate_ohlcv(damaged)
        self.assertEqual(4, len(clean))

        bars = bars_from_frame("TEST.NS", clean)
        self.assertEqual(dataset_version(bars), dataset_version(reversed(bars)))

    def test_persistence_upserts_bars_without_duplicates(self):
        bars = bars_from_frame("TEST.NS", self.frame.iloc[:20])
        self.database.upsert_company({"symbol": "TEST.NS", "name": "Test Limited", "source": "test"})
        self.assertEqual(20, self.database.upsert_market_bars(bars))
        self.assertEqual(20, self.database.upsert_market_bars(bars))
        self.assertEqual(20, len(self.database.load_market_bars("TEST.NS")))

    def test_offline_training_creates_holdout_metrics_and_versioned_artifact(self):
        self.database.upsert_company({"symbol": "TEST.NS", "name": "Test Limited", "source": "test"})
        self.database.upsert_market_bars(bars_from_frame("TEST.NS", self.frame))

        result = train_symbol("TEST.NS", self.database, self.artifact_dir)

        artifact_path = Path(result["artifactPath"])
        self.assertTrue(artifact_path.exists())
        self.assertGreaterEqual(result["untouchedHoldout"]["rows"], 30)
        self.assertIn("balancedAccuracy", result["untouchedHoldout"])
        self.assertEqual(3, len(result["baselines"]))
        self.assertEqual(64, len(result["artifactSha256"]))
        self.assertIn(result["status"], {"candidate", "rejected"})
        self.assertIn("passed", result["qualityGate"])
        self.assertEqual(1, result["purgeGapRows"])
        deep = result["deepLearningExperiment"]
        self.assertEqual("PyTorch MLP", deep["name"])
        self.assertEqual("experimental_not_served", deep["status"])
        self.assertEqual(1, deep["dataSplit"]["purgeGapRows"])
        self.assertIn("balancedAccuracy", deep["holdoutMetrics"])
        self.assertEqual(64, len(deep["artifactSha256"]))
        self.assertEqual(1, len(list(self.artifact_dir.glob("*-pytorch-mlp.pt"))))
        self.assertIsNotNone(self.database.latest_model_run("TEST.NS"))

        trusted_artifact = joblib.load(artifact_path)
        self.assertEqual("TEST.NS", trusted_artifact["symbol"])
        self.assertEqual(result["modelRunId"], trusted_artifact["modelRunId"])
        self.assertEqual(set(trusted_artifact["featureColumns"]), set(trusted_artifact["explainabilityReference"]))
        self.assertEqual(
            len(trusted_artifact["featureColumns"]),
            len(self.database.feature_baselines(result["modelRunId"])),
        )


if __name__ == "__main__":
    unittest.main()
