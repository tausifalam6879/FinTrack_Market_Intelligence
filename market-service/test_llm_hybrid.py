import os
import time
import unittest
from unittest.mock import patch

import market_intelligence as market


MESSAGES = [{"role": "user", "content": "Explain the verified evidence."}]


class HybridLlmTests(unittest.TestCase):
    def setUp(self):
        with market._llm_circuit_lock:
            market._gemini_circuit_open_until = 0.0

    def tearDown(self):
        with market._llm_circuit_lock:
            market._gemini_circuit_open_until = 0.0

    @patch("market_intelligence._ollama_chat")
    @patch("market_intelligence._gemini_chat")
    def test_hybrid_prefers_gemini(self, gemini_chat, ollama_chat):
        gemini_chat.return_value = "Gemini answer"
        with patch.dict(os.environ, {"LLM_PROVIDER": "hybrid"}, clear=False):
            answer, provider = market._provider_chat(MESSAGES)

        self.assertEqual("Gemini answer", answer)
        self.assertEqual("gemini", provider)
        ollama_chat.assert_not_called()

    @patch("market_intelligence._ollama_chat", return_value="Local Ollama answer")
    @patch("market_intelligence._gemini_chat", side_effect=RuntimeError("Gemini service is unavailable."))
    def test_hybrid_uses_ollama_and_skips_gemini_during_ten_second_cooldown(self, gemini_chat, ollama_chat):
        with patch.dict(os.environ, {
            "LLM_PROVIDER": "hybrid",
            "GEMINI_CIRCUIT_COOLDOWN_SECONDS": "10",
        }, clear=False):
            first = market._provider_chat(MESSAGES)
            second = market._provider_chat(MESSAGES)

        self.assertEqual(("Local Ollama answer", "ollama"), first)
        self.assertEqual(("Local Ollama answer", "ollama"), second)
        self.assertEqual(1, gemini_chat.call_count)
        self.assertEqual(2, ollama_chat.call_count)
        self.assertGreater(market._gemini_circuit_open_until, time.monotonic())

    @patch("market_intelligence._ollama_chat", side_effect=RuntimeError("Local Ollama service is unavailable."))
    @patch("market_intelligence._gemini_chat", side_effect=RuntimeError("Gemini service is unavailable."))
    def test_hybrid_reports_failure_when_both_providers_are_unavailable(self, _gemini_chat, _ollama_chat):
        with patch.dict(os.environ, {"LLM_PROVIDER": "hybrid"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "Hybrid LLM providers are unavailable"):
                market._provider_chat(MESSAGES)


if __name__ == "__main__":
    unittest.main()
