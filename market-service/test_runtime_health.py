import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime_health import initialize_runtime, liveness_report, readiness_report


class RuntimeHealthTests(unittest.TestCase):
    def test_readiness_initializes_sqlite_and_reports_only_sanitized_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_url = f"sqlite:///{root / 'runtime.db'}"
            artifact_dir = root / "artifacts"
            with patch.dict(os.environ, {
                "DATABASE_URL": database_url,
                "MODEL_ARTIFACT_DIR": str(artifact_dir),
                "APP_VERSION": "test-version",
                "GIT_COMMIT_SHA": "1234567890abcdef",
            }, clear=False):
                initialize_runtime()
                report = readiness_report()

        serialized = json.dumps(report)
        self.assertEqual("ready", report["status"])
        self.assertEqual("sqlite", report["checks"]["database"]["backend"])
        self.assertTrue(report["checks"]["modelArtifactStorage"]["writable"])
        self.assertEqual("1234567890ab", report["build"]["commit"])
        self.assertNotIn(database_url, serialized)
        self.assertNotIn(str(artifact_dir), serialized)

    def test_required_database_failure_makes_service_not_ready(self):
        with patch("runtime_health.Database.ping", side_effect=RuntimeError("database offline")):
            report = readiness_report()

        self.assertEqual("not-ready", report["status"])
        self.assertEqual("unavailable", report["checks"]["database"]["status"])
        self.assertTrue(report["checks"]["database"]["required"])
        self.assertNotIn("database offline", json.dumps(report))

    def test_durable_database_guard_rejects_sqlite_without_exposing_location(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database_url = f"sqlite:///{root / 'runtime.db'}"
            with patch.dict(os.environ, {
                "DATABASE_URL": database_url,
                "MODEL_ARTIFACT_DIR": str(root / "artifacts"),
                "REQUIRE_DURABLE_DATABASE": "true",
            }, clear=False):
                initialize_runtime()
                report = readiness_report()

        database = report["checks"]["database"]
        self.assertEqual("not-ready", report["status"])
        self.assertEqual("durability-required", database["status"])
        self.assertTrue(database["durabilityRequired"])
        self.assertFalse(database["durableAcrossDeploys"])
        self.assertNotIn(database_url, json.dumps(report))

    @patch("runtime_health.Database")
    def test_durable_guard_rejects_legacy_postgresql_after_cutover(self, factory):
        database = factory.return_value
        database.backend = "postgresql"
        database.schema_status.return_value = {
            "currentVersion": 5,
            "expectedVersion": 5,
            "upToDate": True,
        }
        with patch.dict(os.environ, {"REQUIRE_DURABLE_DATABASE": "true"}, clear=False):
            report = readiness_report()

        self.assertEqual("not-ready", report["status"])
        self.assertEqual("durability-required", report["checks"]["database"]["status"])
        self.assertFalse(report["checks"]["database"]["durableAcrossDeploys"])

    def test_liveness_does_not_depend_on_external_market_or_llm_providers(self):
        report = liveness_report()
        self.assertEqual("ok", report["status"])
        self.assertEqual("not-required", report["authentication"])
        self.assertGreaterEqual(report["uptimeSeconds"], 0)

    def test_hybrid_llm_policy_is_reported_without_exposing_secrets_or_urls(self):
        secret = "private-test-key"
        local_url = "http://127.0.0.1:11434"
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "hybrid",
            "GEMINI_API_KEY": secret,
            "GEMINI_TIMEOUT_MS": "60000",
            "OLLAMA_BASE_URL": local_url,
        }, clear=False):
            report = readiness_report()

        language_model = report["checks"]["languageModel"]
        serialized = json.dumps(language_model)
        self.assertEqual("hybrid", language_model["provider"])
        self.assertEqual("gemini", language_model["primaryProvider"])
        self.assertEqual("ollama", language_model["fallbackProvider"])
        self.assertEqual(60000, language_model["geminiRequestTimeoutMs"])
        self.assertEqual("actual-failure-or-unusable-answer-only", language_model["fallbackPolicy"])
        self.assertTrue(language_model["geminiTriedForEveryQuestion"])
        self.assertNotIn(secret, serialized)
        self.assertNotIn(local_url, serialized)


if __name__ == "__main__":
    unittest.main()
