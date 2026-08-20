import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd

from market_intelligence import (
    _build_analysis_brief,
    _extract_requested_date,
    _historical_session,
    _infer_symbol,
    _llm_grounding_issue,
    _verified_tool_answer,
)


class AgentAnalysisTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            "price": 24774.30,
            "changePercent": 1.67,
        }
        self.prediction = {
            "name": "Nifty 50",
            "outlook": "NEUTRAL",
            "probabilityUp": 53.3,
            "probabilityDown": 46.7,
            "dataAsOf": "2026-08-03T10:00:00+00:00",
            "expectedRange": {
                "low": 24508.78,
                "high": 25039.82,
                "currency": "INR",
            },
            "newsFactor": {
                "sentimentLabel": "mixed/neutral",
            },
            "model": {
                "balancedAccuracy": 51.6,
                "walkForwardFolds": 5,
                "quality": "weak",
            },
            "riskBenchmark": {
                "status": "available",
                "asset": {
                    "periodReturnPercent": 12.4,
                    "annualizedVolatilityPercent": 18.25,
                    "maxDrawdownPercent": -11.6,
                    "historicalVar95Percent": 1.72,
                },
                "benchmark": {"symbol": "^NSEI", "name": "Nifty 50"},
                "comparison": {
                    "relativeReturnPoints": 3.4,
                    "beta": 0.91,
                    "correlation": 0.76,
                    "trackingErrorPercent": 9.8,
                },
            },
        }

    def test_extracts_common_historical_date_formats(self):
        self.assertEqual(date(2026, 7, 15), _extract_requested_date("15 July 2026 ko Nifty kaisa tha?"))
        self.assertEqual(date(2026, 7, 15), _extract_requested_date("Nifty on 2026-07-15"))
        self.assertEqual(date(2026, 7, 15), _extract_requested_date("15/07/2026 market behaviour"))

    def test_explicitly_selected_company_is_not_replaced_by_benchmark_words(self):
        self.assertEqual(
            "RELIANCE.NS",
            _infer_symbol("Reliance ka beta Nifty benchmark ke against batao", "RELIANCE.NS"),
        )
        self.assertEqual("^NSEI", _infer_symbol("Nifty ka outlook", None))

    def test_historical_session_returns_transparent_arithmetic(self):
        frame = pd.DataFrame(
            {
                "Open": [99.0, 102.0, 104.0],
                "High": [102.0, 107.0, 106.0],
                "Low": [98.0, 101.0, 102.0],
                "Close": [101.0, 105.0, 103.0],
                "Volume": [1000, 1200, 1100],
            },
            index=pd.to_datetime(["2026-07-14", "2026-07-15", "2026-07-16"]),
        )
        with patch("market_intelligence._history", return_value=frame):
            result = _historical_session("^NSEI", date(2026, 7, 15))

        self.assertTrue(result["exactSession"])
        self.assertEqual("2026-07-15", result["sessionDate"])
        self.assertEqual(105.0, result["close"])
        self.assertAlmostEqual(3.96, result["changePercent"], places=2)
        self.assertEqual("2026-07-16", result["nextSession"]["date"])
        self.assertAlmostEqual(-1.90, result["nextSession"]["changePercent"], places=2)

    def test_analysis_brief_precalculates_range_scenarios(self):
        brief = _build_analysis_brief(self.snapshot, self.prediction)

        self.assertEqual(53.3, brief["probabilityUp"])
        self.assertEqual(46.7, brief["probabilityDown"])
        self.assertEqual(3.3, brief["distanceFromNeutralPoints"])
        self.assertAlmostEqual(-1.07, brief["expectedDownsidePercent"], places=2)
        self.assertAlmostEqual(1.07, brief["expectedUpsidePercent"], places=2)
        self.assertFalse(brief["modelHasReliableDirectionalEdge"])

    def test_verified_fallback_contains_analysis_sections_and_warning(self):
        answer = _verified_tool_answer(
            "Nifty ka scenario aur calculation samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction"],
            {"factors": []},
        )

        for heading in (
            "Verified figures",
            "Calculation aur scenario",
            "Assumptions aur confidence",
            "Final assessment",
        ):
            self.assertIn(heading, answer)
        self.assertNotIn("Seedha jawab", answer)
        self.assertIn("reliable directional edge nahi", answer)
        self.assertIn("53.3%", answer)
        self.assertIn("personalized buy/sell advice", answer)

    def test_verified_fallback_answers_risk_question_from_calculated_evidence(self):
        answer = _verified_tool_answer(
            "Nifty ka beta, drawdown aur historical VaR risk samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction"],
            {"factors": []},
        )

        self.assertIn("Historical risk and benchmark evidence", answer)
        self.assertIn("annualized volatility 18.25%", answer)
        self.assertIn("Maximum drawdown -11.6%", answer)
        self.assertIn("beta 0.91", answer)
        self.assertIn("future loss limit", answer)

    def test_generated_risk_answer_must_include_the_specifically_requested_beta(self):
        base_answer = (
            "Weak model warning. Annualized volatility is 18.25 percent and the Nifty 50 is the benchmark. "
            + ("Evidence-based explanation. " * 12)
        )
        issue = _llm_grounding_issue(
            base_answer,
            "Nifty benchmark risk aur beta samjhao",
            self.prediction,
            {"factors": []},
        )
        accepted = _llm_grounding_issue(
            base_answer + " Calculated beta is 0.91.",
            "Nifty benchmark risk aur beta samjhao",
            self.prediction,
            {"factors": []},
        )

        self.assertEqual("missing requested beta evidence", issue)
        self.assertIsNone(accepted)

    def test_concise_metric_explanation_can_pass_grounding(self):
        answer = (
            "Annualized volatility 18.25% batati hai ki historical returns kitne fluctuate hue. "
            "Nifty 50 benchmark ke saamne ise dekhein; weak model ka reliable directional edge nahi hai."
        )

        issue = _llm_grounding_issue(
            answer,
            "Benchmark volatility ka simple meaning kya hai?",
            self.prediction,
            {"factors": []},
        )

        self.assertIsNone(issue)

    def test_catalyst_fallback_labels_external_target_and_earnings_date(self):
        company = {
            "catalysts": {
                "status": "available",
                "events": [{
                    "type": "earnings", "label": "Earnings release",
                    "date": "2026-11-12", "status": "upcoming",
                }],
                "analystConsensus": {
                    "recommendation": "Buy", "analystCount": 22,
                    "targetMean": 132.59, "targetGapPercent": 18.33,
                },
                "surpriseSummary": {"reportedQuarters": 5, "beats": 5, "misses": 0},
            }
        }
        answer = _verified_tool_answer(
            "Next earnings date aur analyst price target batao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []},
            company_profile=company,
        )

        self.assertIn("2026-11-12", answer)
        self.assertIn("mean target 132.59", answer)
        self.assertIn("FinTrack ML prediction se separate", answer)

    def test_generated_catalyst_answer_must_include_requested_target_and_date(self):
        company = {
            "catalysts": {
                "events": [{"type": "earnings", "date": "2026-11-12"}],
                "analystConsensus": {"targetMean": 132.59},
            }
        }
        base = "Weak model warning with detailed evidence. " * 12
        issue = _llm_grounding_issue(
            base,
            "Next earnings date aur analyst target batao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + " External mean target 132.59 and earnings date 2026-11-12.",
            "Next earnings date aur analyst target batao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )

        self.assertEqual("missing requested analyst target evidence", issue)
        self.assertIsNone(accepted)

    def test_news_fallback_reports_distribution_sources_and_title_only_boundary(self):
        news = {
            "intelligence": {
                "status": "available", "sentimentLabel": "positive", "sentimentScore": 0.22,
                "articleCount": 5, "sourceCount": 3, "coverage": "moderate", "freshness": "fresh",
                "distribution": {"positive": 3, "mixed/neutral": 1, "negative": 1},
                "themes": [{"theme": "Earnings & outlook", "articleCount": 2}],
            },
            "articles": [{
                "title": "Cisco beats earnings expectations", "publisher": "Evidence Wire",
                "publishedAt": "2026-08-14T08:00:00Z", "sentimentLabel": "positive",
            }],
        }
        answer = _verified_tool_answer(
            "Cisco recent news sentiment and themes batao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "market_news"],
            {"factors": []},
            news_payload=news,
        )

        self.assertIn("Company headline intelligence", answer)
        self.assertIn("3 positive, 1 mixed/neutral, 1 negative", answer)
        self.assertIn("5 headlines from 3 publishers", answer)
        self.assertIn("title-keyword evidence", answer)

    def test_generated_news_answer_must_include_grounded_tone_and_requested_theme(self):
        news = {
            "intelligence": {
                "status": "available", "sentimentLabel": "positive",
                "themes": [{"theme": "Earnings & outlook", "articleCount": 3}],
            }
        }
        base = "Weak model warning with detailed evidence and source limitations. " * 10
        issue = _llm_grounding_issue(
            base,
            "Recent news sentiment and theme batao",
            self.prediction,
            {"factors": []},
            news_payload=news,
        )
        accepted = _llm_grounding_issue(
            base + " Headline sentiment is positive and the leading theme is Earnings & outlook.",
            "Recent news sentiment and theme batao",
            self.prediction,
            {"factors": []},
            news_payload=news,
        )

        self.assertEqual("missing requested headline sentiment evidence", issue)
        self.assertIsNone(accepted)

    def test_financial_trend_fallback_reports_period_growth_cash_flow_and_leverage(self):
        company = {
            "financialTrends": {
                "status": "available",
                "annual": [{
                    "period": "2025-03-31", "revenue": 150.0, "revenueYoYPercent": 25.0,
                    "netIncome": 18.0, "netIncomeYoYPercent": 50.0,
                }],
                "summary": {
                    "latestAnnualPeriod": "2025-03-31", "revenueCagrPercent": 22.47,
                    "revenueTrend": "growing", "netIncomeTrend": "growing",
                    "latestOperatingMarginPercent": 16.67, "operatingMarginChangePoints": 1.67,
                    "latestFreeCashFlow": 16.0, "freeCashFlowTrend": "growing",
                    "latestDebtToEquityRatio": 0.6, "latestDebtYoYPercent": -6.25,
                },
            }
        }
        answer = _verified_tool_answer(
            "Revenue CAGR, margin aur free cash flow trend samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []},
            company_profile=company,
        )

        self.assertIn("Financial statement trend evidence", answer)
        self.assertIn("Latest annual period 2025-03-31", answer)
        self.assertIn("multi-year CAGR 22.47%", answer)
        self.assertIn("debt/equity 0.6x", answer)
        self.assertIn("not estimates", answer)

    def test_generated_financial_trend_answer_requires_latest_period_and_direction(self):
        company = {
            "financialTrends": {
                "status": "available",
                "summary": {"latestAnnualPeriod": "2025-03-31", "revenueTrend": "growing"},
            }
        }
        base = "Weak model warning with statement source and calculation limitations. " * 10
        issue = _llm_grounding_issue(
            base,
            "Revenue CAGR aur trend samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        missing_boundary = _llm_grounding_issue(
            base + " Latest annual period 2025-03-31 shows a growing revenue trend.",
            "Revenue CAGR aur trend samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + " Latest annual period 2025-03-31 shows a growing revenue trend. Provider statements may be restated and this is not an accounting audit.",
            "Revenue CAGR aur trend samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )

        self.assertEqual("missing latest financial statement period", issue)
        self.assertEqual("missing financial statement evidence boundary", missing_boundary)
        self.assertIsNone(accepted)

    def test_ownership_fallback_reports_concentration_partial_coverage_and_insider_activity(self):
        company = {
            "ownershipIntelligence": {
                "status": "available",
                "majorOwnership": {
                    "insidersPercentHeld": 0.05,
                    "institutionsPercentHeld": 84.2,
                    "institutionsFloatPercentHeld": 84.24,
                    "institutionsCount": 5086,
                },
                "concentration": {
                    "returnedInstitutionCount": 2,
                    "topInstitutionsPercentHeld": 18.5,
                    "returnedFundCount": 0,
                    "topFundsPercentHeld": 0.0,
                },
                "institutionalHolders": [{
                    "holder": "Evidence Asset Management", "percentHeld": 11.5,
                    "shares": 500000000, "dateReported": "2026-06-30",
                }],
                "mutualFundHolders": [],
                "insiderSummary": {
                    "netActivity": "net selling", "purchaseShares": 8836,
                    "purchaseTransactions": 8, "saleShares": 122115,
                    "saleTransactions": 18, "netSharesPurchased": -113279,
                    "netSharesPercent": -5.4,
                },
                "recentInsiderTransactions": [{
                    "date": "2026-05-20", "insider": "Example Officer", "position": "CFO",
                    "type": "sale", "shares": 5000,
                }],
            }
        }
        answer = _verified_tool_answer(
            "Cisco ke institutional holders, ownership concentration aur insider buying selling samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []},
            company_profile=company,
        )

        self.assertIn("Ownership and insider activity evidence", answer)
        self.assertIn("institutions 84.2%", answer)
        self.assertIn("top 2 institution rows total 18.5%", answer)
        self.assertIn("Mutual-fund holder rows provider ne return nahi kiye", answer)
        self.assertIn("net selling", answer)
        self.assertIn("not a standalone bullish/bearish signal", answer)

    def test_generated_ownership_answer_requires_percentage_activity_and_boundary(self):
        company = {
            "ownershipIntelligence": {
                "status": "available",
                "majorOwnership": {"institutionsPercentHeld": 84.2},
                "insiderSummary": {"netActivity": "net selling"},
            }
        }
        base = "Weak model warning with detailed provider evidence and calculation context. " * 9
        missing_percent = _llm_grounding_issue(
            base + "Insider activity shows net selling and reporting may be delayed.",
            "Institutional ownership aur insider activity samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        missing_activity = _llm_grounding_issue(
            base + "Institutional ownership is 84.2 percent and reports may be delayed.",
            "Institutional ownership aur insider activity samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        missing_boundary = _llm_grounding_issue(
            base + "Institutional ownership is 84.2 percent and insider activity is net selling.",
            "Institutional ownership aur insider activity samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + "Institutional ownership is 84.2 percent and insider activity is net selling. Holder reports may be delayed and this is not a standalone trading signal.",
            "Institutional ownership aur insider activity samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )

        self.assertEqual("missing requested institutional ownership evidence", missing_percent)
        self.assertEqual("missing requested insider net activity evidence", missing_activity)
        self.assertEqual("missing ownership evidence boundary", missing_boundary)
        self.assertIsNone(accepted)

    def test_estimate_revision_fallback_reports_ranges_breadth_and_basis_warning(self):
        company = {
            "analystEstimateIntelligence": {
                "status": "available",
                "summary": {
                    "currentQuarterEpsAverage": 1.25,
                    "currentQuarterEpsGrowthPercent": 25.0,
                    "currentQuarterRevenueAverage": 12_000_000_000,
                    "currentQuarterRevenueGrowthPercent": 20.0,
                    "currentQuarterAnalystCount": 12,
                    "currentQuarterRevisionSignal": "net upward",
                    "currentQuarterNetRevisions30Days": 6,
                    "periodsWithBasisMismatch": ["+1y"],
                },
                "periods": [{
                    "period": "0q", "label": "Current quarter",
                    "eps": {"average": 1.25, "low": 1.1, "high": 1.4, "analystCount": 12, "growthPercent": 25.0},
                    "revenue": {"average": 12_000_000_000, "low": 11_500_000_000, "high": 12_500_000_000, "growthPercent": 20.0},
                    "revisionCounts": {"signal": "net upward", "upLast7Days": 3, "downLast7Days": 1, "upLast30Days": 8, "downLast30Days": 2, "netLast30Days": 6},
                    "epsTrend": {"change30Days": 0.05},
                }],
            }
        }
        answer = _verified_tool_answer(
            "Current-quarter EPS estimate, revenue estimate aur revision trend samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []},
            company_profile=company,
        )

        self.assertIn("Analyst estimates and revision evidence", answer)
        self.assertIn("EPS average 1.25", answer)
        self.assertIn("Revision breadth: net upward", answer)
        self.assertIn("basis published estimate range", answer)
        self.assertIn("not company guidance", answer)

    def test_generated_estimate_answer_requires_eps_revision_basis_and_boundary(self):
        company = {
            "analystEstimateIntelligence": {
                "status": "available",
                "summary": {
                    "currentQuarterEpsAverage": 1.25,
                    "currentQuarterRevisionSignal": "net upward",
                    "periodsWithBasisMismatch": ["+1y"],
                },
            }
        }
        base = "Weak model warning with detailed estimate evidence and analytical explanation. " * 9
        missing_eps = _llm_grounding_issue(
            base + "Revisions are net upward; a basis mismatch is present; external analyst estimates can change.",
            "EPS estimate revision trend batao", self.prediction, {"factors": []}, company_profile=company,
        )
        missing_revision = _llm_grounding_issue(
            base + "Current-quarter EPS is 1.25; a basis mismatch is present; external analyst estimates can change.",
            "EPS estimate revision trend batao", self.prediction, {"factors": []}, company_profile=company,
        )
        missing_basis = _llm_grounding_issue(
            base + "Current-quarter EPS is 1.25 and revisions are net upward; external analyst estimates can change.",
            "EPS estimate revision trend batao", self.prediction, {"factors": []}, company_profile=company,
        )
        missing_boundary = _llm_grounding_issue(
            base + "Current-quarter EPS is 1.25, revisions are net upward and the trend basis is incompatible.",
            "EPS estimate revision trend batao", self.prediction, {"factors": []}, company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + "Current-quarter EPS is 1.25, revisions are net upward and the trend basis is incompatible. External analyst estimates can change and are not company guidance.",
            "EPS estimate revision trend batao", self.prediction, {"factors": []}, company_profile=company,
        )

        self.assertEqual("missing requested current-quarter EPS estimate", missing_eps)
        self.assertEqual("missing requested estimate revision direction", missing_revision)
        self.assertEqual("missing EPS trend basis mismatch warning", missing_basis)
        self.assertEqual("missing analyst-estimate evidence boundary", missing_boundary)
        self.assertIsNone(accepted)

    def test_dividend_fallback_reports_ttm_growth_yield_split_and_boundaries(self):
        company = {
            "corporateActionIntelligence": {
                "status": "available", "currency": "USD",
                "snapshot": {"currentYieldPercent": 1.48, "payoutRatioPercent": 49.85},
                "summary": {
                    "trailing12MonthTotalPerShare": 1.67,
                    "previous12MonthTotalPerShare": 1.63,
                    "trailingChangePercent": 2.45, "paymentsLast12Months": 4,
                    "completedYearDividendCagrPercent": 2.57,
                    "completedYearCagrStart": 2021, "completedYearCagrEnd": 2025,
                    "latestSplitRatio": "2-for-1",
                },
                "annualDividends": [{
                    "year": 2026, "totalPerShare": 1.25, "paymentCount": 3,
                    "isPartialYear": True, "changePercent": None,
                }],
                "recentSplits": [{"date": "2000-03-23", "displayRatio": "2-for-1"}],
                "recentCapitalGains": [], "upcomingEvents": [],
            }
        }
        answer = _verified_tool_answer(
            "Dividend history, dividend yield, payout ratio aur split history batao",
            self.snapshot, self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []}, company_profile=company,
        )

        self.assertIn("Dividend and corporate-action evidence", answer)
        self.assertIn("1.67 USD per share", answer)
        self.assertIn("Current yield 1.48%", answer)
        self.assertIn("2-for-1 split", answer)
        self.assertIn("partial calendar year", answer)
        self.assertIn("Historical distributions are not guaranteed", answer)

    def test_generated_dividend_answer_requires_requested_values_and_boundary(self):
        company = {
            "corporateActionIntelligence": {
                "status": "available",
                "snapshot": {"currentYieldPercent": 1.48, "payoutRatioPercent": 49.85},
                "summary": {
                    "trailing12MonthTotalPerShare": 1.67,
                    "latestSplitRatio": "2-for-1",
                },
            }
        }
        base = "Weak model warning with detailed provider evidence and calculation context. " * 9
        issue = _llm_grounding_issue(
            base + "Yield is 1.48%, payout is 49.85%, latest split 2-for-1. Historical distributions are not guaranteed.",
            "Dividend history, dividend yield, payout ratio aur split history batao",
            self.prediction, {"factors": []}, company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + "TTM dividend is 1.67, yield is 1.48%, payout is 49.85%, latest split 2-for-1. Historical distributions are not guaranteed.",
            "Dividend history, dividend yield, payout ratio aur split history batao",
            self.prediction, {"factors": []}, company_profile=company,
        )

        self.assertEqual("missing requested trailing dividend evidence", issue)
        self.assertIsNone(accepted)

    def test_earnings_quality_fallback_reports_conversion_allocation_and_boundary(self):
        company = {
            "earningsQualityIntelligence": {
                "status": "available", "currency": "USD", "financialSectorCaution": False,
                "summary": {
                    "latestPeriod": "2025-07-31",
                    "latestOperatingCashConversionPercent": 131.42,
                    "latestFreeCashFlowConversionPercent": 123.04,
                    "latestEarningsCashGap": 3_393_000_000,
                    "latestCapitalExpenditure": 905_000_000,
                    "latestCapitalExpenditureToOperatingCashFlowPercent": 6.38,
                    "latestShareholderCashReturns": 13_659_000_000,
                    "latestShareholderReturnsToFreeCashFlowPercent": 102.8,
                    "latestFreeCashFlowAfterShareholderReturns": -371_000_000,
                    "latestNetCommonStockIssuance": -6_486_000_000,
                    "latestNetDebtIssuance": -2_812_000_000,
                    "positiveFreeCashFlowPeriods": 4, "freeCashFlowPeriodCount": 4,
                },
                "annual": [{
                    "period": "2025-07-31", "netIncome": 10_800_000_000,
                    "operatingCashFlow": 14_193_000_000, "operatingCashConversionPercent": 131.42,
                    "freeCashFlow": 13_288_000_000, "shareholderCashReturns": 13_659_000_000,
                }],
            }
        }
        answer = _verified_tool_answer(
            "Earnings quality, cash conversion aur capital allocation samjhao",
            self.snapshot, self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []}, company_profile=company,
        )

        self.assertIn("Earnings quality and capital-allocation evidence", answer)
        self.assertIn("operating-cash conversion 131.42%", answer)
        self.assertIn("13.66B USD", answer)
        self.assertIn("not an accounting-quality score", answer)

    def test_generated_earnings_quality_answer_requires_conversion_returns_and_boundary(self):
        company = {
            "earningsQualityIntelligence": {
                "status": "available", "currency": "USD", "financialSectorCaution": False,
                "summary": {
                    "latestOperatingCashConversionPercent": 131.42,
                    "latestShareholderCashReturns": 13_659_000_000,
                },
            }
        }
        base = "Weak model warning with detailed provider statement evidence and calculations. " * 9
        missing = _llm_grounding_issue(
            base + "Operating cash conversion is 131.42%. Statements can be restated.",
            "Earnings quality, cash conversion aur capital allocation samjhao",
            self.prediction, {"factors": []}, company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + "Operating cash conversion is 131.42% and shareholder cash returns are 13.66B USD. This is descriptive, not an accounting-quality score.",
            "Earnings quality, cash conversion aur capital allocation samjhao",
            self.prediction, {"factors": []}, company_profile=company,
        )

        self.assertEqual("missing requested shareholder cash-return evidence", missing)
        self.assertIsNone(accepted)

    def test_liquidity_fallback_reports_basis_ratios_mismatch_and_boundary(self):
        company = {
            "liquidityDebtIntelligence": {
                "status": "available", "currency": "USD", "financialSectorCaution": False,
                "summary": {
                    "latestPeriod": "2025-07-31", "latestLiquidFunds": 16_110_000_000,
                    "latestLiquidityBasis": "cash, cash equivalents and short-term investments",
                    "latestTotalDebt": 28_093_000_000, "latestDebtAfterLiquidFunds": 11_983_000_000,
                    "latestBalancePosition": "net debt after liquid funds", "latestCurrentRatio": 0.998,
                    "latestWorkingCapital": -78_000_000, "latestLiquidFundsToDebtPercent": 57.34,
                    "latestTotalDebtToEquityRatio": 0.6, "latestTotalDebtToAssetsPercent": 22.97,
                    "latestInterestCoverageRatio": 7.968, "latestDebtToEbitdaRatio": 1.812,
                    "liquidFundsTrend": "mixed", "totalDebtTrend": "mixed",
                    "providerNetDebtBasisMismatchPeriods": ["2025-07-31"],
                },
                "annual": [{
                    "period": "2025-07-31", "liquidFunds": 16_110_000_000,
                    "liquidityBasis": "cash, cash equivalents and short-term investments",
                    "totalDebt": 28_093_000_000, "debtAfterLiquidFunds": 11_983_000_000,
                    "currentRatio": 0.998,
                }],
            }
        }
        answer = _verified_tool_answer(
            "Liquidity, net debt, current ratio aur interest coverage batao",
            self.snapshot, self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []}, company_profile=company,
        )

        self.assertIn("Balance-sheet liquidity and debt-capacity evidence", answer)
        self.assertIn("16.11B USD", answer)
        self.assertIn("debt after liquid funds 11.98B USD", answer)
        self.assertIn("interest coverage 7.968x", answer)
        self.assertIn("basis differs", answer)
        self.assertIn("not a credit rating", answer)

    def test_generated_liquidity_answer_requires_values_basis_warning_and_boundary(self):
        company = {
            "liquidityDebtIntelligence": {
                "status": "available", "currency": "USD", "financialSectorCaution": False,
                "summary": {
                    "latestLiquidFunds": 16_110_000_000, "latestDebtAfterLiquidFunds": 11_983_000_000,
                    "latestCurrentRatio": 0.998, "latestInterestCoverageRatio": 7.968,
                    "providerNetDebtBasisMismatchPeriods": ["2025-07-31"],
                },
            }
        }
        base = "Weak model warning with detailed provider statement calculations. " * 9
        missing_basis = _llm_grounding_issue(
            base + "Liquid funds are 16.11B USD, debt after liquid funds 11.98B USD, current ratio 0.998 and interest coverage 7.968. Statements can be restated.",
            "Liquidity, net debt, current ratio aur interest coverage batao",
            self.prediction, {"factors": []}, company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + "Liquid funds are 16.11B USD, debt after liquid funds 11.98B USD, current ratio 0.998 and interest coverage 7.968. Provider net debt uses a different basis and is kept separate. This is not a credit rating.",
            "Liquidity, net debt, current ratio aur interest coverage batao",
            self.prediction, {"factors": []}, company_profile=company,
        )

        self.assertEqual("missing provider net-debt basis warning", missing_basis)
        self.assertIsNone(accepted)


    def test_profitability_returns_fallback_reports_margins_returns_and_method_boundary(self):
        company = {
            "profitabilityReturnsIntelligence": {
                "status": "available",
                "currency": "USD",
                "financialSectorCaution": False,
                "annual": [{
                    "period": "2025-12-31", "grossMarginPercent": 44.0,
                    "operatingMarginPercent": 16.0, "netMarginPercent": 12.0,
                    "returnOnAssetsPercent": 13.33, "returnOnEquityPercent": 26.67,
                    "returnOnInvestedCapitalPercent": 22.09, "assetTurnoverRatio": 1.111,
                }],
                "summary": {
                    "latestPeriod": "2025-12-31", "latestGrossMarginPercent": 44.0,
                    "latestOperatingMarginPercent": 16.0, "latestNetMarginPercent": 12.0,
                    "latestReturnOnAssetsPercent": 13.33, "latestReturnOnEquityPercent": 26.67,
                    "latestReturnOnInvestedCapitalPercent": 22.09,
                    "latestAssetTurnoverRatio": 1.111, "latestEquityMultiplierRatio": 2.0,
                    "latestEffectiveTaxRatePercent": 25.0, "operatingMarginTrend": "growing",
                },
            }
        }
        answer = _verified_tool_answer(
            "ROE, ROIC, gross margin aur asset turnover samjhao",
            self.snapshot,
            self.prediction,
            ["market_snapshot", "technical_prediction", "company_fundamentals"],
            {"factors": []},
            company_profile=company,
        )

        self.assertIn("Profitability, returns and capital-efficiency evidence", answer)
        self.assertIn("ROE 26.67%", answer)
        self.assertIn("industrial ROIC 22.09%", answer)
        self.assertIn("gross margin 44.0%", answer)
        self.assertIn("average beginning and ending balances", answer)
        self.assertIn("not a profitability score", answer)

    def test_generated_profitability_answer_requires_requested_values_and_boundary(self):
        company = {
            "profitabilityReturnsIntelligence": {
                "status": "available",
                "financialSectorCaution": False,
                "summary": {
                    "latestReturnOnEquityPercent": 26.67,
                    "latestReturnOnInvestedCapitalPercent": 22.09,
                    "latestGrossMarginPercent": 44.0,
                },
            }
        }
        base = "Weak model warning with detailed provider calculation evidence. " * 10
        missing_value = _llm_grounding_issue(
            base + "ROE is 26.67 percent and gross margin is 44 percent.",
            "ROE, ROIC aur gross margin samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        missing_boundary = _llm_grounding_issue(
            base + "ROE is 26.67 percent, ROIC is 22.09 percent and gross margin is 44 percent.",
            "ROE, ROIC aur gross margin samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )
        accepted = _llm_grounding_issue(
            base + "ROE is 26.67 percent, ROIC is 22.09 percent and gross margin is 44 percent. Return ratios use average beginning and ending balances and are not a profitability score.",
            "ROE, ROIC aur gross margin samjhao",
            self.prediction,
            {"factors": []},
            company_profile=company,
        )

        self.assertEqual("missing requested return-on-invested-capital evidence", missing_value)
        self.assertEqual("missing profitability/returns evidence boundary", missing_boundary)
        self.assertIsNone(accepted)


if __name__ == "__main__":
    unittest.main()
