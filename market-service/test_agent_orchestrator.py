import unittest
import asyncio
from datetime import date
import json
from unittest.mock import patch

from agent_orchestrator import build_agent_plan, tool_trace
from market_intelligence import market_agent


class AgentOrchestratorTests(unittest.TestCase):
    def test_broad_market_explanation_routes_to_risk_context(self):
        plan = build_agent_plan(
            "How has 7269.T behaved versus the broad market? iska kya matlab hai",
            "7269.T",
        )

        self.assertIn("risk_and_benchmark_analysis", plan["intents"])
        self.assertNotIn("general_market_research", plan["intents"])

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

    def test_earnings_and_target_question_uses_company_catalyst_evidence(self):
        plan = build_agent_plan(
            "Cisco ka next earnings date aur analyst price target batao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("company_catalyst_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)

    def test_company_news_question_uses_read_only_headline_evidence(self):
        plan = build_agent_plan(
            "Cisco recent news sentiment themes aur source diversity batao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("news_analysis", plan["intents"])
        self.assertIn("market_news", tools)
        news_step = next(step for step in plan["steps"] if step["tool"] == "market_news")
        self.assertEqual("read-only", news_step["access"])

    def test_financial_trend_question_uses_company_statement_evidence(self):
        plan = build_agent_plan(
            "Reliance ka revenue CAGR, margin aur free cash flow trend samjhao",
            "RELIANCE.NS",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("financial_statement_trend_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("company_document_rag", tools)
        company_step = next(step for step in plan["steps"] if step["tool"] == "company_fundamentals")
        self.assertEqual("read-only", company_step["access"])

    def test_ownership_question_uses_read_only_company_evidence_without_forcing_rag(self):
        plan = build_agent_plan(
            "Cisco ke institutional holders, ownership concentration aur insider buying selling samjhao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("ownership_and_insider_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("company_document_rag", tools)
        company_step = next(step for step in plan["steps"] if step["tool"] == "company_fundamentals")
        self.assertEqual("read-only", company_step["access"])

    def test_estimate_revision_question_uses_company_analysis_without_forcing_rag(self):
        plan = build_agent_plan(
            "Cisco ka current-quarter EPS estimate, revenue estimate aur 30-day revisions batao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("analyst_estimate_revision_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("company_document_rag", tools)
        self.assertNotIn("company_catalyst_analysis", plan["intents"])
        company_step = next(step for step in plan["steps"] if step["tool"] == "company_fundamentals")
        self.assertEqual("read-only", company_step["access"])

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

    def test_dividend_and_split_question_uses_read_only_company_evidence_without_rag(self):
        plan = build_agent_plan(
            "Cisco ka dividend history, payout ratio aur stock split history batao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("dividend_and_corporate_action_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("company_document_rag", tools)
        company_step = next(step for step in plan["steps"] if step["tool"] == "company_fundamentals")
        self.assertEqual("read-only", company_step["access"])

    def test_earnings_quality_question_uses_read_only_company_statements_without_rag(self):
        plan = build_agent_plan(
            "Cisco ki earnings quality, cash conversion aur capital allocation samjhao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("earnings_quality_and_capital_allocation_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("company_document_rag", tools)
        company_step = next(step for step in plan["steps"] if step["tool"] == "company_fundamentals")
        self.assertEqual("read-only", company_step["access"])

    def test_liquidity_and_debt_question_uses_read_only_company_statements_without_rag(self):
        plan = build_agent_plan(
            "Cisco ki liquidity, net debt, current ratio aur interest coverage batao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("liquidity_and_debt_capacity_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("company_document_rag", tools)
        company_step = next(step for step in plan["steps"] if step["tool"] == "company_fundamentals")
        self.assertEqual("read-only", company_step["access"])

    def test_profitability_returns_question_uses_read_only_company_statements_without_rag(self):
        plan = build_agent_plan(
            "Cisco ka ROE samjhao",
            "CSCO",
        )

        tools = [step["tool"] for step in plan["steps"]]
        self.assertIn("profitability_returns_and_efficiency_analysis", plan["intents"])
        self.assertIn("company_fundamentals", tools)
        self.assertNotIn("company_document_rag", tools)
        company_step = next(step for step in plan["steps"] if step["tool"] == "company_fundamentals")
        self.assertEqual("read-only", company_step["access"])

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
            patch("market_intelligence._provider_chat", side_effect=RuntimeError("offline")) as provider_chat,
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
        self.assertEqual(2, provider_chat.call_count)
        self.assertIn("company_document_rag", body["toolsUsed"])
        self.assertEqual("S1", body["citations"][0]["citation"])
        self.assertIn("[S1 p.98]", body["answer"])
        rag_trace = next(item for item in body["toolTrace"] if item["tool"] == "company_document_rag")
        self.assertEqual("completed", rag_trace["status"])
        self.assertEqual(1, rag_trace["evidenceCount"])


if __name__ == "__main__":
    unittest.main()
