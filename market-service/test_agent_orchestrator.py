import unittest
import asyncio
from datetime import date
import json
from unittest.mock import patch

from agent_orchestrator import build_agent_plan, tool_trace
from market_intelligence import market_agent


class AgentOrchestratorTests(unittest.TestCase):
    def test_document_question_routes_to_cited_rag_without_unrelated_global_tools(self):
        plan = build_agent_plan(
            "Reliance annual report me debt ke baare me kya kaha gaya?",
            "RELIANCE.NS",
        )
        tools = [step["tool"] for step in plan["steps"]]

        self.assertIn("company_document_rag", tools)
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("market_breadth", tools)
        self.assertNotIn("global_market_overview", tools)
        self.assertFalse(plan["safety"]["llmChoosesTools"])
        self.assertTrue(all(step["access"] == "read-only" for step in plan["steps"]))

    def test_historical_global_breadth_request_selects_each_required_tool(self):
        plan = build_agent_plan(
            "15 July 2026 ke global markets, gainers losers compare karo",
            "^NSEI",
            date(2026, 7, 15),
            is_index=True,
        )
        tools = {step["tool"] for step in plan["steps"]}
        self.assertIn("historical_market_session", tools)
        self.assertIn("market_breadth", tools)
        self.assertIn("global_market_overview", tools)
        self.assertNotIn("company_document_rag", tools)

    def test_risk_question_is_explicitly_classified_without_adding_mutation_tools(self):
        plan = build_agent_plan(
            "Infosys ka beta, drawdown aur Nifty benchmark risk samjhao",
            "INFY.NS",
        )

        self.assertIn("risk_and_benchmark_analysis", plan["intents"])
        self.assertIn("technical_prediction", [step["tool"] for step in plan["steps"]])
        self.assertFalse(plan["safety"]["mutationToolsAvailable"])

    def test_peer_question_uses_dynamic_read_only_comparison_tool(self):
        plan = build_agent_plan(
            "NVIDIA ko same sector peers se valuation comparison karo",
            "NVDA",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("sector_peer_analysis", plan["intents"])
        self.assertIn("sector_peer_comparison", tools)
        peer_step = next(step for step in plan["steps"] if step["tool"] == "sector_peer_comparison")
        self.assertEqual("read-only", peer_step["access"])

    def test_trace_preserves_plan_reason_and_honest_no_evidence_status(self):
        plan = build_agent_plan("annual report source citation", "AAPL")
        trace = tool_trace(plan, {
            "company_document_rag": {
                "status": "no_evidence",
                "evidenceCount": 0,
                "message": "No indexed evidence.",
            }
        })
        rag = next(item for item in trace if item["tool"] == "company_document_rag")
        self.assertEqual("no_evidence", rag["status"])
        self.assertIn("reason", rag)

    def test_public_agent_returns_plan_trace_and_document_citations(self):
        snapshot = {
            "price": 1400.0,
            "changePercent": 0.8,
            "dataAsOf": "2026-08-12T10:00:00+00:00",
            "source": "test market feed",
        }
        prediction = {
            "name": "Reliance Industries",
            "outlook": "NEUTRAL",
            "probabilityUp": 52.0,
            "probabilityDown": 48.0,
            "dataAsOf": "2026-08-12T10:00:00+00:00",
            "expectedRange": {"low": 1380.0, "high": 1420.0, "currency": "INR"},
            "newsFactor": {"sentimentLabel": "mixed/neutral"},
            "model": {
                "backtestAccuracy": 52.0,
                "balancedAccuracy": 51.0,
                "rocAuc": 50.5,
                "walkForwardFolds": 5,
                "type": "Logistic Regression",
                "quality": "weak",
            },
            "technicalIndicators": {"rsi14": 49.0},
            "macroFactor": {"signal": "neutral", "factors": []},
            "history": [],
            "disclaimer": "Educational research only.",
        }
        company = {
            "sector": "Energy",
            "industry": "Integrated energy",
            "performance": {},
            "fundamentals": {},
        }
        retrieval = {
            "provider": "local-hashing-v1",
            "matches": [{
                "citation": "S1",
                "documentId": "doc-1",
                "title": "Reliance Annual Report",
                "documentType": "annual-report",
                "reportingPeriod": "FY 2024-25",
                "sourceUrl": "https://example.com/report.pdf",
                "page": 98,
                "score": 0.71,
                "text": "Borrowings and debt evidence from the indexed annual report.",
                "snippet": "Borrowings and debt evidence from the indexed annual report.",
            }],
        }
        with (
            patch("market_intelligence.market_snapshot", return_value=snapshot),
            patch("market_intelligence.market_prediction", return_value=prediction),
            patch("market_intelligence.company_research", return_value=company),
            patch("document_rag.retrieve_chunks", return_value=retrieval),
            patch("market_intelligence._provider_chat", side_effect=RuntimeError("offline")),
        ):
            payload = {
                "symbol": "RELIANCE.NS",
                "message": "Annual report me debt ke baare me kya kaha gaya?",
            }

            class FakeRequest:
                headers = {"content-length": "1", "content-type": "application/json"}

                async def body(self):
                    return json.dumps(payload).encode("utf-8")

            body = asyncio.run(market_agent(FakeRequest()))

        self.assertEqual("deterministic-read-only-v1", body["agentPlan"]["planner"])
        self.assertIn("company_document_rag", body["toolsUsed"])
        self.assertEqual("S1", body["citations"][0]["citation"])
        self.assertIn("[S1 p.98]", body["answer"])
        rag_trace = next(item for item in body["toolTrace"] if item["tool"] == "company_document_rag")
        self.assertEqual("completed", rag_trace["status"])
        self.assertEqual(1, rag_trace["evidenceCount"])


if __name__ == "__main__":
    unittest.main()
