import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from drift_monitoring import (
    build_feature_baselines,
    refresh_drift_snapshot,
    retraining_policy,
    rolling_prediction_quality,
)
from persistence import Database, utc_now


class DriftMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(
            f"sqlite:///{Path(self.temporary_directory.name) / 'drift-test.db'}"
        )
        self.database.initialize_schema()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def _store_observations(self, values):
        for index, value in enumerate(values):
            prediction_id = f"TEST.NS:2026-07-{index + 1:02d}:run-1"
            self.database.upsert_prediction({
                "id": prediction_id,
                "symbol": "TEST.NS",
                "model_run_id": "run-1",
                "model_data_date": f"2026-07-{index + 1:02d}",
                "generated_at": utc_now(),
                "probability_up": 55.0,
                "outlook": "NEUTRAL",
                "reference_close": 100 + index,
            })
            self.database.upsert_prediction_features(
                prediction_id,
                "TEST.NS",
                "run-1",
                {"return_1": value, "volume_ratio": value + 1},
            )

    def test_training_baseline_and_shifted_serving_data_create_persistent_high_drift(self):
        generator = np.random.default_rng(42)
        training = pd.DataFrame({
            "return_1": generator.normal(0, 0.01, 240),
            "volume_ratio": generator.normal(1, 0.08, 240),
        })
        baselines = build_feature_baselines(training, training.columns)
        self.database.replace_feature_baselines("run-1", "TEST.NS", baselines)
        self._store_observations(np.linspace(0.12, 0.18, 30))

        snapshot = refresh_drift_snapshot("TEST.NS", "run-1", self.database)
        persisted = self.database.latest_drift_snapshot("TEST.NS", "run-1")

        self.assertEqual("high", snapshot["status"])
        self.assertEqual(30, snapshot["recentObservations"])
        self.assertGreaterEqual(snapshot["maxPsi"], 0.25)
        self.assertEqual(snapshot["id"], persisted["id"])

    def test_policy_never_automatically_retrains(self):
        records = [{
            "evaluated_at": utc_now(),
            "correct": index < 8,
            "actual_direction": "UP" if index % 2 else "DOWN",
            "probability_up": 55.0,
        } for index in range(20)]
        quality = rolling_prediction_quality(records)
        approved = {"training_end": "2026-08-01"}

        policy = retraining_policy(approved, quality, {"status": "high"})

        self.assertEqual("retrain_recommended", policy["decision"])
        self.assertFalse(policy["automaticRetraining"])
        self.assertGreaterEqual(len(policy["reasons"]), 1)


if __name__ == "__main__":
    unittest.main()
