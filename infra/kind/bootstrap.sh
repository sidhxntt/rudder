#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cluster_name="rudder-kind"

command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
command -v kind >/dev/null || { echo "kind is required" >&2; exit 1; }
command -v kubectl >/dev/null || { echo "kubectl is required" >&2; exit 1; }

if ! kind get clusters | grep -Fxq "$cluster_name"; then
  kind create cluster --name "$cluster_name" --config "$root_dir/infra/kind/kind-config.yaml"
fi

# BuildKit runs inside the Compose `rudder` network and therefore resolves the
# registry as `kind-registry:5000`; make that same registry name resolvable
# from Kind nodes so immutable images need no retagging or copy.
docker compose -f "$root_dir/docker-compose.dev.yml" up -d registry
registry_id="$(docker compose -f "$root_dir/docker-compose.dev.yml" ps -q registry)"
if [ -z "$registry_id" ]; then
  echo "could not find the Rudder registry container" >&2
  exit 1
fi
if ! docker inspect "$registry_id" \
  --format '{{range $network, $_ := .NetworkSettings.Networks}}{{println $network}}{{end}}' \
  | grep -Fxq kind; then
  docker network connect --alias kind-registry kind "$registry_id" || true
fi

kubectl config use-context "kind-$cluster_name" >/dev/null
# The control plane runs inside Docker in local development, so Kind's host
# loopback address is not reachable from it. Write a disposable
# Docker-reachable kubeconfig copy for docker-compose.kind.yml. Existing Kind
# clusters created before the host gateway SAN was added cannot verify that
# host name; this dedicated *local-only* copy intentionally skips verification
# until the developer recreates Kind. The host's normal kubeconfig is untouched.
kubectl config view --raw --minify \
  | awk '
      /certificate-authority-data:/ { next }
      /- cluster:/ { print; print "    insecure-skip-tls-verify: true"; next }
      { gsub("https://127.0.0.1:", "https://host.docker.internal:"); print }
    ' \
  > "$root_dir/infra/kind/kubeconfig"
# The upstream ingress-nginx Kind manifest intentionally schedules only on a
# node explicitly marked ingress-ready.  A single-node local cluster must add
# that marker itself or the controller remains Pending while its admission
# webhook starts accepting requests too early.
for _ in $(seq 1 45); do
  kubectl get node "$cluster_name-control-plane" >/dev/null 2>&1 && break
  sleep 2
done
kubectl get node "$cluster_name-control-plane" >/dev/null 2>&1 \
  || { echo "Kind control-plane node did not become discoverable" >&2; exit 1; }
kubectl label node "$cluster_name-control-plane" ingress-ready=true --overwrite >/dev/null
if ! kubectl get deployment -n ingress-nginx ingress-nginx-controller >/dev/null 2>&1; then
  kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
fi
for _ in $(seq 1 45); do
  kubectl get deployment -n ingress-nginx ingress-nginx-controller >/dev/null 2>&1 && break
  sleep 2
done
kubectl get deployment -n ingress-nginx ingress-nginx-controller >/dev/null 2>&1 \
  || { echo "ingress controller deployment did not become discoverable" >&2; exit 1; }
kubectl wait --namespace ingress-nginx \
  --for=condition=Available deployment/ingress-nginx-controller --timeout=180s
for _ in $(seq 1 45); do
  controller_pods="$(kubectl -n ingress-nginx get pods \
    -l app.kubernetes.io/component=controller -o name 2>/dev/null || true)"
  [ -n "$controller_pods" ] && break
  sleep 2
done
[ -n "${controller_pods:-}" ] \
  || { echo "ingress controller pod did not become discoverable" >&2; exit 1; }
kubectl wait --namespace ingress-nginx \
  --for=condition=Ready pod -l app.kubernetes.io/component=controller --timeout=180s
# The Ingress admission webhook is served by the controller pod. Waiting for
# its endpoints avoids an immediately-following Rudder release getting a
# transient HTTP 500 while the Service catches up with the Ready pod.
for _ in $(seq 1 45); do
  endpoints="$(kubectl -n ingress-nginx get endpoints ingress-nginx-controller-admission \
    -o jsonpath='{.subsets[0].addresses[0].ip}' 2>/dev/null || true)"
  [ -n "$endpoints" ] && break
  sleep 2
done
[ -n "${endpoints:-}" ] || { echo "ingress admission endpoint did not become ready" >&2; exit 1; }

echo "Kind runtime ready: cluster=$cluster_name ingress=http://127.0.0.1:8081"
