import os
import ssl
import unittest

from persistence import Database, LATEST_SCHEMA_VERSION


class MySqlConfigurationTests(unittest.TestCase):
    def test_mysql_url_is_parsed_without_exposing_credentials(self):
        database = Database(
            "mysql+pymysql://fintrack:p%40ss@db.example:3307/fintrack?charset=utf8mb4&ssl-mode=REQUIRED"
        )
        options = database._mysql_connection_options()

        self.assertEqual("mysql", database.backend)
        self.assertEqual("db.example", options["host"])
        self.assertEqual(3307, options["port"])
        self.assertEqual("fintrack", options["user"])
        self.assertEqual("p@ss", options["password"])
        self.assertEqual("fintrack", options["database"])
        self.assertIn("ssl", options)

    def test_hosted_mysql_requires_verified_tls_in_driver(self):
        import pymysql

        for mode in ("REQUIRED", "VERIFY_IDENTITY", "VERIFY_CA"):
            with self.subTest(mode=mode):
                options = Database(
                    f"mysql://test:test@example.invalid/fintrack?ssl-mode={mode}"
                )._mysql_connection_options()
                connection = pymysql.Connection(defer_connect=True, **options)
                self.assertTrue(connection.ssl)
                self.assertTrue(connection._ssl_required)
                self.assertEqual(ssl.CERT_REQUIRED, connection.ctx.verify_mode)
                self.assertEqual(mode != "VERIFY_CA", connection.ctx.check_hostname)

    def test_mysql_statements_use_mysql_upsert_syntax(self):
        statements = "\n".join(Database._mysql_schema_statements())

        self.assertIn("ENGINE=InnoDB", statements)
        self.assertIn("utf8mb4", statements)
        self.assertNotIn("TIMESTAMPTZ", statements)


@unittest.skipUnless(
    os.getenv("FINTRACK_TEST_MYSQL_URL"),
    "Set FINTRACK_TEST_MYSQL_URL to run the real MySQL integration test.",
)
class MySqlIntegrationTests(unittest.TestCase):
    def test_schema_and_core_upserts_against_mysql(self):
        database = Database(os.environ["FINTRACK_TEST_MYSQL_URL"])
        database.initialize_schema()
        self.assertEqual("mysql", database.backend)
        self.assertEqual(LATEST_SCHEMA_VERSION, database.schema_status()["currentVersion"])

        symbol = "MYSQLTEST.NS"
        database.upsert_company({"symbol": symbol, "name": "First Name", "source": "test"})
        database.upsert_company({"symbol": symbol, "name": "Updated Name", "source": "test"})
        database.upsert_market_bars([{
            "symbol": symbol,
            "session_date": "2026-09-03",
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.0,
            "adjusted_close": 101.0,
            "volume": 1000,
            "source": "test",
        }])

        model_run_id = "mysql-integration-run"
        prediction_id = "mysql-integration-prediction"
        document_id = "mysql-integration-document"
        database.save_model_run({
            "id": model_run_id,
            "symbol": symbol,
            "model_name": "Logistic Regression",
            "artifact_path": "artifacts/mysql-integration.joblib",
            "dataset_version": "mysql-integration-dataset",
            "training_start": "2025-01-01",
            "training_end": "2025-10-31",
            "training_rows": 200,
            "holdout_start": "2025-11-01",
            "holdout_end": "2025-12-31",
            "holdout_rows": 40,
            "balanced_accuracy": 0.58,
            "roc_auc": 0.62,
            "brier_score": 0.24,
            "metrics": {"accuracy": 0.57},
            "baselines": {"majority": {"balancedAccuracy": 0.5}},
            "features": ["return_1"],
        })
        database.replace_feature_baselines(model_run_id, symbol, [{
            "featureName": "return_1",
            "sampleCount": 200,
            "mean": 0.01,
            "std": 0.02,
            "binEdges": [-0.05, 0.0, 0.05],
            "binProportions": [0.25, 0.5, 0.25],
        }])
        database.upsert_prediction({
            "id": prediction_id,
            "symbol": symbol,
            "model_run_id": model_run_id,
            "model_data_date": "2026-09-03",
            "generated_at": "2026-09-03T12:00:00+00:00",
            "probability_up": 58.0,
            "outlook": "BULLISH",
            "reference_close": 102.0,
        })
        database.upsert_prediction_features(
            prediction_id, symbol, model_run_id, {"return_1": 0.02}
        )
        database.save_drift_snapshot({
            "id": "mysql-integration-drift",
            "symbol": symbol,
            "modelRunId": model_run_id,
            "evaluatedAt": "2026-09-03T13:00:00+00:00",
            "recentObservations": 1,
            "meanPsi": 0.01,
            "maxPsi": 0.01,
            "status": "low",
            "recommendation": "monitor",
        })
        database.replace_document({
            "id": document_id,
            "symbol": symbol,
            "title": "MySQL integration evidence",
            "document_type": "test",
            "file_sha256": "0" * 64,
            "page_count": 1,
            "embedding_provider": "test",
        }, [{
            "id": "mysql-integration-chunk",
            "page_number": 1,
            "chunk_index": 0,
            "text": "Verified MySQL document row.",
            "embedding": [0.1, 0.2],
        }])
        database.upsert_market_bars([{
            "symbol": symbol,
            "session_date": "2026-09-03",
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 102.0,
            "adjusted_close": 102.0,
            "volume": 1200,
            "source": "test",
        }])

        with database.connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT name FROM companies WHERE symbol = %s", (symbol,))
            self.assertEqual("Updated Name", cursor.fetchone()[0])
            cursor.execute(
                "SELECT close, volume FROM market_bars WHERE symbol = %s AND session_date = %s",
                (symbol, "2026-09-03"),
            )
            close, volume = cursor.fetchone()
            self.assertEqual(102.0, float(close))
            self.assertEqual(1200, int(volume))
            cursor.execute("SELECT COUNT(*) FROM prediction_features WHERE prediction_id = %s", (prediction_id,))
            self.assertEqual(1, int(cursor.fetchone()[0]))
            cursor.execute("SELECT COUNT(*) FROM document_chunks WHERE document_id = %s", (document_id,))
            self.assertEqual(1, int(cursor.fetchone()[0]))
            cursor.execute("DELETE FROM document_sources WHERE id = %s", (document_id,))
            cursor.execute("DELETE FROM drift_snapshots WHERE model_run_id = %s", (model_run_id,))
            cursor.execute("DELETE FROM prediction_features WHERE model_run_id = %s", (model_run_id,))
            cursor.execute("DELETE FROM predictions WHERE model_run_id = %s", (model_run_id,))
            cursor.execute("DELETE FROM model_feature_baselines WHERE model_run_id = %s", (model_run_id,))
            cursor.execute("DELETE FROM model_runs WHERE id = %s", (model_run_id,))
            cursor.execute("DELETE FROM market_bars WHERE symbol = %s", (symbol,))
            cursor.execute("DELETE FROM companies WHERE symbol = %s", (symbol,))


if __name__ == "__main__":
    unittest.main()
