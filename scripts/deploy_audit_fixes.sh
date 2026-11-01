#!/usr/bin/env bash
# Update both existing services; retain env/secrets/network configuration.
set -euo pipefail
PROJECT_ID="project-424147c2-3cf6-4c26-b18"
REGION="asia-south1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$(mktemp -d /tmp/fintrack-audit-release.XXXXXX)"
chmod 700 "$STATE_DIR"
declare -A OLD_TRAFFIC
declare -a PROMOTED=()
for service in fintrack-market-api fintrack-gateway; do
  gcloud run services describe "$service" --project="$PROJECT_ID" --region="$REGION" \
    --format=json > "$STATE_DIR/$service.json"
  OLD_TRAFFIC[$service]="$(python3 - "$STATE_DIR/$service.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
t = {}
for row in d['status']['traffic']:
    if row.get('percent', 0):
        key = row['revisionName']
        t[key] = t.get(key, 0) + row['percent']
if sum(t.values()) != 100:
    raise SystemExit('Cannot verify previous traffic; stopping.')
print(','.join(f'{key}={value}' for key,value in t.items()))
PY
)"
done
rollback() {
  trap - ERR
  for (( i=${#PROMOTED[@]}-1; i>=0; i-- )); do
    service="${PROMOTED[$i]}"
    gcloud run services update-traffic "$service" --project="$PROJECT_ID" --region="$REGION" \
      --to-revisions="${OLD_TRAFFIC[$service]}" || true
  done
  printf '\nDeployment failed; previous promoted-service traffic restoration attempted. Inspect logs.\n' >&2
  exit 1
}
trap rollback ERR
for service in fintrack-market-api fintrack-gateway; do
  source_dir=market-service
  [[ "$service" == fintrack-gateway ]] && source_dir=gateway-service
  gcloud run deploy "$service" --source="$REPO_ROOT/$source_dir" \
    --project="$PROJECT_ID" --region="$REGION" --no-traffic --tag=audit-check
  gcloud run services describe "$service" --project="$PROJECT_ID" --region="$REGION" \
    --format=json > "$STATE_DIR/staged.json"
  read -r REVISION STAGED_URL LIVE_URL < <(python3 - "$STATE_DIR/staged.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
t = next(r for r in d['status']['traffic'] if r.get('tag') == 'audit-check')
print(t['revisionName'], t['url'], d['status']['url'])
PY
)
  python3 "$REPO_ROOT/scripts/check_agent_speed.py" "$STAGED_URL"
  # Record before promotion so even a failed traffic update is rolled back.
  PROMOTED+=("$service")
  gcloud run services update-traffic "$service" --project="$PROJECT_ID" --region="$REGION" \
    --to-revisions="${REVISION}=100"
  python3 "$REPO_ROOT/scripts/check_agent_speed.py" "$LIVE_URL"
done
trap - ERR
printf '\nAPI and gateway audit fixes deployed; staged and live research checks passed.\n'
