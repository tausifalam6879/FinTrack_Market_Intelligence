#!/usr/bin/env bash
# Build a separate training image and inventory all eligible stored symbols.
set -euo pipefail
PROJECT_ID="${PROJECT_ID:-project-424147c2-3cf6-4c26-b18}"
REGION="${REGION:-asia-south1}"
MODEL_BUCKET="${MODEL_BUCKET:-fintrack-models-304232323336}"
TRAINING_SA="fintrack-training@${PROJECT_ID}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVISION="$(git -C "$ROOT" rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/fintrack-market-api:training-${REVISION}"

gcloud builds submit "$ROOT/market-service" --project="$PROJECT_ID" --region="$REGION" --tag="$IMAGE"
if ! gcloud iam service-accounts describe "$TRAINING_SA" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create fintrack-training --project="$PROJECT_ID" --display-name="FinTrack offline training"
fi
for SECRET in fintrack-database-url fintrack-aiven-ca; do
  gcloud secrets add-iam-policy-binding "$SECRET" --project="$PROJECT_ID" \
    --member="serviceAccount:${TRAINING_SA}" --role="roles/secretmanager.secretAccessor" >/dev/null
done
for ROLE in roles/storage.objectCreator roles/storage.objectViewer; do
  gcloud storage buckets add-iam-policy-binding "gs://${MODEL_BUCKET}" \
    --member="serviceAccount:${TRAINING_SA}" --role="$ROLE" >/dev/null
done
gcloud run jobs deploy fintrack-model-training --project="$PROJECT_ID" --region="$REGION" \
  --image="$IMAGE" --service-account="$TRAINING_SA" \
  --network=fintrack-egress --subnet=fintrack-egress-asia-south1 --vpc-egress=all-traffic \
  --set-secrets="DATABASE_URL=fintrack-database-url:latest,/etc/secrets/ca.pem=fintrack-aiven-ca:latest" \
  --set-env-vars="MODEL_ARTIFACT_BUCKET=${MODEL_BUCKET},MODEL_ARTIFACT_DIR=/app/artifacts,REQUIRE_DURABLE_DATABASE=true" \
  --command=python --args="offline_training.py,--all-stored,--list-only" \
  --cpu=2 --memory=2Gi --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=30m
gcloud run jobs execute fintrack-model-training --project="$PROJECT_ID" --region="$REGION" --wait
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="fintrack-model-training"' \
  --project="$PROJECT_ID" --freshness=10m --limit=100 --order=asc --format='value(textPayload)'
printf '\nInventory only: no models trained or approved; live API unchanged.\n'
