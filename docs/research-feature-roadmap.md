# Research feature additions

This tracks the requested research extensions without rebuilding existing capabilities.

| Requested feature | Existing capability | Remaining work |
| --- | --- | --- |
| Portfolio and watchlist | Holdings, currency totals, sector allocation, highest/lowest returns, timestamps and unrealized P/L | Transaction ledger and corporate-action reconciliation are not implemented |
| ML explainability | Diagnostic feature importance plus existing per-prediction counterfactual sensitivity and probability path UI | SHAP is not implemented; existing sensitivity is not SHAP and should not be relabelled |
| Backtesting | Added fixed logistic-model expanding training, next-open execution, costs, drawdown, benchmark and training audit | User-selected date windows, adjusted execution prices and richer curve visualization |
| Smart alerts | Browser downside alerts | Additional rules and persistent scheduling; external notifications require delivery configuration |
| Research reports | Print / Save PDF | Structured generated report combining evidence and citations |
| Portfolio risk | Added current-weight historical simulation, volatility, drawdown, sector concentration and historical 95% loss quantile | Adjusted prices and actual transaction-history analytics |
| Correlation matrix | Added multi-holding return correlations on common dates | Longer histories and date-window selection |
| Model performance dashboard | Registry, experiments, drift and outcome panels | Review time-series performance visualization gaps |
| Prediction confidence | Calibration and neutral thresholds | Explain strength separately from measured predictive reliability; no arbitrary confidence labels |
| Event impact | Corporate actions data | Dated event windows and benchmark-adjusted returns |
| News intelligence | Existing news analysis | Audit duplicate grouping, entities and topic coverage before extending |
| Bull / bear case | Existing analysis briefs | Evidence-linked positive factors, negative factors and uncertainties |
| Peer scorecard | Existing peer comparison | Audit available fundamentals before extending metrics |
| Scenario analysis | Added individual holding and whole currency-group shocks | Sector and currency scenarios require declared FX assumptions |
| Data provenance | Source/timestamp and operations panels | Review per-section coverage and stale-data labels |

The holdings panel is browser-local. Quantities and purchase prices are not included in quote requests. It is an aggregate current-holdings record, not a transaction ledger. Returns exclude fees, taxes and dividends. Missing quotes suppress complete totals rather than being treated as zero. Holdings in different currencies are never summed without conversion.
