#!/usr/bin/env bash
# Production read-only dump, followed by isolated local restore. No access-rule changes.
set -euo pipefail
PROJECT_ID="project-424147c2-3cf6-4c26-b18"
REGION="asia-south1"
BUCKET="fintrack-backups-304232323336"
BACKUP_SA="fintrack-backup@${PROJECT_ID}.iam.gserviceaccount.com"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REVISION="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy/fintrack-backup:${REVISION}"
OBJECT="rehearsals/$(date -u +%Y%m%dT%H%M%SZ)-${RANDOM}.sql"
docker info --format '{{.ServerVersion}}'
if ! gcloud storage buckets describe "gs://${BUCKET}" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${BUCKET}" --project="$PROJECT_ID" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention
fi
if ! gcloud iam service-accounts describe "$BACKUP_SA" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create fintrack-backup --project="$PROJECT_ID" --display-name="FinTrack read-only database backup runner"
fi
for SECRET in fintrack-database-url fintrack-aiven-ca; do
  gcloud secrets add-iam-policy-binding "$SECRET" --project="$PROJECT_ID" \
    --member="serviceAccount:${BACKUP_SA}" --role=roles/secretmanager.secretAccessor >/dev/null
done
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${BACKUP_SA}" --role=roles/storage.objectCreator >/dev/null
gcloud builds submit "$REPO_ROOT/market-service" --project="$PROJECT_ID" --region="$REGION" \
  --config="$REPO_ROOT/market-service/cloudbuild-backup.yaml" --substitutions="_IMAGE=$IMAGE"
gcloud run jobs deploy fintrack-database-backup --project="$PROJECT_ID" --region="$REGION" \
  --image="$IMAGE" --service-account="$BACKUP_SA" \
  --network=fintrack-egress --subnet=fintrack-egress-asia-south1 --vpc-egress=all-traffic \
  --set-secrets="DATABASE_URL=fintrack-database-url:latest,/etc/secrets/ca.pem=fintrack-aiven-ca:latest" \
  --set-env-vars="BACKUP_BUCKET=${BUCKET},BACKUP_OBJECT=${OBJECT}" \
  --cpu=1 --memory=1Gi --tasks=1 --parallelism=1 --max-retries=0 --task-timeout=20m
gcloud run jobs execute fintrack-database-backup --project="$PROJECT_ID" --region="$REGION" --wait
LOCAL_DIR="$(mktemp -d /tmp/fintrack-backup-rehearsal.XXXXXX)"
chmod 700 "$LOCAL_DIR"
gcloud storage cp "gs://${BUCKET}/${OBJECT}" "$LOCAL_DIR/backup.sql"
gcloud storage cp "gs://${BUCKET}/${OBJECT}.manifest.json" "$LOCAL_DIR/backup.sql.manifest.json"
chmod 600 "$LOCAL_DIR/backup.sql" "$LOCAL_DIR/backup.sql.manifest.json"
python "$REPO_ROOT/scripts/rehearse_mysql_restore.py" "$LOCAL_DIR/backup.sql"
gcloud storage cp "$LOCAL_DIR/backup.sql.restore-report.json" "gs://${BUCKET}/${OBJECT}.restore-report.json"
printf '\nRestore rehearsal completed. Private local backup retained at %s; cloud copy retained in gs://%s/%s. Never commit SQL backups.\n' "$LOCAL_DIR" "$BUCKET" "$OBJECT"
