import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from data_operations import data_operations_snapshot
from data_pipeline import bars_from_frame
from market_intelligence import _persist_research_history
from operations_pipeline import run_operations
from persistence import Database


class DataOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database = Database(
            f"sqlite:///{Path(self.temporary_directory.name) / 'operations.db'}"
        )
        self.database.initialize_schema()

    def tearDown(self):
        self.temporary_directory.cleanup()

    @staticmethod
    def _frame(rows=220, end=None):
        end = end or datetime.now(timezone.utc).date()
        index = pd.bdate_range(end=end, periods=rows)
        close = 100 + np.linspace(0, 18, rows)
        return pd.DataFrame({
            "Open": close * 0.999,
            "High": close * 1.006,
            "Low": close * 0.994,
            "Close": close,
            "Adj Close": close,
            "Volume": np.full(rows, 1_000_000),
        }, index=index)

    def test_provider_only_symbol_is_reported_honestly(self):
        snapshot = data_operations_snapshot("NEW.NS", self.database)

        self.assertEqual("provider_only", snapshot["freshness"])
        self.assertEqual(0, snapshot["storedBars"])
        self.assertFalse(snapshot["offlineTrainingReady"])
        self.assertFalse(snapshot["storage"]["durableAcrossDeploys"])

    def test_demand_research_seeds_dynamic_fresh_training_history(self):
        frame = self._frame()
        with patch("market_intelligence.Database", return_value=self.database):
            written = _persist_research_history("DYNAMIC.NS", "Dynamic Limited", frame)

        snapshot = data_operations_snapshot("DYNAMIC.NS", self.database)

        self.assertEqual(len(frame), written)
        self.assertEqual("fresh", snapshot["freshness"])
        self.assertTrue(snapshot["offlineTrainingReady"])
        self.assertIn("DYNAMIC.NS", self.database.operational_symbols())

    def test_old_history_is_stale_even_when_row_count_is_training_ready(self):
        old_end = datetime.now(timezone.utc).date() - timedelta(days=20)
        self.database.upsert_market_bars(bars_from_frame("OLD.NS", self._frame(end=old_end)))

        snapshot = data_operations_snapshot("OLD.NS", self.database)

        self.assertEqual("stale", snapshot["freshness"])
        self.assertTrue(snapshot["offlineTrainingReady"])

    def test_operations_use_database_universe_and_never_train_or_approve(self):
        self.database.upsert_market_bars(bars_from_frame("DYNAMIC.NS", self._frame()))
        ingestion = {
            "status": "completed",
            "results": [{"symbol": "DYNAMIC.NS", "status": "stored", "rows": 220}],
        }
        monitoring = {"status": "completed", "results": [], "errors": []}
        snapshot = {
            "servingMode": "runtime_fallback",
            "dataOperations": {"freshness": "fresh"},
            "driftMonitoring": {"status": "not_applicable"},
            "retrainingPolicy": {"decision": "offline_training_required"},
        }
        with (
            patch("operations_pipeline.ingest_symbols", return_value=ingestion) as ingest,
            patch("operations_pipeline.monitor_symbols", return_value=monitoring),
            patch("operations_pipeline.monitoring_snapshot", return_value=snapshot),
        ):
            result = run_operations(self.database)

        self.assertEqual("demand_driven_database", result["universeSource"])
        self.assertEqual(["DYNAMIC.NS"], result["symbols"])
        self.assertFalse(result["automaticTraining"])
        self.assertFalse(result["automaticApproval"])
        ingest.assert_called_once()


if __name__ == "__main__":
    unittest.main()
