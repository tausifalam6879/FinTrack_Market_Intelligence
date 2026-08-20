"""Deterministic, read-only tool planning for the FinTrack research agent."""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Dict, List, Optional


TOOL_CATALOG: Dict[str, Dict[str, str]] = {
    "market_snapshot": {
        "label": "Current market snapshot",
        "evidenceType": "live_market_data",
        "source": "Yahoo Finance via yfinance",
    },
    "technical_prediction": {
        "label": "ML, technical and risk evidence",
        "evidenceType": "probabilistic_model",
        "source": "FinTrack model service",
    },
    "historical_market_session": {
        "label": "Historical session lookup",
        "evidenceType": "historical_market_data",
        "source": "Yahoo Finance via yfinance",
    },
    "company_fundamentals": {
        "label": "Company and fundamental profile",
        "evidenceType": "company_market_profile",
        "source": "Yahoo Finance via yfinance",
    },
    "sector_peer_comparison": {
        "label": "Dynamic sector peer comparison",
        "evidenceType": "relative_company_market_evidence",
        "source": "Yahoo Finance equity screener via yfinance",
    },
    "company_document_rag": {
        "label": "Indexed company-document retrieval",
        "evidenceType": "cited_document_chunks",
        "source": "FinTrack trusted document index",
    },
    "market_news": {
        "label": "Recent market headlines",
        "evidenceType": "publisher_headlines",
        "source": "Yahoo Finance publisher feed",
    },
    "macro_market_factors": {
        "label": "Macro and cross-asset factors",
        "evidenceType": "macro_market_data",
        "source": "Yahoo Finance via yfinance",
    },
    "market_breadth": {
        "label": "India watchlist breadth",
        "evidenceType": "computed_market_breadth",
        "source": "FinTrack liquid India watchlist",
    },
    "global_market_overview": {
        "label": "Global index overview",
        "evidenceType": "global_market_data",
        "source": "Yahoo Finance via yfinance",
    },
}


def _contains(message: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in message for phrase in phrases)


