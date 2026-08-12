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

    def test_liveness_does_not_depend_on_external_market_or_llm_providers(self):
        report = liveness_report()
        self.assertEqual("ok", report["status"])
        self.assertEqual("not-required", report["authentication"])
        self.assertGreaterEqual(report["uptimeSeconds"], 0)


if __name__ == "__main__":
    unittest.main()
