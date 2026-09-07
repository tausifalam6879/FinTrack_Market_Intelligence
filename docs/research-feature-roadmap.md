# Research feature additions

This tracks the requested research extensions without rebuilding existing capabilities.

| Requested feature | Existing capability | Remaining work |
| --- | --- | --- |
| Portfolio and watchlist | Browser watchlist and comparison; new holdings panel with separate currency totals, quote timestamps and unrealized P/L | Sector allocation and best/worst performer; risk analytics below |
| ML explainability | Diagnostic feature importance | Per-prediction contributions with verified units; do not present importance as probability percentage points |
| Backtesting | Time-series validation | Historical out-of-sample strategy simulation, costs, execution lag and benchmark comparison |
| Smart alerts | Browser downside alerts | Additional rules and persistent scheduling; external notifications require delivery configuration |
| Research reports | Print / Save PDF | Structured generated report combining evidence and citations |
| Portfolio risk | Individual asset risk | Aligned portfolio returns, volatility, drawdown, concentration and carefully defined VaR |
| Correlation matrix | Asset/benchmark comparison | Multi-holding correlation using aligned observations |
| Model performance dashboard | Registry, experiments, drift and outcome panels | Review time-series performance visualization gaps |
| Prediction confidence | Calibration and neutral thresholds | Explain strength separately from measured predictive reliability; no arbitrary confidence labels |
| Event impact | Corporate actions data | Dated event windows and benchmark-adjusted returns |
| News intelligence | Existing news analysis | Audit duplicate grouping, entities and topic coverage before extending |
| Bull / bear case | Existing analysis briefs | Evidence-linked positive factors, negative factors and uncertainties |
| Peer scorecard | Existing peer comparison | Audit available fundamentals before extending metrics |
| Scenario analysis | Basic single-stock explanations | Explicit holding/sector shocks; currency scenarios require declared FX assumptions |
| Data provenance | Source/timestamp and operations panels | Review per-section coverage and stale-data labels |

The holdings panel is browser-local. Quantities and purchase prices are not included in quote requests. It is an aggregate current-holdings record, not a transaction ledger. Returns exclude fees, taxes and dividends. Missing quotes suppress complete totals rather than being treated as zero. Holdings in different currencies are never summed without conversion.
