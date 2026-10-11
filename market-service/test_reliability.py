import os
import hashlib
import sys
from types import SimpleNamespace
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from artifact_storage import resolve_artifact
from request_budget import RequestBudget


class ReliabilityTests(unittest.TestCase):
    def test_remote_download_is_verified_and_reused(self):
        content = b"controlled-test-payload"
        checksum = hashlib.sha256(content).hexdigest()
        class Blob:
            size = len(content)
            downloads = 0
            def download_to_filename(self, filename, timeout):
                self.downloads += 1
                Path(filename).write_bytes(content)
        blob = Blob()
        storage = SimpleNamespace(Client=lambda: SimpleNamespace(
            bucket=lambda bucket: SimpleNamespace(blob=lambda key: blob)))
        with TemporaryDirectory() as directory, patch.dict(os.environ, {"MODEL_ARTIFACT_BUCKET": "trusted"}), \
             patch.dict(sys.modules, {"google": SimpleNamespace(cloud=SimpleNamespace(storage=storage)),
                                     "google.cloud": SimpleNamespace(storage=storage),
                                     "google.cloud.storage": storage}):
            root = Path(directory)
            first = resolve_artifact("gs://trusted/models/model.joblib", root, checksum)
            second = resolve_artifact("gs://trusted/models/model.joblib", root, checksum)
            self.assertEqual(first, second)
            self.assertEqual(blob.downloads, 1)
            self.assertEqual(first.read_bytes(), content)

    def test_limits_reject_and_release_without_consuming_rejected_quota(self):
        budget = RequestBudget(per_minute=2, concurrent=1)
        self.assertTrue(budget.acquire())
        self.assertFalse(budget.acquire())
        budget.release()
        self.assertTrue(budget.acquire())
        budget.release()
        self.assertFalse(budget.acquire())

    def test_budget_recovers_after_window(self):
        with patch("request_budget.time.monotonic", side_effect=[0, 61]):
            budget = RequestBudget(per_minute=1)
            self.assertTrue(budget.acquire())
            budget.release()
            self.assertTrue(budget.acquire())

    def test_untrusted_bucket_rejected_before_download(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, {"MODEL_ARTIFACT_BUCKET": "trusted"}):
            with self.assertRaises(ValueError):
                resolve_artifact("gs://other/models/x.joblib", Path(root), "a" * 64)

    def test_untrusted_prefix_rejected_before_download(self):
        with TemporaryDirectory() as root, patch.dict(os.environ, {"MODEL_ARTIFACT_BUCKET": "trusted"}):
            with self.assertRaises(ValueError):
                resolve_artifact("gs://trusted/other/x.joblib", Path(root), "a" * 64)

    def test_prediction_never_trains_without_approved_artifact(self):
        import numpy as np
        import pandas as pd
        import market_intelligence as market
        from fastapi import HTTPException
        rng = np.random.default_rng(42)
        close = 100 * np.cumprod(1 + rng.normal(0, .01, 200))
        frame = pd.DataFrame({"Close": close, "Volume": rng.integers(100, 500, 200)},
                             index=pd.bdate_range("2025-01-01", periods=200))
        with patch.object(market, "_cache_get", return_value=None), \
             patch.object(market, "_history", return_value=frame), \
             patch.object(market, "approved_model", return_value=None), \
             patch.object(market, "_walk_forward_model_comparison") as train:
            with self.assertRaises(HTTPException) as error:
                market.market_prediction("INFY.NS")
            self.assertEqual(error.exception.status_code, 503)
            self.assertEqual(error.exception.detail["code"], "MODEL_UNAVAILABLE")
            train.assert_not_called()
