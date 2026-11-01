#!/usr/bin/env bash
# Reuse the existing backup job; never deploy, change IAM, or restore production.
set -euo pipefail
umask 077
PROJECT_ID="${PROJECT_ID:-project-424147c2-3cf6-4c26-b18}"
REGION="${REGION:-asia-south1}"
BUCKET="fintrack-backups-304232323336"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for tool in gcloud python3 docker tar; do
  command -v "$tool" >/dev/null || { printf 'Missing required tool: %s\n' "$tool" >&2; exit 1; }
done
docker info >/dev/null
STAMP="$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')"
OBJECT="rehearsals/${STAMP}.sql"
LOCAL_DIR="$(mktemp -d /tmp/fintrack-fresh-backup.XXXXXX)"
ARCHIVE="${HOME}/fintrack-database-${STAMP}.tar.gz"
trap 'printf "Private working files retained at %s\n" "$LOCAL_DIR"' EXIT
printf 'Creating a fresh export with the existing backup job...\n'
gcloud run jobs execute fintrack-database-backup \
  --project="$PROJECT_ID" --region="$REGION" \
  --update-env-vars="BACKUP_BUCKET=${BUCKET},BACKUP_OBJECT=${OBJECT}" --wait
gcloud storage cp "gs://${BUCKET}/${OBJECT}" "$LOCAL_DIR/backup.sql"
gcloud storage cp "gs://${BUCKET}/${OBJECT}.manifest.json" "$LOCAL_DIR/backup.sql.manifest.json"
chmod 600 "$LOCAL_DIR/backup.sql" "$LOCAL_DIR/backup.sql.manifest.json"
printf 'Verifying checksum and restoring into disposable local MySQL (not production)...\n'
python3 "$REPO_ROOT/scripts/rehearse_mysql_restore.py" "$LOCAL_DIR/backup.sql"
python3 - "$LOCAL_DIR/backup.sql.restore-report.json" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    report = json.load(stream)
if report.get("status") != "restore_verified" or report.get("productionModified") is not False:
    raise SystemExit("Restore verification did not pass; no verified archive created.")
PY
tar -czf "$ARCHIVE" -C "$LOCAL_DIR" \
  backup.sql backup.sql.manifest.json backup.sql.restore-report.json
chmod 600 "$ARCHIVE"
printf '\nVerified database archive: %s\n' "$ARCHIVE"
printf 'Download this archive using Cloud Shell > Download file, then store it privately on your PC.\n'
printf 'Until downloaded, it is still on Google. It contains sensitive application data; never commit or share it publicly.\n'
printf 'Scope: database tables/triggers and isolated SQL restore; not models, secrets, schedules, or full application recovery.\n'
printf 'Production database, job configuration, IAM, and live traffic were not changed.\n'
