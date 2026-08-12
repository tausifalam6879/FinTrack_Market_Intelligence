import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiment_tracking import experiment_comparison, log_training_experiment
from persistence import Database, utc_now


class ExperimentTrackingTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp_directory.name)
        self.database = Database(f"sqlite:///{self.root / 'experiments.db'}")
        self.database.initialize_schema()
        self.artifact = self.root / "model.joblib"
        self.artifact.write_bytes(b"controlled-test-artifact")
        self.deep_artifact = self.root / "model-pytorch.pt"
        self.deep_artifact.write_bytes(b"controlled-pytorch-checkpoint")

    def tearDown(self):
        self.temp_directory.cleanup()

    def _log_actual_run(self):
        tracking_uri = f"sqlite:///{(self.root / 'mlflow.db').resolve().as_posix()}"
        with patch.dict(os.environ, {
            "MLFLOW_TRACKING_URI": tracking_uri,
            "MLFLOW_ARTIFACT_ROOT": (self.root / "mlartifacts").resolve().as_uri(),
            "MLFLOW_EXPERIMENT_NAME": "fintrack-tests",
            "MLFLOW_REQUIRED": "true",
            "GIT_PYTHON_REFRESH": "quiet",
        }):
            metadata = log_training_experiment(
                run_id="fintrack-run-123",
                symbol="TEST.NS",
                model_name="Logistic Regression",
                run_status="candidate",
                dataset_version="dataset-abc",
                training_period={"start": "2025-01-01", "end": "2025-10-31", "rows": 200},
                holdout_period={"start": "2025-11-01", "end": "2025-12-31", "rows": 40},
                holdout_fraction=0.15,
                holdout_metrics={
                    "accuracy": 0.57,
                    "balancedAccuracy": 0.58,
                    "rocAuc": 0.62,
                    "brierScore": 0.24,
                },
                baselines={"training_majority": {"balancedAccuracy": 0.50}},
                quality_gate={"passed": True, "checks": {"test": True}},
                selection={"id": "logistic", "name": "Logistic Regression"},
                validation={"folds": 5, "comparisons": []},
                feature_columns=["return_1", "rsi_14"],
                artifact_path=self.artifact,
                artifact_sha256="a" * 64,
                deep_learning_experiment={
                    "name": "PyTorch MLP",
                    "status": "experimental_not_served",
                    "framework": "PyTorch",
                    "frameworkVersion": "2.test",
                    "device": "cpu",
                    "seed": 42,
                    "architecture": {"hiddenLayers": [32, 16]},
                    "earlyStopping": {"bestEpoch": 12, "epochsTrained": 20},
                    "validationMetrics": {"balancedAccuracy": 0.55},
                    "holdoutMetrics": {
                        "balancedAccuracy": 0.60,
                        "rocAuc": 0.64,
                        "brierScore": 0.23,
                    },
                    "artifactSha256": "b" * 64,
                },
                deep_artifact_path=self.deep_artifact,
            )
        return tracking_uri, metadata

    def test_actual_mlflow_store_contains_params_metrics_tags_and_artifacts(self):
        import mlflow
        from mlflow import MlflowClient

        tracking_uri, metadata = self._log_actual_run()
        client = MlflowClient(tracking_uri=tracking_uri)
        run = client.get_run(metadata["runId"])
        artifacts = client.list_artifacts(metadata["runId"])

        self.assertEqual("logged", metadata["status"])
        self.assertEqual("TEST.NS", run.data.params["symbol"])
        self.assertEqual("fintrack-run-123", run.data.tags["fintrack.model_run_id"])
        self.assertAlmostEqual(0.58, run.data.metrics["holdout_balancedAccuracy"])
        self.assertAlmostEqual(0.60, run.data.metrics["deep_holdout_balancedAccuracy"])
        self.assertTrue(metadata["deepLearningArtifactLogged"])
        self.assertIn("training-summary.json", {item.path for item in artifacts})
        self.assertIn("model", {item.path for item in artifacts})
        self.assertIn("deep-learning", {item.path for item in artifacts})

    def test_public_comparison_marks_mlflow_and_legacy_runs(self):
        tracking = {
            "enabled": True,
            "status": "logged",
            "provider": "MLflow",
            "runId": "mlflow-123",
            "experimentId": "1",
        }
        for index, value in enumerate((tracking, None)):
            self.database.save_model_run({
                "id": f"run-{index}",
                "symbol": "TEST.NS",
                "model_name": "Logistic Regression",
                "artifact_path": str(self.artifact),
                "dataset_version": f"dataset-{index}",
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
                    "qualityGate": {"passed": True},
                    **({"deepLearningExperiment": {
                        "name": "PyTorch MLP",
                        "status": "experimental_not_served",
                        "framework": "PyTorch",
                        "frameworkVersion": "2.test",
                        "device": "cpu",
                        "seed": 42,
                        "architecture": {"hiddenLayers": [32, 16]},
                        "earlyStopping": {"bestEpoch": 12, "epochsTrained": 20},
                        "validationMetrics": {"balancedAccuracy": 0.55},
                        "holdoutMetrics": {
                            "balancedAccuracy": 0.60,
                            "rocAuc": 0.64,
                            "brierScore": 0.23,
                        },
                        "artifactSha256": "b" * 64,
                    }} if value else {}),
                    **({"experimentTracking": value} if value else {}),
                },
                "baselines": {"majority": {"balancedAccuracy": 0.5}},
                "features": ["return_1"],
                "status": "candidate",
                "created_at": f"2026-08-12T00:00:0{index}+00:00",
            })

        comparison = experiment_comparison("TEST.NS", self.database)

        self.assertEqual(2, comparison["count"])
        self.assertEqual(1, comparison["trackedCount"])
        self.assertEqual("legacy-untracked", comparison["runs"][0]["tracking"]["status"])
        self.assertEqual("logged", comparison["runs"][1]["tracking"]["status"])
        self.assertEqual(60.0, comparison["runs"][1]["deepLearningExperiment"]["holdoutBalancedAccuracy"])
        self.assertEqual(2.0, comparison["runs"][1]["deepLearningExperiment"]["balancedAccuracyDeltaVsClassical"])


if __name__ == "__main__":
    unittest.main()
