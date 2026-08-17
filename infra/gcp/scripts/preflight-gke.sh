#!/usr/bin/env bash
# Read-only Phase 4 capacity and identity checks. It intentionally creates
# nothing and must pass before enabling the regional workloads node pool.
set -euo pipefail

: "${RUDDER_GCP_PROJECT:?Set RUDDER_GCP_PROJECT}"
: "${RUDDER_GCP_REGION:?Set RUDDER_GCP_REGION}"
: "${RUDDER_GKE_CLUSTER:?Set RUDDER_GKE_CLUSTER}"
: "${RUDDER_KUBERNETES_WORKLOAD_POOL:?Set RUDDER_KUBERNETES_WORKLOAD_POOL}"

# The current approved topology shares the tainted platform pool with customer
# releases. A later dedicated workloads-pool migration needs six additional
# vCPUs, but this check must not reject the valid 12-vCPU shared-pool setup.
required_total_cpus="${RUDDER_REQUIRED_GKE_CPUS:-12}"
required_available_cpus="${RUDDER_REQUIRED_WORKLOAD_CPUS:-0}"
expected_workload_pool="${RUDDER_GCP_PROJECT}.svc.id.goog"

command -v gcloud >/dev/null || {
  printf 'gcloud is required for the GKE preflight.\n' >&2
  exit 1
}
command -v jq >/dev/null || {
  printf 'jq is required for the GKE preflight.\n' >&2
  exit 1
}

# Terraform's Google provider uses Application Default Credentials rather than
# merely the active gcloud account. Check that credential explicitly so a plan
# cannot fail later with an opaque invalid_grant or RAPT error.
if ! gcloud auth application-default print-access-token >/dev/null 2>&1; then
  cat >&2 <<'EOF'
Terraform Application Default Credentials are unavailable or expired.
Run `gcloud auth application-default login`, complete the browser flow, then
rerun this preflight. This command only refreshes local operator credentials;
it does not modify cloud resources.
EOF
  exit 1
fi

# GKE rejects regional node-pool creation against the project-wide
# `CPUS_ALL_REGIONS` quota. The regional `CPUS` entry can show capacity that
# GKE still cannot use, so reading it would permit a deployment that fails.
project_info="$(gcloud compute project-info describe \
  --project "$RUDDER_GCP_PROJECT" \
  --format=json)"
# gcloud represents Compute quota values as decimals (for example `12.0`).
# Convert them before Bash arithmetic so a quota shortfall always fails closed.
quota_limit="$(jq -er '.quotas[] | select(.metric == "CPUS_ALL_REGIONS") | (.limit | tonumber | floor)' <<<"$project_info")"
quota_usage="$(jq -er '.quotas[] | select(.metric == "CPUS_ALL_REGIONS") | (.usage | tonumber | floor)' <<<"$project_info")"
available_cpus="$((quota_limit - quota_usage))"

cluster="$(gcloud container clusters describe "$RUDDER_GKE_CLUSTER" \
  --region "$RUDDER_GCP_REGION" \
  --project "$RUDDER_GCP_PROJECT" \
  --format=json)"
cluster_status="$(jq -er '.status' <<<"$cluster")"
workload_pool="$(jq -er '.workloadIdentityConfig.workloadPool' <<<"$cluster")"
platform_pool="$(jq -er '.nodePools[] | select(.name == "platform")' <<<"$cluster")"

if [[ "$cluster_status" != "RUNNING" ]]; then
  printf 'GKE cluster %s is %s; expected RUNNING.\n' "$RUDDER_GKE_CLUSTER" "$cluster_status" >&2
  exit 1
fi

if [[ "$workload_pool" != "$expected_workload_pool" ]]; then
  printf 'GKE Workload Identity pool is %s; expected %s.\n' "$workload_pool" "$expected_workload_pool" >&2
  exit 1
fi

if [[ "$RUDDER_KUBERNETES_WORKLOAD_POOL" != "platform" ]]; then
  cat >&2 <<'EOF'
The current quota-approved GKE topology requires
RUDDER_KUBERNETES_WORKLOAD_POOL=platform. Do not select a dedicated workloads
pool until CPUS_ALL_REGIONS is increased and Terraform creates that pool.
EOF
  exit 1
fi

platform_label="$(jq -er '.config.labels["rudder.pool"] // empty' <<<"$platform_pool")"
platform_taint="$(jq -er '[.config.taints[]? | select(.key == "rudder.pool" and .value == "platform" and .effect == "NO_SCHEDULE")] | length' <<<"$platform_pool")"
if [[ "$platform_label" != "platform" || "$platform_taint" != "1" ]]; then
  printf 'The platform node pool must have label rudder.pool=platform and its NoSchedule taint.\n' >&2
  exit 1
fi

if (( quota_limit < required_total_cpus || available_cpus < required_available_cpus )); then
  cat >&2 <<EOF
GKE aggregate CPU quota is insufficient for the workloads node pool.
Project CPUS_ALL_REGIONS: ${quota_usage} used / ${quota_limit} limit (${available_cpus} available).
Need at least ${required_total_cpus} total and ${required_available_cpus} available vCPUs.
Request a project-wide CPUS_ALL_REGIONS quota increase before setting enable_workloads_pool = true.
EOF
  exit 1
fi

printf 'GKE preflight passed: %s is RUNNING with Workload Identity %s.\n' \
  "$RUDDER_GKE_CLUSTER" "$workload_pool"
printf 'Project CPUS_ALL_REGIONS: %s used / %s limit (%s available).\n' \
  "$quota_usage" "$quota_limit" "$available_cpus"
