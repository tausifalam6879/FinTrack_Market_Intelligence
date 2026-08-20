import unittest

from runtime_metrics import record_llm, record_request, telemetry_snapshot


class RuntimeMetricsTests(unittest.TestCase):
    def test_snapshot_contains_only_aggregate_route_and_llm_evidence(self):
        record_request("/market/analysis", 200, 12.5)
        record_request("/market/analysis", 503, 25.0)
        record_llm("grounding_fallback", False)
        snapshot = telemetry_snapshot()

        self.assertGreaterEqual(snapshot["api"]["totalRequests"], 2)
        self.assertGreaterEqual(snapshot["api"]["serverErrors"], 1)
        self.assertIsNotNone(snapshot["api"]["p95LatencyMs"])
        self.assertGreaterEqual(snapshot["languageModel"]["groundingFallbacks"], 1)
        self.assertIn("no questions", snapshot["privacy"])


if __name__ == "__main__":
    unittest.main()
