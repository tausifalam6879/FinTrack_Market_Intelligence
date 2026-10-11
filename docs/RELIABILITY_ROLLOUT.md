# Reliability changes and production rollout

## Release gate

Prediction no longer fits an estimator during an HTTP request. When no trusted approved
model is available, prediction-dependent analysis returns HTTP 503 with code
MODEL_UNAVAILABLE. Company, price and news endpoints remain independent. Existing
browser snapshots may be shown with their saved timestamp. Do not deploy until you
have trained, passed the quality gate, approved and tested artifacts for the symbols
you intend to support. Some symbols may legitimately fail the quality gate; display
unavailable rather than inventing a forecast. General research that requires a
prediction can also be unavailable for those symbols.

## Durable model storage

Set MODEL_ARTIFACT_BUCKET to a private Cloud Storage bucket and optionally
MODEL_ARTIFACT_PREFIX (default models/). Use a dedicated training identity with
storage.objects.create permission and a serving identity with storage.objects.get.
Use bucket-scoped IAM, not public access. Existing artifacts are not migrated
automatically. Retrain and approve to register gs:// URIs, or migrate existing
registered artifacts with controlled checksum/identity verification.

The offline trainer publishes immutable checksum-named objects before registering
the run. Serving downloads from the allowlisted bucket/prefix into MODEL_ARTIFACT_DIR,
checks SHA-256, then applies the existing identity verification. Local cached files
are disposable; the bucket is durable. Registry database integrity and trusted
training access still matter because joblib can execute code when loaded.

Train outside the public request path:

```sh
python offline_training.py --symbols INFY.NS
python model_registry.py --approve CANDIDATE_RUN_ID
```

Train with the same dependency versions as serving. Failed gate candidates cannot
be approved; never bypass the gate to make the dashboard appear complete.

## Freshness, news, transparency and evidence

Badges no longer label saved data as verified. Cached/snapshot notices preserve
timestamps; fetch time is distinct from observation time. News empty results do
not replace good browser cache. Filters with no matches and provider failures have
different messages. Prediction UI shows model, serving mode and evaluation date.
Price ranges are labelled volatility estimates, not calibrated confidence intervals.
Document answers expose evidence status, document type and relevant cited passages.
Citation presence alone does not prove every generated claim is supported.

## Request budgets

EXPENSIVE_REQUESTS_PER_MINUTE defaults to 30 and EXPENSIVE_REQUESTS_CONCURRENT to 2.
Limits apply to expensive analysis, prediction, agent, comparison, backtest and
document POST routes per service process. HTTP 429 includes Retry-After. These are
capacity limits, not user authentication or an account-wide spend cap. Bound Cloud
Run max instances and use a shared limiter/edge controls if you require global
quotas. Limits reset on restart and each instance has its own budget.

## Backup and recovery verification

Existing backup tooling verifies SHA-256 and preserves a manifest. SQL integrity
alone is weaker than an actual restore. Run the wrapper with Docker running and
FINTRACK_CLOUD_MYSQL_URI set securely in the environment:

```powershell
./scripts/verify_backup_restore.ps1 -CaFile C:/secure/ca.pem -BackupFile C:/secure/fintrack-backup.sql
```

It creates a fresh backup and imports it into a disposable MySQL container. It
never targets production for restore. Preserve the resulting .manifest.json and
.restore-report.json alongside an encrypted off-host copy of the SQL backup.
Use a timestamped destination on every run. For stronger validation, use the
existing rehearsal tool's --application option with its prebuilt API/gateway images.

The local machine currently has no working Docker daemon or gcloud CLI. Production
backup/restore and Cloud Storage IAM must be verified in Cloud Shell or another
configured environment before declaring the rollout complete.
