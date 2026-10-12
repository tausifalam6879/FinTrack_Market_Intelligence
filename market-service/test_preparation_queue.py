import tempfile
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from persistence import Database
from preparation_queue import PreparationQueue, process_queue, eligible_for_automatic_approval, seed_uncovered_symbols


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

    def test_explicit_retry_and_run_identity_are_preserved(self):
        self.queue.enqueue("NVDA")
        claim = self.queue.claim()
        self.queue.finish(claim, "rejected", "failed-quality-run")
        self.assertEqual(self.queue.enqueue("NVDA")["model_run_id"], "failed-quality-run")
        self.assertEqual(self.queue.retry("NVDA")["status"], "pending")
        claim = self.queue.claim()
        self.assertEqual(self.queue.retry("NVDA")["status"], "running")

    def test_automatic_approval_rejects_legacy_small_and_failed_models(self):
        candidate = {"status": "candidate", "qualityGate": {"passed": True},
                     "probabilityMethod": "chronological_sigmoid_v1",
                     "untouchedHoldout": {"rows": 75, "brierScore": 0.23}}
        self.assertTrue(eligible_for_automatic_approval(candidate))
        for changes in ({"status": "rejected"}, {"probabilityMethod": "legacy"},
                        {"untouchedHoldout": {"rows": 30, "brierScore": 0.23}},
                        {"untouchedHoldout": {"rows": 75, "brierScore": 0.26}}):
            self.assertFalse(eligible_for_automatic_approval({**candidate, **changes}))

    def test_worker_approves_only_through_verified_registry(self):
        self.queue.enqueue("AAPL")
        result = {"status": "candidate", "modelRunId": "run-id", "qualityGate": {"passed": True},
                  "probabilityMethod": "chronological_sigmoid_v1",
                  "untouchedHoldout": {"rows": 80, "brierScore": 0.24}}
        with patch.dict(os.environ, {"PREPARATION_APPROVE_PASSING": "true"}), \
             patch("preparation_queue.ingest_symbols", return_value={"results": [{"status": "stored"}]}), \
             patch("offline_training.train_symbol", return_value=result), \
             patch("model_registry.approve_model") as approve:
            output = process_queue(self.database, 1)
        approve.assert_called_once_with("run-id", self.database)
        self.assertEqual(output["results"][0]["status"], "approved")

    def test_capacity_is_bounded(self):
        for index in range(100):
            self.queue.enqueue(f"C{index}")
        self.assertEqual(self.queue.enqueue("NEW")["status"], "queue_full")
        self.assertEqual(self.queue.enqueue("C0")["status"], "pending")

    def test_seed_skips_approved_and_already_calibrated_results(self):
        self.queue.enqueue("OLD")
        self.queue.finish(self.queue.claim(), "rejected", "old-run")
        def latest(symbol, status=None):
            if status == "approved":
                return {"id": "approved-run"} if symbol == "APPROVED" else None
            return {"metrics_json": '{"probabilityMethod":"chronological_sigmoid_v1"}'} if symbol == "CALIBRATED" else None
        with patch("offline_training.stored_training_universe", return_value={"eligible": ["OLD", "NEW", "APPROVED", "CALIBRATED"]}), \
             patch.object(self.database, "latest_model_run", side_effect=latest):
            result = seed_uncovered_symbols(self.database)
        self.assertEqual([r["symbol"] for r in result["results"]], ["OLD", "NEW"])
        self.assertEqual(self.queue.status("OLD")["status"], "pending")
        self.assertFalse(result["trainingStarted"])

    def test_retry_does_not_exceed_queue_capacity(self):
        self.queue.enqueue("OLD")
        self.queue.finish(self.queue.claim(), "rejected")
        for index in range(100):
            self.queue.enqueue(f"C{index}")
        self.assertEqual(self.queue.retry("OLD")["status"], "queue_full")
        self.assertEqual(self.queue.status("OLD")["status"], "rejected")

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
