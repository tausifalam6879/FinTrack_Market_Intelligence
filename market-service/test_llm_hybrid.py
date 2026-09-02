import os
import json
import unittest
from unittest.mock import patch

import market_intelligence as market


MESSAGES = [{"role": "user", "content": "Explain the verified evidence."}]


class HybridLlmTests(unittest.TestCase):
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
    @patch("market_intelligence._gemini_chat")
    def test_offline_preference_skips_gemini_timeout(self, gemini_chat, ollama_chat):
        with patch.dict(os.environ, {"LLM_PROVIDER": "hybrid"}, clear=False):
            answer, provider = market._provider_chat(MESSAGES, prefer_local=True)

        self.assertEqual("Local Ollama answer", answer)
        self.assertEqual("ollama", provider)
        gemini_chat.assert_not_called()
        ollama_chat.assert_called_once_with(MESSAGES)

    @patch("market_intelligence._ollama_chat", return_value="Local Ollama answer")
    @patch("market_intelligence._gemini_chat", side_effect=RuntimeError("Gemini service is unavailable."))
    def test_hybrid_retries_gemini_for_every_question_before_ollama(self, gemini_chat, ollama_chat):
        with patch.dict(os.environ, {"LLM_PROVIDER": "hybrid"}, clear=False):
            first = market._provider_chat(MESSAGES)
            second = market._provider_chat(MESSAGES)

        self.assertEqual(("Local Ollama answer", "ollama"), first)
        self.assertEqual(("Local Ollama answer", "ollama"), second)
        self.assertEqual(2, gemini_chat.call_count)
        self.assertEqual(2, ollama_chat.call_count)

    @patch("market_intelligence._ollama_chat", side_effect=RuntimeError("Local Ollama service is unavailable."))
    @patch("market_intelligence._gemini_chat", side_effect=RuntimeError("Gemini service is unavailable."))
    def test_hybrid_reports_failure_when_both_providers_are_unavailable(self, _gemini_chat, _ollama_chat):
        with patch.dict(os.environ, {"LLM_PROVIDER": "hybrid"}, clear=False):
            with self.assertRaisesRegex(RuntimeError, "Hybrid LLM providers are unavailable"):
                market._provider_chat(MESSAGES)

    @patch("market_intelligence.urlopen")
    def test_ollama_receives_compact_question_with_requested_model_metrics(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = json.dumps({
            "message": {"content": "RSI is neutral."}
        }).encode("utf-8")
        evidence = {
            "asset": {"symbol": "^NSEI", "price": 24252},
            "model": {"probabilityUp": 48.7, "rsi14": 45.2, "outlook": "NEUTRAL"},
            "derivedCalculations": {"rangeWidth": 358.4},
            "drivers": [[f"factor-{index}", index] for index in range(20)],
            "largeUnusedSection": "x" * 7000,
        }
        messages = [
            {"role": "system", "content": "long hosted model policy " * 500},
            {"role": "user", "content": f"Question: RSI samjhao\nEvidence: {json.dumps(evidence)}"},
        ]

        answer = market._ollama_chat(messages)

        request = urlopen.call_args.args[0]
        body = json.loads(request.data.decode("utf-8"))
        compact_prompt = body["messages"][-1]["content"]
        self.assertEqual("RSI is neutral.", answer)
        self.assertIn('"rsi14": 45.2', compact_prompt)
        self.assertNotIn('"probabilityUp": 48.7', compact_prompt)
        self.assertIn("above 70 overbought", compact_prompt)
        self.assertNotIn("long hosted model policy", body["messages"][0]["content"])
        self.assertLessEqual(len(compact_prompt), 900)
        self.assertEqual(2048, body["options"]["num_ctx"])


if __name__ == "__main__":
    unittest.main()
