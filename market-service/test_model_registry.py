import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import joblib

from model_registry import approve_model, approved_model, monitoring_snapshot, record_prediction
from persistence import Database, utc_now


class ModelRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        root = Path(self.temp_directory.name)
        self.artifact_dir = root / "artifacts"
        self.artifact_dir.mkdir()
        self.database = Database(f"sqlite:///{root / 'registry.db'}")
        self.database.initialize_schema()

    def tearDown(self):
        self.temp_directory.cleanup()

    def _candidate_run(self, run_id="run-approved-test", status="candidate", gate_passed=True):
        artifact_path = self.artifact_dir / f"{run_id}.joblib"
        artifact = {
            "estimator": "trusted-test-estimator",
            "symbol": "TEST.NS",
            "modelRunId": run_id,
            "datasetVersion": "dataset-123",
            "featureColumns": ["return_1"],
        }
        joblib.dump(artifact, artifact_path)
        checksum = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        self.database.save_model_run({
            "id": run_id,
            "symbol": "TEST.NS",
            "model_name": "Logistic Regression",
            "artifact_path": str(artifact_path),
            "dataset_version": "dataset-123",
            "training_start": "2025-01-01",
            "training_end": "2025-10-31",
            "training_rows": 200,
            "holdout_start": "2025-11-01",
            "holdout_end": "2025-12-31",
            "holdout_rows": 40,
            "balanced_accuracy": 0.58,
            "roc_auc": 0.62,
            "brier_score": 0.24,
            "metrics": {
                "accuracy": 0.57,
                "precision": 0.56,
                "recall": 0.55,
                "f1": 0.55,
                "artifactSha256": checksum,
                "qualityGate": {"passed": gate_passed},
            },
            "baselines": {"majority": {"balancedAccuracy": 0.5}},
            "features": ["return_1"],
            "status": status,
            "created_at": utc_now(),
        })
        return run_id

    def test_candidate_is_verified_and_approved(self):
        run_id = self._candidate_run()
        result = approve_model(run_id, self.database, self.artifact_dir)
        loaded = approved_model("TEST.NS", self.database, self.artifact_dir)

        self.assertEqual("approved", result["status"])
        self.assertEqual(run_id, loaded["artifact"]["modelRunId"])
        self.assertEqual("approved", self.database.model_run(run_id)["status"])

    def test_failed_quality_gate_cannot_be_approved(self):
        run_id = self._candidate_run("run-rejected-test", gate_passed=False)
        with self.assertRaises(ValueError):
            approve_model(run_id, self.database, self.artifact_dir)
        self.assertEqual("candidate", self.database.model_run(run_id)["status"])

    def test_prediction_is_persisted_and_older_row_is_evaluated(self):
        def payload(date, close, outlook):
            return {
                "symbol": "TEST.NS",
                "modelDataDate": date,
                "generatedAt": utc_now(),
                "probabilityUp": 62.0,
                "outlook": outlook,
                "lastClose": close,
                "expectedRange": {"low": close * 0.98, "high": close * 1.02},
                "model": {"modelRunId": None},
            }

        record_prediction(payload("2026-08-10", 100, "BULLISH"), self.database)
        record_prediction(payload("2026-08-11", 102, "NEUTRAL"), self.database)
        snapshot = monitoring_snapshot("TEST.NS", self.database)

        self.assertEqual(2, snapshot["predictionMonitoring"]["totalStored"])
        self.assertEqual(1, snapshot["predictionMonitoring"]["evaluated"])
        self.assertEqual(100.0, snapshot["predictionMonitoring"]["observedAccuracy"])


if __name__ == "__main__":
    unittest.main()
