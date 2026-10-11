import json
import unittest
from rehearse_mysql_restore import decode_model_record


class RestoreModelRecordsTests(unittest.TestCase):
    def test_nested_metrics_escaped_strings_survive_mysql_transport(self):
        metrics = {"artifactSha256": "a" * 64, "notes": 'Quoted "model"\nPath C:\\models', "label": "測試"}
        original = {"symbol": "AAPL", "uri": "gs://bucket/models/test.joblib", "metrics": json.dumps(metrics)}
        encoded = json.dumps(original).encode("utf-8").hex().upper()
        restored = decode_model_record(encoded)
        self.assertEqual(restored, original)
        self.assertEqual(json.loads(restored["metrics"]), metrics)

    def test_invalid_hex_is_rejected(self):
        with self.assertRaises(ValueError):
            decode_model_record("not hex")
