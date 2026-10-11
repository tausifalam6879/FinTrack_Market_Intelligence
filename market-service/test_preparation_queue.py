import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from persistence import Database
from preparation_queue import PreparationQueue, process_queue


class PreparationQueueTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = Database("sqlite:///" + str(Path(self.directory.name) / "queue.db"))
        self.queue = PreparationQueue(self.database)
        self.queue.initialize()

    def test_deduplication_and_terminal_status_are_preserved(self):
        self.queue.enqueue("aapl")
        self.queue.enqueue("AAPL")
        claim = self.queue.claim()
        self.assertEqual(claim["symbol"], "AAPL")
        self.assertIsNone(self.queue.claim())
        self.queue.finish(claim, "rejected", "run-id")
        self.assertEqual(self.queue.enqueue("AAPL")["status"], "rejected")
        self.assertIsNone(self.queue.claim())

    def test_foreign_lease_cannot_finish_work(self):
        self.queue.enqueue("MSFT")
        claim = self.queue.claim()
        self.queue.finish({**claim, "lease_token": "wrong"}, "candidate")
        self.assertEqual(self.queue.status("MSFT")["status"], "running")

    def test_capacity_is_bounded(self):
        for index in range(100):
            self.queue.enqueue(f"C{index}")
        self.assertEqual(self.queue.enqueue("NEW")["status"], "queue_full")
        self.assertEqual(self.queue.enqueue("C0")["status"], "pending")

    def test_worker_records_candidate_without_approval(self):
        self.queue.enqueue("AAPL")
        with patch("preparation_queue.ingest_symbols", return_value={"results": [{"status": "stored"}]}), \
             patch("offline_training.train_symbol", return_value={"status": "candidate", "modelRunId": "run-id"}) as train:
            result = process_queue(self.database, 1)
        self.assertFalse(result["automaticApproval"])
        self.assertEqual(self.queue.status("AAPL")["status"], "candidate")
        train.assert_called_once()

    def test_worker_error_is_sanitized(self):
        self.queue.enqueue("AAPL")
        with patch("preparation_queue.ingest_symbols", side_effect=RuntimeError("password-secret")):
            process_queue(self.database, 1)
        status = self.queue.status("AAPL")
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error_code"], "RuntimeError")
        self.assertNotIn("password-secret", str(status))
