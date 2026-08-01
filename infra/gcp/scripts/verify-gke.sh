#!/usr/bin/env bash
# Read-only Phase 4 acceptance checks. It intentionally creates nothing.
set -euo pipefail

: "${RUDDER_GCP_PROJECT:?Set RUDDER_GCP_PROJECT}"
: "${RUDDER_GCP_REGION:?Set RUDDER_GCP_REGION}"
: "${RUDDER_GKE_CLUSTER:?Set RUDDER_GKE_CLUSTER}"

"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/configure-kubectl.sh"

kubectl get nodes -L rudder.pool
kubectl get pods -A
# A cluster with Ready nodes is not usable if CoreDNS cannot schedule. Check
# it before treating the Rudder platform deployment as an acceptance failure.
kubectl -n kube-system rollout status deployment/kube-dns --timeout=5m
kubectl -n kube-system wait --for=condition=Ready pod -l k8s-app=kube-dns --timeout=5m
kubectl -n rudder-system get serviceaccount rudder-control-plane
kubectl auth can-i delete persistentvolumeclaims \
  --as=system:serviceaccount:rudder-system:rudder-control-plane \
  --all-namespaces | grep -qx no

printf 'Phase 4 GKE read-only verification passed.\n'
