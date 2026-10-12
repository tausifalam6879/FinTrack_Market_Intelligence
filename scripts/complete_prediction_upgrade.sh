#!/usr/bin/env bash
# Recovery rehearsal, staged deployment and bounded wider-company preparation.
set -euo pipefail
PROJECT_ID="project-424147c2-3cf6-4c26-b18"
REGION="asia-south1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVISION="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/fintrack-market-api:coverage-${REVISION}"
TAG="coverage-check"

# Fail before paid builds if the required Cloud Shell access is unavailable.
gcloud run services describe fintrack-market-api --project="$PROJECT_ID" --region="$REGION" --format='value(status.url)'
gcloud run jobs describe fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" --format='value(metadata.name)'
bash "$REPO_ROOT/scripts/verify_application_recovery.sh" --models --browser --external-ai

gcloud builds submit "$REPO_ROOT/market-service" --project="$PROJECT_ID" --region="$REGION" \
  --config="$REPO_ROOT/market-service/cloudbuild-training.yaml" --substitutions="_IMAGE=$IMAGE"
gcloud run services update fintrack-market-api --project="$PROJECT_ID" --region="$REGION" \
  --image="${IMAGE}-runtime" --no-traffic --tag="$TAG" \
  --update-env-vars="ENABLE_COMPANY_PREPARATION_QUEUE=true,PREPARATION_APPROVE_PASSING=true"
STATE_FILE="$(mktemp /tmp/fintrack-upgrade-state.XXXXXX)"
gcloud run services describe fintrack-market-api --project="$PROJECT_ID" --region="$REGION" --format=json > "$STATE_FILE"
read -r STAGED_REVISION STAGED_URL < <(python3 - "$STATE_FILE" "$TAG" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
t=next(t for t in s['status']['traffic'] if t.get('tag')==sys.argv[2])
print(t['revisionName'],t['url'])
PY
)
python3 "$REPO_ROOT/scripts/verify_prediction_upgrade.py" --api="$STAGED_URL"

# Existing secrets, fixed NAT, service account and hourly schedule are preserved.
gcloud run jobs update fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" \
  --image="$IMAGE" --command=python --args="preparation_queue.py,--limit,1" \
  --update-env-vars="PREPARATION_APPROVE_PASSING=true" --max-retries=0
gcloud run jobs execute fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" \
  --args="preparation_queue.py,--check-only" --wait
gcloud run services update-traffic fintrack-market-api --project="$PROJECT_ID" --region="$REGION" \
  --to-revisions="${STAGED_REVISION}=100"
gcloud run jobs execute fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" \
  --args="preparation_queue.py,--seed-stored" --wait
gcloud run jobs execute fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" --wait
printf '\nUpgrade deployed and recovery checks passed. One company processed now; the hourly worker processes the remaining queue. Only calibrated models passing quality checks publish automatically.\n'
