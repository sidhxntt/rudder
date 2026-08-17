#!/usr/bin/env bash
# Configure an operator kubeconfig for the Rudder GKE cluster.
# This is deliberately an operator-only helper. The deployed control plane
# authenticates in-cluster through Workload Identity instead.
set -euo pipefail

: "${RUDDER_GCP_PROJECT:?Set RUDDER_GCP_PROJECT}"
: "${RUDDER_GCP_REGION:?Set RUDDER_GCP_REGION}"
: "${RUDDER_GKE_CLUSTER:?Set RUDDER_GKE_CLUSTER}"

gcloud container clusters get-credentials "$RUDDER_GKE_CLUSTER" \
  --region "$RUDDER_GCP_REGION" \
  --project "$RUDDER_GCP_PROJECT" \
  --dns-endpoint

expected_context="gke_${RUDDER_GCP_PROJECT}_${RUDDER_GCP_REGION}_${RUDDER_GKE_CLUSTER}"
actual_context="$(kubectl config current-context)"
if [[ "$actual_context" != "$expected_context" ]]; then
  printf 'Expected kube context %s, got %s\n' "$expected_context" "$actual_context" >&2
  exit 1
fi

printf 'kubectl is configured for %s\n' "$actual_context"
