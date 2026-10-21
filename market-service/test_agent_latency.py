"""Latency regressions also verify that evidence boundaries survive the fast path."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import market_intelligence as market
import document_rag as rag
from agent_orchestrator import build_agent_plan
from persistence import Database


class Request:
    headers = {}

    def __init__(self, message, symbol="CUSTOM.NS", **extra):
        self.payload = {"symbol": symbol, "message": message, **extra}

    async def body(self):
        return json.dumps(self.payload).encode()


class AgentLatencyTests(unittest.TestCase):
    def setUp(self):
        market.clear_market_cache()

    def test_report_question_never_fetches_quotes_profile_or_prediction(self):
        evidence = {"matches": [{
            "citation": "S1", "page": 4, "title": "Company annual report",
            "documentId": "custom-report", "reportingPeriod": "2025",
            "sourceUrl": "https://example.test/report", "score": .8,
            "text": "Reported debt was reduced through operating cash flows.",
            "snippet": "Reported debt was reduced through operating cash flows.",
        }]}
        with (
            patch.object(market, "market_snapshot") as snapshot,
            patch.object(market, "market_research_analysis") as prediction,
            patch.object(market, "company_research") as company,
            patch.object(rag, "retrieve_chunks", return_value=evidence) as retrieve,
            patch.object(market, "_provider_chat", side_effect=RuntimeError("offline")),
        ):
            result = asyncio.run(market.market_agent(Request(
                "Section: reports and RAG. Answer only from indexed company reports. "
                "User question: What does the report say about major risks and debt?")))
        snapshot.assert_not_called()
        prediction.assert_not_called()
        company.assert_not_called()
        retrieve.assert_called_once_with("CUSTOM.NS", "What does the report say about major risks and debt?", 5)
        self.assertEqual(["company_document_rag"], result["toolsUsed"])
        self.assertIn("[S1 p.4]", result["answer"])
        self.assertFalse(result["usedLiveContext"])

    def test_missing_report_returns_immediately_without_generator(self):
        with patch.object(rag, "retrieve_chunks", return_value={"matches": []}), patch.object(market, "_provider_chat") as chat:
            result = asyncio.run(market.market_agent(Request("Summarize the annual report")))
        chat.assert_not_called()
        self.assertEqual([], result["citations"])
        self.assertFalse(result["llmAnswerAccepted"])
        self.assertIn("retrievable evidence", result["answer"])

    def test_profile_question_ignores_ui_model_instruction_for_routing(self):
        snapshot = {"name": "Custom Company", "symbol": "CUSTOM.NS", "price": 100, "dataAsOf": "2026-10-21", "currency": "INR"}
        company = {"name": "Custom Company", "summary": "Builds network equipment.", "sector": "Technology", "industry": "Networks", "performance": {}, "fundamentals": {}}
        with (
            patch.object(market, "market_snapshot", return_value=snapshot),
            patch.object(market, "market_research_analysis") as prediction,
            patch.object(market, "company_research", return_value=company) as fetch,
            patch.object(market, "_provider_chat", side_effect=RuntimeError("offline")),
        ):
            result = asyncio.run(market.market_agent(Request(
                "Section: company evidence. Do not invent a model score. User question: Explain company fundamentals")))
        prediction.assert_not_called()
        fetch.assert_called_once_with("CUSTOM.NS", sections=set())
        self.assertNotIn("Prediction is unavailable", result["answer"])

    def test_basic_profile_does_not_call_optional_provider_endpoints_or_poison_full_cache(self):
        class ProfileTicker:
            def get_info(self):
                return {"longName": "Custom Company", "sector": "Technology"}

            def __getattr__(self, name):
                raise AssertionError("Unexpected optional provider call: " + name)

        frame = pd.DataFrame({"Close": [10., 11.], "Low": [9., 10.], "High": [11., 12.]}, index=pd.date_range("2026-10-19", periods=2))
        with patch.object(market.yf, "Ticker", return_value=ProfileTicker()), patch.object(market, "_history", return_value=frame), patch.object(market, "market_snapshot", return_value={"name": "Custom", "price": 11., "dataAsOf": "2026-10-20", "currency": "INR"}), patch.object(market, "market_news") as news:
            result = market.company_research("CUSTOM.NS", sections=set())
        self.assertEqual("Custom Company", result["name"])
        news.assert_not_called()
        self.assertIsNone(market._cache_get("company:CUSTOM.NS"))

    def test_requested_sections_preserve_detailed_evidence(self):
        plan = build_agent_plan("Revenue CAGR and free cash flow trend", "CUSTOM.NS")
        self.assertIn("statements", market._agent_company_sections(plan["intents"]))
        plan = build_agent_plan("Analyst estimate revisions", "CUSTOM.NS")
        self.assertEqual({"estimates"}, market._agent_company_sections(plan["intents"]))
        self.assertIn("technical_prediction", [step["tool"] for step in build_agent_plan("RSI and prediction", "CUSTOM.NS")["steps"]])

    def test_followup_retrieval_retains_the_previous_document_question(self):
        with patch.object(rag, "retrieve_chunks", return_value={"matches": []}) as retrieve, patch.object(market, "_provider_chat"):
            asyncio.run(market.market_agent(Request(
                "Why?", recentMessages=[{"role": "user", "content": "What does the annual report say about debt?"}])))
        self.assertIn("annual report", retrieve.call_args.args[1])
        self.assertIn("debt", retrieve.call_args.args[1])

    def test_company_fallback_keeps_requested_detailed_evidence_without_forecast(self):
        snapshot = {"name": "Custom Company", "currency": "INR"}
        company = {"sector": "Technology", "fundamentals": {}, "financialTrends": {
            "status": "available", "summary": {"latestAnnualPeriod": "2025-03-31", "revenueTrend": "increased"},
            "annual": [{"period": "2025-03-31", "revenue": 123000, "freeCashFlow": 3000}],
        }}
        answer = market._verified_tool_answer(
            "Explain the revenue trend and free cash flow", snapshot,
            market._unrequested_agent_prediction("CUSTOM.NS", snapshot), [], {}, company_profile=company)
        self.assertIn("2025-03-31", answer)
        self.assertIn("123K INR", answer)
        self.assertNotIn("probability-up", answer)

    def test_independent_evidence_calls_overlap(self):
        barrier = threading.Barrier(3)

        def evidence(value):
            barrier.wait(timeout=3)
            return value

        plan = {"steps": [{"tool": name} for name in ("market_snapshot", "company_fundamentals", "market_news", "macro_market_factors")], "intents": []}
        with (
            patch.object(market, "market_snapshot", return_value={"name": "Custom"}),
            patch.object(market, "company_research", side_effect=lambda *a, **k: evidence({"sector": "Technology"})),
            patch.object(market, "market_news", side_effect=lambda *a: evidence({"articles": []})),
            patch.object(market, "macro_factors", side_effect=lambda: evidence({"factors": []})),
        ):
            context, outcomes = market._collect_agent_evidence(plan, "CUSTOM.NS", "question", None)
        self.assertIn("company", context)
        self.assertEqual(4, len(outcomes))

    def test_waiting_agent_does_not_block_event_loop(self):
        entered, release = threading.Event(), threading.Event()

        def execute(payload):
            entered.set()
            release.wait(timeout=3)
            return {"answer": "done"}

        async def check():
            task = asyncio.create_task(market.market_agent(Request("question")))
            try:
                for _ in range(100):
                    if entered.is_set():
                        break
                    await asyncio.sleep(.01)
                self.assertTrue(entered.is_set())
                self.assertFalse(task.done())
            finally:
                release.set()
                await task

        with patch.object(market, "_execute_market_agent", side_effect=execute):
            asyncio.run(check())

    def test_unknown_and_uncited_document_claims_are_rejected(self):
        matches = [{"citation": "S1", "page": 4}]
        prediction = market._unrequested_agent_prediction("CUSTOM.NS", {})
        for answer, issue in (
            ("Reported debt decreased during the reporting period according to the annual report. [S1 p.4] [S9 p.99]", "unknown indexed document citation"),
            ("Reported debt decreased during the reporting period according to the annual report. [S1 p.4]\nRevenue doubled during the same reporting period according to management.", "uncited document claim"),
        ):
            self.assertEqual(issue, market._llm_grounding_issue(answer, "annual report", prediction, {}, document_matches=matches, document_requested=True))


class RetrievalCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.database = Database(f"sqlite:///{Path(self.tmp.name) / 'rag.db'}")
        with rag._RETRIEVAL_CACHE_LOCK:
            rag._RETRIEVAL_CACHE.clear()

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, symbol, text):
        return rag.ingest_text_evidence(symbol, "Annual report", text * 8, "annual-report", "2025", "https://example.test/report", database=self.database)

    def test_repeated_questions_reuse_index_and_query_vectors_but_keep_citations(self):
        self.ingest("CUSTOM.NS", "Revenue increased through software services. ")
        with patch.object(self.database, "document_chunks", wraps=self.database.document_chunks) as chunks, patch.object(rag, "embed_texts", wraps=rag.embed_texts) as embed:
            first = rag.retrieve_chunks("CUSTOM.NS", "How did revenue increase?", database=self.database)
            again = rag.retrieve_chunks("CUSTOM.NS", "How did revenue increase?", database=self.database)
        self.assertTrue(first["matches"])
        self.assertEqual(first, again)
        self.assertEqual(1, chunks.call_count)
        self.assertEqual(1, embed.call_count)

    def test_manifest_change_and_company_selection_do_not_reuse_old_passages(self):
        original = self.ingest("CUSTOM.NS", "Revenue increased through software services. ")
        rag.retrieve_chunks("CUSTOM.NS", "revenue", database=self.database)
        replacement = self.ingest("CUSTOM.NS", "Revenue decreased because product demand declined. ")
        self.database.delete_documents("CUSTOM.NS", "annual-report", replacement["documentId"])
        updated = rag.retrieve_chunks("CUSTOM.NS", "revenue", database=self.database)
        self.assertTrue(updated["matches"])
        self.assertTrue(all(item["documentId"] != original["documentId"] for item in updated["matches"]))
        other = rag.retrieve_chunks("OTHER.NS", "revenue", database=self.database)
        self.assertEqual([], other["matches"])
        self.database.delete_documents("CUSTOM.NS", "annual-report")
        self.assertEqual([], rag.retrieve_chunks("CUSTOM.NS", "revenue", database=self.database)["matches"])


if __name__ == "__main__":
    unittest.main()