def build_agent_plan(
    message: str,
    symbol: str,
    requested_date: Optional[date] = None,
    *,
    is_index: bool = False,
) -> Dict[str, Any]:
    """Select a bounded set of read-only tools from user intent.

    Tool choice is deliberately deterministic and occurs outside the LLM. This
    keeps the public agent auditable and prevents a prompt from inventing or
    invoking mutation-capable tools.
    """
    lowered = " ".join(str(message or "").lower().split())
    intents: List[str] = []
    reasons: Dict[str, str] = {}

    def add_intent(intent: str) -> None:
        if intent not in intents:
            intents.append(intent)

    def require(tool: str, reason: str) -> None:
        reasons.setdefault(tool, reason)

    comprehensive = _contains(lowered, (
        "overall", "complete analysis", "full analysis", "deep analysis",
        "research karo", "analyse karo", "analyze karo", "poora analysis",
    ))
    document_request = _contains(lowered, (
        "annual report", "annual reports", "10-k", "10k", "filing", "document",
        "management discussion", "investor presentation",
        "page citation", "source citation", "report me", "report mein", "debt ke",
    )) or bool(re.search(r"\brag\b", lowered))
    news_request = _contains(lowered, (
        "news", "headline", "announcement", "sentiment", "latest update", "war",
    ))
    macro_request = _contains(lowered, (
        "macro", "factor", "gold", "oil", "crude", "rupee", "dollar", "yield", "vix",
        "bitcoin", "inflation",
    ))
    breadth_request = _contains(lowered, (
        "gainer", "loser", "breadth", "advance", "decline", "most active", "top stock",
    ))
    global_request = _contains(lowered, (
        "world market", "global market", "global indices", "major indices", "us market",
        "asian market", "europe market",
    ))
    company_request = _contains(lowered, (
        "fundamental", "valuation", "market cap", "p/e", " pe ", "sector", "industry",
        "business", "company profile", "performance", "revenue", "profit", "debt",
        "earnings date", "earnings calendar", "next earnings", "analyst", "price target",
        "target price", "consensus", "ex-dividend", "ex dividend", "eps surprise", "catalyst",
        "financial statement", "cash flow", "free cash flow", "margin", "year over year",
        "yoy", "cagr", "annual", "quarterly",
        "ownership", "shareholding", "shareholders", "institutional holder", "institutional holding",
        "mutual fund holder", "fund holding", "insider transaction", "insider buying", "insider selling",
        "insider activity", "promoter holding", "top holder", "ownership concentration",
        "analyst estimate", "earnings estimate", "eps estimate", "revenue estimate",
        "estimate revision", "estimate revisions", "eps revision", "eps revisions",
        "estimate trend", "earnings outlook", "consensus eps", "consensus revenue",
        "upward revision", "downward revision", "revision breadth",
        "dividend history", "dividend growth", "dividend yield", "payout ratio",
        "dividend consistency", "distribution history", "corporate action", "stock split",
        "split history", "capital gain distribution", "dividend payment", "trailing dividend",
        "earnings quality", "cash conversion", "profit to cash", "operating cash conversion",
        "fcf conversion", "free cash flow conversion", "capital allocation", "buyback",
        "share repurchase", "stock repurchase", "stock issuance", "share issuance",
        "debt repayment", "debt issuance", "cash deployment", "shareholder return",
        "balance sheet health", "balance sheet strength", "liquidity", "liquidity trend",
        "cash position", "cash balance", "net debt", "debt capacity", "debt trend",
        "working capital", "current ratio", "interest coverage", "debt to ebitda",
        "debt to equity", "debt to assets", "cash to debt", "leverage trend",
        "profitability", "return on equity", " roe ", "return on assets", " roa ",
        "return on invested capital", " roic ", "gross margin", "net margin",
        "asset turnover", "capital efficiency", "equity multiplier", "dupont", "du pont",
        "effective tax rate", "return ratio", "return ratios",
    ))
    catalyst_request = _contains(lowered, (
        "earnings date", "earnings calendar", "next earnings", "analyst rating", "analyst recommendation", "price target",
        "target price", "consensus", "ex-dividend", "ex dividend", "eps surprise", "catalyst",
    ))
    financial_trend_request = _contains(lowered, (
        "financial statement", "revenue trend", "profit trend", "cash flow trend", "free cash flow",
        "margin trend", "year over year", "yoy", "cagr", "annual revenue", "quarterly revenue",
        "debt trend",
    ))
    ownership_request = _contains(lowered, (
        "ownership", "shareholding", "shareholders", "institutional holder", "institutional holding",
        "mutual fund holder", "fund holding", "insider transaction", "insider buying", "insider selling",
        "insider activity", "promoter holding", "top holder", "ownership concentration",
    ))
    estimate_revision_request = _contains(lowered, (
        "analyst estimate", "earnings estimate", "eps estimate", "revenue estimate",
        "estimate revision", "estimate revisions", "eps revision", "eps revisions",
        "estimate trend", "earnings outlook", "consensus eps", "consensus revenue",
        "upward revision", "downward revision", "revision breadth",
    ))
    dividend_action_request = _contains(lowered, (
        "dividend history", "dividend growth", "dividend yield", "payout ratio",
        "dividend consistency", "distribution history", "corporate action", "stock split",
        "split history", "capital gain distribution", "ex-dividend", "ex dividend",
        "dividend payment", "trailing dividend",
    ))
    earnings_quality_request = _contains(lowered, (
        "earnings quality", "cash conversion", "profit to cash", "operating cash conversion",
        "fcf conversion", "free cash flow conversion", "capital allocation", "buyback",
        "share repurchase", "stock repurchase", "stock issuance", "share issuance",
        "debt repayment", "debt issuance", "cash deployment", "shareholder return",
    ))
    liquidity_debt_request = _contains(lowered, (
        "balance sheet health", "balance sheet strength", "liquidity", "liquidity trend",
        "cash position", "cash balance", "net debt", "debt capacity", "debt trend",
        "working capital", "current ratio", "interest coverage", "debt to ebitda",
        "debt to equity", "debt to assets", "cash to debt", "leverage trend",
    ))
    padded_lowered = f" {lowered} "
    profitability_return_request = _contains(padded_lowered, (
        " profitability", " return on equity", " roe ", " return on assets", " roa ",
        " return on invested capital", " roic ", " gross margin", " net margin",
        " asset turnover", " capital efficiency", " equity multiplier", " dupont", " du pont",
        " effective tax rate", " return ratio", " return ratios",
    )) or bool(re.search(r"\b(?:roe|roa|roic)\b", lowered))
    model_request = _contains(lowered, (
        "prediction", "forecast", "outlook", "bullish", "bearish", "next session", "model",
        "probability", "kal", "tomorrow",
    ))
    technical_request = _contains(lowered, (
        "technical", "rsi", "sma", "volatility", "expected range", "support", "resistance",
    ))
    peer_request = _contains(lowered, (
        "peer", "peers", "comparable", "competitor", "competitors", "sector comparison",
        "compare valuation", "valuation comparison", "relative valuation", "sector median",
        "similar company", "similar companies",
    ))
    risk_request = _contains(lowered, (
        "risk", "benchmark", "beta", "correlation", "drawdown", "tracking error",
        "historical var", "value at risk",
        "relative return", "outperform", "underperform", "broad market",
        "market comparison", "behaved versus",
    )) or " var " in f" {lowered} "

    # Every market-agent response is anchored to the selected symbol and model
    # context, so follow-up questions cannot silently drift to a different asset.
    require("market_snapshot", "Anchor the response to the selected asset and current timestamped quote.")
    require("technical_prediction", "Keep probabilistic model context and its limitations available.")
    add_intent("current_market_context")

    if model_request or technical_request or comprehensive:
        add_intent("model_and_technical_analysis")
    if risk_request or comprehensive:
        add_intent("risk_and_benchmark_analysis")
    if requested_date:
        add_intent("historical_date_analysis")
        require("historical_market_session", f"Look up the requested date {requested_date.isoformat()} without using today's data.")
    if not is_index and (company_request or document_request or profitability_return_request or comprehensive):
        add_intent("company_research")
        require("company_fundamentals", "Provide company identity and available market-profile fundamentals.")
    if not is_index and (catalyst_request or comprehensive):
        add_intent("company_catalyst_analysis")
    if not is_index and (financial_trend_request or comprehensive):
        add_intent("financial_statement_trend_analysis")
    if not is_index and (ownership_request or comprehensive):
        add_intent("ownership_and_insider_analysis")
    if not is_index and (estimate_revision_request or comprehensive):
        add_intent("analyst_estimate_revision_analysis")
    if not is_index and (dividend_action_request or comprehensive):
        add_intent("dividend_and_corporate_action_analysis")
    if not is_index and (earnings_quality_request or comprehensive):
        add_intent("earnings_quality_and_capital_allocation_analysis")
    if not is_index and (liquidity_debt_request or comprehensive):
        add_intent("liquidity_and_debt_capacity_analysis")
    if not is_index and (profitability_return_request or comprehensive):
        add_intent("profitability_returns_and_efficiency_analysis")
    if not is_index and (peer_request or comprehensive):
        add_intent("sector_peer_analysis")
        require("sector_peer_comparison", "Compare the company with dynamically discovered same-sector, same-market peers.")
    if not is_index and document_request:
        add_intent("document_research")
        require("company_document_rag", "Retrieve only indexed company evidence with page/source citations.")
    if news_request or comprehensive:
        add_intent("news_analysis")
        require("market_news", "Use recent publisher headlines requested by the user.")
    if macro_request or comprehensive:
        add_intent("macro_analysis")
        require("macro_market_factors", "Evaluate requested cross-asset and macro drivers.")
    if breadth_request:
        add_intent("market_breadth_analysis")
        require("market_breadth", "Compute advances, declines, gainers and losers from the declared watchlist.")
    if global_request:
        add_intent("global_market_comparison")
        require("global_market_overview", "Compare the requested major global indices.")

    if len(intents) == 1 and not any((model_request, technical_request)):
        add_intent("general_market_research")
        if not is_index:
            require("company_fundamentals", "Add basic company context for an otherwise general question.")
        require("market_news", "Add recent headlines for a general research answer.")

    ordered_tools = [tool for tool in TOOL_CATALOG if tool in reasons]
    return {
        "planner": "deterministic-read-only-v1",
        "strategy": "plan_execute_synthesize",
        "symbol": symbol,
        "intents": intents,
        "steps": [
            {
                "step": index + 1,
                "tool": tool,
                **TOOL_CATALOG[tool],
                "reason": reasons[tool],
                "access": "read-only",
            }
            for index, tool in enumerate(ordered_tools)
        ],
        "safety": {
            "llmChoosesTools": False,
            "mutationToolsAvailable": False,
            "publicAuthenticationRequired": False,
        },
    }


def tool_trace(plan: Dict[str, Any], outcomes: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    trace = []
    for step in plan.get("steps", []):
        outcome = outcomes.get(step["tool"], {})
        trace.append({
            **step,
            "status": outcome.get("status", "completed"),
            "evidenceCount": int(outcome.get("evidenceCount") or 0),
            **({"message": outcome["message"]} if outcome.get("message") else {}),
        })
    return trace
