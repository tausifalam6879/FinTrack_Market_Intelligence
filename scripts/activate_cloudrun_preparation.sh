#!/usr/bin/env bash
# Activate the already-tested queue revision and a bounded hourly worker.
set -euo pipefail
PROJECT_ID="${PROJECT_ID:-project-424147c2-3cf6-4c26-b18}"
REGION="${REGION:-asia-south1}"
REVISION="fintrack-market-api-00012-buh"
SCHEDULER="fintrack-company-preparation-hourly"
INVOKER="fintrack-preparation-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

# Validate the exact revision before changing traffic or scheduling costs.
gcloud run revisions describe "$REVISION" --project="$PROJECT_ID" --region="$REGION" --format=json |
python -c '
import json,sys
d=json.load(sys.stdin)
spec=d["spec"]
env={e["name"]:e.get("value") for e in spec["containers"][0].get("env",[])}
assert env.get("ENABLE_COMPANY_PREPARATION_QUEUE")=="true", "Queue revision is not enabled"
assert env.get("MODEL_ARTIFACT_BUCKET")=="fintrack-models-304232323336", "Unexpected model bucket"
assert spec["containers"][0]["image"].endswith("@sha256:bccb276db2f5261a6053689b40ed8c0713076baaeffcb62d852f749bb0371a82"), "Unexpected serving image"
print("Verified tested serving revision")
'
gcloud services enable cloudscheduler.googleapis.com --project="$PROJECT_ID"
if ! gcloud iam service-accounts describe "$INVOKER" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create fintrack-preparation-scheduler --project="$PROJECT_ID" \
    --display-name="FinTrack preparation scheduler invoker"
fi
gcloud run jobs add-iam-policy-binding fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" \
  --member="serviceAccount:${INVOKER}" --role=roles/run.invoker >/dev/null
gcloud run jobs update fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" \
  --command=python --args="preparation_queue.py,--limit,1" \
  --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=30m
ACTION=create
if gcloud scheduler jobs describe "$SCHEDULER" --project="$PROJECT_ID" --location="$REGION" >/dev/null 2>&1; then
  ACTION=update
fi
gcloud scheduler jobs "$ACTION" http "$SCHEDULER" --project="$PROJECT_ID" --location="$REGION" \
  --schedule="0 * * * *" --time-zone="Asia/Kolkata" \
  --uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/fintrack-company-preparation:run" \
  --http-method=POST --oauth-service-account-email="$INVOKER" \
  --oauth-token-scope="https://www.googleapis.com/auth/cloud-platform" \
  --message-body='{}' --attempt-deadline=180s --max-retry-attempts=0 --max-retry-duration=0s
gcloud run services update-traffic fintrack-market-api --project="$PROJECT_ID" --region="$REGION" \
  --to-revisions="${REVISION}=100"
curl --silent --show-error --fail-with-body --max-time 60 \
  "https://fintrack-market-api-n2ylozzkwq-el.a.run.app/health/ready"
printf '\nActivation finished. One queued company per hourly execution. No automatic approval.\n'
gcloud scheduler jobs describe "$SCHEDULER" --project="$PROJECT_ID" --location="$REGION" \
  --format='yaml(state,schedule,timeZone,httpTarget.uri)'
