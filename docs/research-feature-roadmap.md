# Research feature additions

This tracks the requested research extensions without rebuilding existing capabilities.

| Requested feature | Existing capability | Remaining work |
| --- | --- | --- |
| Portfolio and watchlist | Holdings, currency totals, sector allocation, highest/lowest returns, timestamps and unrealized P/L | Transaction ledger and corporate-action reconciliation are not implemented |
| ML explainability | Diagnostic feature importance plus existing per-prediction counterfactual sensitivity and probability path UI | SHAP is not implemented; existing sensitivity is not SHAP and should not be relabelled |
| Backtesting | Added fixed logistic-model expanding training, next-open execution, costs, drawdown, benchmark and training audit | User-selected date windows, adjusted execution prices and richer curve visualization |
| Smart alerts | Added persistent browser rules for per-company price, RSI and rise probability, checked while app is open, with optional browser notifications | Crossing/event rules and closed-browser/email scheduling require further implementation and delivery configuration |
| Research reports | Added 13-section evidence report, optional existing-agent explanation, sources and report-only Print / Save PDF | More detailed statement-period comparisons and richer cited narrative |
| Portfolio risk | Added current-weight historical simulation, volatility, drawdown, sector concentration and historical 95% loss quantile | Adjusted prices and actual transaction-history analytics |
| Correlation matrix | Added multi-holding return correlations on common dates | Longer histories and date-window selection |
| Model performance dashboard | Registry, experiments, drift and outcome panels | Review time-series performance visualization gaps |
| Prediction confidence | Calibration and neutral thresholds; added separation from 50% alongside measured balanced accuracy | No unvalidated probability-to-confidence label mapping |
| Event impact | User-selected windows, benchmark comparison and provider calendar/reported earnings date suggestions; invalid dates filtered, future events disabled and stale results cleared | Independent announcement verification and after-hours release handling; provider dates are not independently verified |
| News intelligence | Existing keyword themes and tone; added similar-headline grouping retaining original sources, dates, numbers and negations | Entity extraction and evaluated relevance classifier remain unimplemented; no invented confidence percentage |
| Bull / bear case | Added positive/negative factors from reported growth, model thresholds and current ratio, with uncertainties | Broader field coverage |
| Peer scorecard | Extended existing table with provider-supplied ROE, revenue growth and operating margin; missing values remain blank | Provider coverage and period alignment; no unsupported financial score |
| Scenario analysis | Added individual holding and whole currency-group shocks | Sector and currency scenarios require declared FX assumptions |
| Data provenance | Source/timestamp and operations panels; added summary of price session, model, prediction generation and company source | Review further per-section coverage |

The holdings panel is browser-local. Quantities and purchase prices are not included in quote requests. It is an aggregate current-holdings record, not a transaction ledger. Returns exclude fees, taxes and dividends. Missing quotes suppress complete totals rather than being treated as zero. Holdings in different currencies are never summed without conversion.
