import unittest
from unittest.mock import MagicMock
from offline_training import stored_training_universe


class TrainingUniverseTests(unittest.TestCase):
    def test_all_stored_companies_are_selected_and_short_history_reported(self):
        database = MagicMock()
        database._rows.return_value = [{"symbol": f"COMPANY{i}", "bars": 200} for i in range(601)] + [
            {"symbol": "NEW", "bars": 179}, {"symbol": "BOUNDARY", "bars": 180}]
        result = stored_training_universe(database)
        self.assertEqual(len(result["eligible"]), 602)
        self.assertIn("BOUNDARY", result["eligible"])
        self.assertEqual(result["skipped"][0]["symbol"], "NEW")
        self.assertEqual(result["discovered"], 603)
