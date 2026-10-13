# Prediction probabilities, coverage and recovery

## Experimental research estimates (October 2026 update)

The research screen now offers a separate experimental Logistic Regression estimate
when there is no approved artifact and enough clean, two-class price history exists.
It uses at most 600 observations, four causal price features, a chronological 80/20
split with a one-row gap, and publishes the evaluated estimator without holdout refit.
It is uncalibrated and is **not** quality-gate approved. It may underperform a simple
baseline. Both the API and UI label it `experimental_runtime`; it is not inserted
into the approved registry or approved prediction audit. Insufficient history still
returns no estimate. The approved-model path and worker gates are unchanged.

Research-only fallback responses and aggregate news are cached for 60 seconds.
Fetch status does not imply exchange-real-time prices. The UI shows loading while
refreshing; provider timestamps remain authoritative. Use
`bash scripts/deploy_research_response_fix.sh` for the serving-only staged rollout.

The previous serving calculation shrank the estimator output toward 50% using
holdout balanced accuracy and AUC, added heuristic news/macro points, and clipped
the result to 5–95%. This was not fitted probability calibration. It explains why
many displayed estimates clustered around 45–55% and why 99% was impossible.

The API now displays the approved estimator probability directly. News and macro
data remain research context. Legacy approved artifacts are labelled uncalibrated.
New training uses sigmoid calibration with three expanding time folds and a
one-session gap, entirely before the final holdout. The exact evaluated estimator
is published without refitting on that holdout. High outputs are permitted, never
forced. A probability is distinct from price gain, measured accuracy and a guarantee.

## Wider company coverage

Opening a supported company stores its history and queues it when a model is
missing. The worker retrieves up to five years of available history, compares
models and evaluates a separate holdout. With `PREPARATION_APPROVE_PASSING=true`,
it approves only calibrated candidates passing all existing registry quality
checks, with at least 60 holdout rows and Brier score below 0.25. Approval verifies
artifact checksum, identity and dataset version. Rejected candidates stay rejected.
Companies with insufficient history or weak predictive evidence can still have no
forecast. No unrelated company's model is substituted.

`preparation_queue.py --seed-stored` queues uncovered stored symbols once for the
new calibrated pipeline. It skips approved models and already calibrated runs.
`--retry-symbols SYMBOL ...` is an explicit operator retry (maximum ten symbols),
not a retry triggered by repeatedly opening the browser. The hourly worker remains
bounded to one company per execution. This is a research screening policy, not
evidence of profitable trading or universal coverage.

## Recovery and rollout

In Cloud Shell run `bash scripts/complete_prediction_upgrade.sh` from the repository.
It reuses the private verified SQL backup, restores disposable MySQL/API/gateway,
checks approved artifacts, drives a real Chromium browser through the built React
app, and makes a real Gemini call using public market evidence from the restored
database. Only the recovered API receives temporary outbound access for Gemini.
Production database credentials are never supplied to the recovery containers.
Gemini credentials are passed on stdin and are never printed.

The browser assertion requires a real recovered API analysis response, not a cached
or bundled snapshot. Its screenshot is retained beside the local recovery report.
The external AI check validates provider response against the restored symbol/date;
it is not a comprehensive test of every possible AI question or a factuality proof.

The script then builds runtime/training images, checks a zero-traffic API revision
(including real AI for a company without a forecast), updates the bounded worker,
and promotes the tested revision. Failed checks stop the script. Earlier successful
steps may remain; the script is not a transaction. Existing approved models remain
usable. Remaining queued companies run on the existing hourly schedule.

Local regression: build the three `fintrack-rehearsal-*:local` images, then run
`python scripts/test_browser_recovery.py`. It uses synthetic data and no cloud secrets.

Recovery downloads a missing MySQL image separately, with visible Docker progress
and a ten-minute download deadline. Container startup has its own three-minute
deadline. A timeout does not prove a database problem: check Docker availability,
disk capacity and network access in Cloud Shell. Failed attempts clean up only
their exact temporary container/network names; cleanup warnings identify anything
that may need inspection. No production restore is attempted.

Calibration reference: https://scikit-learn.org/stable/modules/calibration.html
