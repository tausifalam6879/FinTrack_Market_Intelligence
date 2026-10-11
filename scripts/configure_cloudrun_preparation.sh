#!/usr/bin/env bash
# Deploy a separate preparation job in check-only mode. No training or serving changes.
set -euo pipefail
PROJECT_ID="${PROJECT_ID:-project-424147c2-3cf6-4c26-b18}"
REGION="${REGION:-asia-south1}"
MODEL_BUCKET="${MODEL_BUCKET:-fintrack-models-304232323336}"
PREPARATION_SA="fintrack-training@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVISION="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/fintrack-market-api:training-${REVISION}"

# Fail before a paid build if the previously configured account/secrets are missing.
gcloud iam service-accounts describe "$PREPARATION_SA" --project="$PROJECT_ID" >/dev/null
gcloud secrets describe fintrack-database-url --project="$PROJECT_ID" >/dev/null
gcloud secrets describe fintrack-aiven-ca --project="$PROJECT_ID" >/dev/null
gcloud builds submit "$REPO_ROOT/market-service" --project="$PROJECT_ID" --region="$REGION" \
  --config="$REPO_ROOT/market-service/cloudbuild-training.yaml" --substitutions="_IMAGE=$IMAGE"

gcloud run jobs deploy fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" \
  --image="$IMAGE" --service-account="$PREPARATION_SA" \
  --network=fintrack-egress --subnet=fintrack-egress-asia-south1 --vpc-egress=all-traffic \
  --set-secrets="DATABASE_URL=fintrack-database-url:latest,/etc/secrets/ca.pem=fintrack-aiven-ca:latest" \
  --set-env-vars="MODEL_ARTIFACT_BUCKET=${MODEL_BUCKET},MODEL_ARTIFACT_DIR=/app/artifacts,REQUIRE_DURABLE_DATABASE=true" \
  --command=python --args="preparation_queue.py,--check-only" \
  --cpu=2 --memory=4Gi --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=30m
gcloud run jobs execute fintrack-company-preparation --project="$PROJECT_ID" --region="$REGION" --wait
printf '\nCheck only completed. No models trained or approved. Serving flag and scheduler unchanged.\n'
