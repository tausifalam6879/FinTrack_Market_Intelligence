#!/usr/bin/env bash
set -euo pipefail

# Run from Google Cloud Shell. This script never reads or prints application secrets.
PROJECT_ID="${PROJECT_ID:-project-424147c2-3cf6-4c26-b18}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-fintrack-market-api}"
NETWORK="${NETWORK:-fintrack-egress}"
SUBNET="${SUBNET:-fintrack-egress-asia-south1}"
SUBNET_RANGE="${SUBNET_RANGE:-10.20.0.0/26}"
ROUTER="${ROUTER:-fintrack-egress-router}"
NAT="${NAT:-fintrack-egress-nat}"
ADDRESS="${ADDRESS:-fintrack-egress-ip}"

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud services enable compute.googleapis.com run.googleapis.com

if ! gcloud compute networks describe "$NETWORK" >/dev/null 2>&1; then
  gcloud compute networks create "$NETWORK" --subnet-mode=custom
fi

if ! gcloud compute networks subnets describe "$SUBNET" --region="$REGION" >/dev/null 2>&1; then
  gcloud compute networks subnets create "$SUBNET" \
    --network="$NETWORK" \
    --region="$REGION" \
    --range="$SUBNET_RANGE"
fi

# Cloud Run Direct VPC egress reserves addresses in /28 blocks and requires a
# /26 or larger subnet. Upgrade the /28 created by the first script revision.
CURRENT_RANGE="$(gcloud compute networks subnets describe "$SUBNET" --region="$REGION" --format='value(ipCidrRange)')"
if [[ "$CURRENT_RANGE" == */28 ]]; then
  gcloud compute networks subnets expand-ip-range "$SUBNET" \
    --region="$REGION" \
    --prefix-length=26 \
    --quiet
fi

if ! gcloud compute addresses describe "$ADDRESS" --region="$REGION" >/dev/null 2>&1; then
  gcloud compute addresses create "$ADDRESS" --region="$REGION" --network-tier=PREMIUM
fi

if ! gcloud compute routers describe "$ROUTER" --region="$REGION" >/dev/null 2>&1; then
  gcloud compute routers create "$ROUTER" --network="$NETWORK" --region="$REGION"
fi

if ! gcloud compute routers nats describe "$NAT" --router="$ROUTER" --region="$REGION" >/dev/null 2>&1; then
  gcloud compute routers nats create "$NAT" \
    --router="$ROUTER" \
    --region="$REGION" \
    --nat-custom-subnet-ip-ranges="$SUBNET" \
    --nat-external-ip-pool="$ADDRESS" \
    --enable-logging
fi

gcloud run services update "$SERVICE" \
  --region="$REGION" \
  --network="$NETWORK" \
  --subnet="$SUBNET" \
  --vpc-egress=all-traffic \
  --quiet

STATIC_IP="$(gcloud compute addresses describe "$ADDRESS" --region="$REGION" --format='value(address)')"
SERVICE_URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --format='value(status.url)')"

echo
echo "STATIC_EGRESS_READY"
echo "Static IP: $STATIC_IP"
echo "Service URL: $SERVICE_URL"
echo
echo "NEXT: Add ${STATIC_IP}/32 to Aiven allowed IP addresses."
echo "Keep 0.0.0.0/0 until the service health check passes; remove it only afterward."
curl --fail --silent --show-error --max-time 60 "$SERVICE_URL/health" || true
echo
