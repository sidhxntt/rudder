#!/usr/bin/env bash
set -euo pipefail

: "${RUDDER_GCP_PROJECT:?Set RUDDER_GCP_PROJECT}"
: "${RUDDER_TF_STATE_BUCKET:?Set RUDDER_TF_STATE_BUCKET}"
: "${RUDDER_GCP_REGION:=asia-south1}"

if ! gcloud storage buckets describe "gs://${RUDDER_TF_STATE_BUCKET}" --project "$RUDDER_GCP_PROJECT" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${RUDDER_TF_STATE_BUCKET}" \
    --project "$RUDDER_GCP_PROJECT" \
    --location "$RUDDER_GCP_REGION" \
    --uniform-bucket-level-access
fi

gcloud storage buckets update "gs://${RUDDER_TF_STATE_BUCKET}" --versioning
gcloud storage buckets update "gs://${RUDDER_TF_STATE_BUCKET}" --public-access-prevention

printf 'Initialise Terraform with:\n\n'
printf '  terraform -chdir=infra/gcp/terraform init -backend-config="bucket=%s" -backend-config="prefix=rudder/production"\n' "$RUDDER_TF_STATE_BUCKET"
