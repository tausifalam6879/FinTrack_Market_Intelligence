#!/usr/bin/env bash
# Reuse the completed backup; disposable database credentials only.
# --external-ai temporarily supplies the serving Gemini key via stdin, never logs.
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_URI="gs://fintrack-backups-304232323336/rehearsals/20261011T085822Z-30076.sql"
docker info --format '{{.ServerVersion}}'
RECOVERY_DIR="$(mktemp -d /tmp/fintrack-app-recovery.XXXXXX)"
chmod 700 "$RECOVERY_DIR"
gcloud storage cp "$BACKUP_URI" "$RECOVERY_DIR/backup.sql"
gcloud storage cp "${BACKUP_URI}.manifest.json" "$RECOVERY_DIR/backup.sql.manifest.json"
chmod 600 "$RECOVERY_DIR/backup.sql" "$RECOVERY_DIR/backup.sql.manifest.json"
python3 - "$RECOVERY_DIR/backup.sql" <<'PY'
import hashlib,json,sys
from pathlib import Path
p=Path(sys.argv[1])
m=json.loads(p.with_suffix(p.suffix+'.manifest.json').read_text())
assert m['format']=='mysql-sql'
assert hashlib.sha256(p.read_bytes()).hexdigest()==m['sha256'], 'Backup checksum mismatch'
print('Backup checksum verified')
PY
docker build -t fintrack-rehearsal-api:local "$REPO_ROOT/market-service"
docker build -t fintrack-rehearsal-gateway:local "$REPO_ROOT/gateway-service"
if [[ " $* " == *" --browser "* ]]; then
  docker build -f "$REPO_ROOT/frontend/Dockerfile.recovery" -t fintrack-rehearsal-browser:local "$REPO_ROOT/frontend"
fi
python3 "$REPO_ROOT/scripts/rehearse_mysql_restore.py" "$RECOVERY_DIR/backup.sql" --application "$@"
REPORT_SUFFIX="application-restore-report.json"
if [[ " $* " == *" --models "* ]]; then REPORT_SUFFIX="model-application-restore-report.json"; fi
if [[ " $* " == *" --browser "* || " $* " == *" --external-ai "* ]]; then REPORT_SUFFIX="extended-application-restore-report.json"; fi
gcloud storage cp "$RECOVERY_DIR/backup.sql.restore-report.json" "${BACKUP_URI}.${REPORT_SUFFIX}"
printf '\nApplication recovery rehearsal complete. Report saved privately. Production unchanged. Local backup retained at %s.\n' "$RECOVERY_DIR"
