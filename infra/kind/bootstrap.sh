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
# The control plane usually runs inside Docker during development; its
# loopback address is not the host loopback in Kind's generated kubeconfig.
# Write a disposable Docker-reachable copy for docker-compose.kind.yml.
kubectl config view --raw --minify \
  | sed 's#https://127.0.0.1:#https://host.docker.internal:#' \
  > "$root_dir/infra/kind/kubeconfig"
# The upstream ingress-nginx Kind manifest intentionally schedules only on a
# node explicitly marked ingress-ready.  A single-node local cluster must add
# that marker itself or the controller remains Pending while its admission
# webhook starts accepting requests too early.
kubectl label node "$cluster_name-control-plane" ingress-ready=true --overwrite >/dev/null
if ! kubectl get namespace ingress-nginx >/dev/null 2>&1; then
  kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.12.1/deploy/static/provider/kind/deploy.yaml
fi
kubectl wait --namespace ingress-nginx \
  --for=condition=Available deployment/ingress-nginx-controller --timeout=180s
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
