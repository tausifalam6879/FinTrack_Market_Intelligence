#!/usr/bin/env bash
set -euo pipefail

# Run from Google Cloud Shell after the latest market API revision is deployed.
# The job reuses the service image, database secret, runtime identity and VPC.
PROJECT_ID="${PROJECT_ID:-project-424147c2-3cf6-4c26-b18}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-fintrack-market-api}"
JOB="${JOB:-fintrack-market-operations}"
SCHEDULER_JOB="${SCHEDULER_JOB:-fintrack-market-operations-weekdays}"
SCHEDULER_REGION="${SCHEDULER_REGION:-asia-south1}"
SCHEDULE="${SCHEDULE:-30 13 * * 1-5}"
TIME_ZONE="${TIME_ZONE:-Asia/Kolkata}"
REBUILD_SERVICE="${REBUILD_SERVICE:-true}"

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable run.googleapis.com cloudscheduler.googleapis.com >/dev/null

# The service and the job intentionally share one tested production image.
# Rebuilding here ensures operations_pipeline.py is present in that image.
if [[ "$REBUILD_SERVICE" == "true" ]]; then
  gcloud run deploy "$SERVICE" \
    --project="$PROJECT_ID" --region="$REGION" \
    --source=market-service --quiet
fi

SERVICE_JSON="$(mktemp)"
trap 'rm -f "$SERVICE_JSON"' EXIT
gcloud run services describe "$SERVICE" \
  --project="$PROJECT_ID" --region="$REGION" --format=json >"$SERVICE_JSON"

readarray -t SETTINGS < <(python3 - "$SERVICE_JSON" <<'PY'
import json, shlex, sys

service = json.load(open(sys.argv[1], encoding="utf-8"))
template = service["spec"]["template"]
spec = template["spec"]
container = spec["containers"][0]
annotations = template.get("metadata", {}).get("annotations", {})

db = next((item for item in container.get("env", []) if item.get("name") == "DATABASE_URL"), None)
if not db:
    raise SystemExit("DATABASE_URL is not configured on the Cloud Run service.")
secret = db.get("valueFrom", {}).get("secretKeyRef", {})
if not secret.get("name"):
    raise SystemExit(
        "DATABASE_URL must use Secret Manager before creating the scheduled job; "
        "plain-text database URLs are intentionally not copied."
    )

values = {
    "IMAGE": container["image"],
    "SERVICE_ACCOUNT": spec.get("serviceAccountName", ""),
    "DB_SECRET": secret["name"],
    "DB_SECRET_VERSION": secret.get("key", "latest"),
    "NETWORK": annotations.get("run.googleapis.com/network-interfaces", ""),
    "VPC_EGRESS": annotations.get("run.googleapis.com/vpc-access-egress", "all-traffic"),
}
for key, value in values.items():
    print(f"{key}={shlex.quote(value)}")
PY
)
eval "${SETTINGS[*]}"

NETWORK_NAME="$(python3 - "$NETWORK" <<'PY'
import json, sys
raw = sys.argv[1]
if not raw:
    print("")
else:
    data = json.loads(raw)
    print(data[0].get("network", ""))
PY
)"
SUBNET_NAME="$(python3 - "$NETWORK" <<'PY'
import json, sys
raw = sys.argv[1]
if not raw:
    print("")
else:
    data = json.loads(raw)
    print(data[0].get("subnetwork", ""))
PY
)"

if [[ -z "$NETWORK_NAME" || -z "$SUBNET_NAME" ]]; then
  echo "The source service has no Direct VPC egress configuration." >&2
  exit 1
fi

JOB_ARGS=(
  --project="$PROJECT_ID"
  --region="$REGION"
  --image="$IMAGE"
  --command=python
  --args=operations_pipeline.py,--period,2y,--max-symbols,100
  --tasks=1
  --max-retries=1
  --task-timeout=30m
  --cpu=1
  --memory=1Gi
  --set-env-vars=REQUIRE_DURABLE_DATABASE=true
  --set-secrets="DATABASE_URL=${DB_SECRET}:${DB_SECRET_VERSION}"
  --network="$NETWORK_NAME"
  --subnet="$SUBNET_NAME"
  --vpc-egress="$VPC_EGRESS"
  --quiet
)
if [[ -n "$SERVICE_ACCOUNT" ]]; then
  JOB_ARGS+=(--service-account="$SERVICE_ACCOUNT")
fi

gcloud run jobs deploy "$JOB" "${JOB_ARGS[@]}"

SCHEDULER_SA="${SERVICE_ACCOUNT:-$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')-compute@developer.gserviceaccount.com}"
gcloud run jobs add-iam-policy-binding "$JOB" \
  --project="$PROJECT_ID" --region="$REGION" \
  --member="serviceAccount:${SCHEDULER_SA}" --role=roles/run.invoker --quiet >/dev/null

RUN_URI="https://${REGION}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${PROJECT_ID}/jobs/${JOB}:run"
if gcloud scheduler jobs describe "$SCHEDULER_JOB" --location="$SCHEDULER_REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" \
    --location="$SCHEDULER_REGION" --schedule="$SCHEDULE" --time-zone="$TIME_ZONE" \
    --uri="$RUN_URI" --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA" \
    --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform --quiet
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --location="$SCHEDULER_REGION" --schedule="$SCHEDULE" --time-zone="$TIME_ZONE" \
    --uri="$RUN_URI" --http-method=POST \
    --oauth-service-account-email="$SCHEDULER_SA" \
    --oauth-token-scope=https://www.googleapis.com/auth/cloud-platform --quiet
fi

echo
echo "CLOUD_RUN_MARKET_JOB_READY"
echo "Job: $JOB"
echo "Schedule: weekdays at 19:00 Asia/Kolkata"
echo "Database traffic uses the existing fixed Cloud NAT egress."
echo "NEXT: run once with: gcloud run jobs execute $JOB --region=$REGION --wait"
