#!/usr/bin/env bash
# Deploy the question-scoped research path using the existing Cloud Run setup.
set -euo pipefail
PROJECT_ID="project-424147c2-3cf6-4c26-b18"
REGION="asia-south1"
SERVICE="fintrack-market-api"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$(mktemp -d /tmp/fintrack-agent-release.XXXXXX)"
chmod 700 "$STATE_DIR"

gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
  --format=json > "$STATE_DIR/before.json"
PREVIOUS_TRAFFIC="$(python3 - "$STATE_DIR/before.json" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    service = json.load(stream)
traffic = {}
for item in service['status']['traffic']:
    if item.get('percent', 0) > 0:
        revision = item['revisionName']
        traffic[revision] = traffic.get(revision, 0) + item['percent']
if sum(traffic.values()) != 100:
    raise SystemExit('Cannot verify previous serving traffic; deployment stopped.')
print(','.join(f'{revision}={percent}' for revision, percent in traffic.items()))
PY
)"

gcloud run deploy "$SERVICE" --source="$REPO_ROOT/market-service" \
  --project="$PROJECT_ID" --region="$REGION" --no-traffic --tag=rag-speed-check
gcloud run services describe "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
  --format=json > "$STATE_DIR/staged.json"
read -r REVISION STAGED_URL LIVE_URL < <(python3 - "$STATE_DIR/staged.json" <<'PY'
import json, sys
with open(sys.argv[1]) as stream:
    service = json.load(stream)
tag = next(item for item in service['status']['traffic'] if item.get('tag') == 'rag-speed-check')
print(tag['revisionName'], tag['url'], service['status']['url'])
PY
)

python3 "$REPO_ROOT/scripts/check_agent_speed.py" "$STAGED_URL"
gcloud run services update-traffic "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
  --to-revisions="${REVISION}=100"
if ! python3 "$REPO_ROOT/scripts/check_agent_speed.py" "$LIVE_URL"; then
  printf '\nLive verification failed; restoring the previous serving traffic.\n' >&2
  gcloud run services update-traffic "$SERVICE" --project="$PROJECT_ID" --region="$REGION" \
    --to-revisions="$PREVIOUS_TRAFFIC"
  exit 1
fi
printf '\nDeployed %s at %s. Research and report checks passed on staged and live URLs.\n' "$REVISION" "$LIVE_URL"
