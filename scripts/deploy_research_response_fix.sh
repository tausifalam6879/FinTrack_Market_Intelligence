#!/usr/bin/env bash
# Update only the serving API. Existing jobs, approved models and backups stay unchanged.
set -euo pipefail
PROJECT_ID="project-424147c2-3cf6-4c26-b18"
REGION="asia-south1"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
gcloud run deploy fintrack-market-api --source="$REPO_ROOT/market-service" \
  --project="$PROJECT_ID" --region="$REGION" --no-traffic --tag=response-check
STATE_FILE="$(mktemp /tmp/fintrack-response-state.XXXXXX)"
gcloud run services describe fintrack-market-api --project="$PROJECT_ID" --region="$REGION" --format=json > "$STATE_FILE"
read -r STAGED_REVISION STAGED_URL < <(python3 - "$STATE_FILE" <<'PY'
import json,sys
service=json.load(open(sys.argv[1]))
tag=next(t for t in service['status']['traffic'] if t.get('tag')=='response-check')
print(tag['revisionName'],tag['url'])
PY
)
python3 "$REPO_ROOT/scripts/check_research_response.py" "$STAGED_URL"
gcloud run services update-traffic fintrack-market-api --project="$PROJECT_ID" --region="$REGION" \
  --to-revisions="${STAGED_REVISION}=100"
printf '\nResearch response update deployed. Experimental estimates remain separate from approved forecasts.\n'
