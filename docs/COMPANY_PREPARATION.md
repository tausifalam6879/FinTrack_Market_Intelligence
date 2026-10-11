# New-company preparation

Company research does not require an approved prediction model. Missing predictions
stay unavailable; they are never replaced with 0%, 50%, or a model fitted during
the web request.

## Demand queue

The serving environment flag `ENABLE_COMPANY_PREPARATION_QUEUE=true` enables
enqueueing after valid company history has been persisted. It is disabled by
default. Two idempotently created database tables hold requests and the enqueue
lock. Each symbol has one request. The active queue is capped at 100 symbols.
Public requests cannot approve models or retry terminal requests.

States: `pending`, `running`, `candidate`, `rejected`, `failed`. Workers claim a
two-hour lease with a unique token. Expired leases may be reclaimed, at most three
attempts; stale workers cannot overwrite another worker's result. Training jobs
must have a timeout shorter than the lease. Terminal failures need operator
investigation; they are not repeatedly retrained by page visits.

## Trusted offline worker

Run `python preparation_queue.py --limit 3` in the training container, not the
lightweight serving container. It processes at most ten symbols per invocation,
refreshes validated provider history, and calls the existing offline trainer.
There is no automatic approval. A candidate must still pass the existing registry
approval process; rejected models must not be promoted.

The worker needs the database secret, database TLS certificate, existing fixed
network egress, and model bucket write/read permissions used by the training job.
Schedule a separate preparation job so the main training job is not replaced.
No scheduler or Cloud Run deployment has been created by this code change.

Before enabling, deploy the new training image, test the worker on the cloud
database, verify serving-account artifact access, and establish a cost budget.
Only then enable the serving flag and scheduled worker. Without these steps,
queued work will not run automatically. Insufficient history and provider failures
remain explicit failed preparation, not a promised forecast.

## Checks

`python -m unittest test_preparation_queue test_research_availability`
tests deduplication, capacity, claim ownership, terminal states, sanitized errors,
candidate-only processing, and research without invented predictions.
