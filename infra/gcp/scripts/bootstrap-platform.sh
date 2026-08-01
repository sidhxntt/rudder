#!/usr/bin/env bash
# Install the portable, cluster-wide Rudder platform prerequisites.
#
# The control-plane image and every Helm chart version are explicit inputs.
# This prevents an operator command from silently moving a production cluster
# to a different chart release or running an unreviewed image.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../../.." && pwd)"
platform_dir="$repo_root/infra/kubernetes/platform"

: "${RUDDER_GCP_PROJECT:?Set RUDDER_GCP_PROJECT}"
: "${RUDDER_GCP_REGION:?Set RUDDER_GCP_REGION}"
: "${RUDDER_GKE_CLUSTER:?Set RUDDER_GKE_CLUSTER}"
: "${RUDDER_RUNTIME_GSA:?Set RUDDER_RUNTIME_GSA to the rudder-runtime service-account email}"
: "${RUDDER_BACKUP_BUCKET:?Set RUDDER_BACKUP_BUCKET to the private GCS backup bucket}"
: "${RUDDER_BACKUP_GSA:?Set RUDDER_BACKUP_GSA to the dedicated CloudNativePG backup service-account email}"
: "${RUDDER_BACKUP_IDENTITY_BROKER_GSA:?Set RUDDER_BACKUP_IDENTITY_BROKER_GSA to the broker service-account email}"
: "${RUDDER_SECRET_SYNC_GSA:?Set RUDDER_SECRET_SYNC_GSA to the dedicated Secret Manager reader service-account email}"
: "${RUDDER_CERT_MANAGER_GSA:?Set RUDDER_CERT_MANAGER_GSA to the rudder-cert-manager service-account email}"
: "${RUDDER_CONTROL_PLANE_IMAGE:?Set RUDDER_CONTROL_PLANE_IMAGE to an immutable Artifact Registry digest}"
: "${RUDDER_CONTROL_PLANE_HOST:?Set RUDDER_CONTROL_PLANE_HOST to the public HTTPS control-plane hostname}"
: "${RUDDER_KUBERNETES_PUBLIC_DOMAIN:?Set RUDDER_KUBERNETES_PUBLIC_DOMAIN to the delegated public Rudder suffix}"
: "${RUDDER_REGISTRY:?Set RUDDER_REGISTRY to the Artifact Registry hostname/repository}"
: "${RUDDER_GCP_BUILD_SOURCE_BUCKET:?Set RUDDER_GCP_BUILD_SOURCE_BUCKET to the private Cloud Build source bucket}"
: "${RUDDER_GCP_BUILD_LOGS_BUCKET:?Set RUDDER_GCP_BUILD_LOGS_BUCKET to the private Cloud Build logs bucket}"
: "${RUDDER_GCP_BUILD_SERVICE_ACCOUNT:?Set RUDDER_GCP_BUILD_SERVICE_ACCOUNT to the dedicated Cloud Build publisher service-account email}"
: "${RUDDER_CONTROL_PLANE_SECRET_NAME:?Set RUDDER_CONTROL_PLANE_SECRET_NAME to the Secret Manager JSON secret name}"
: "${RUDDER_ACME_EMAIL:?Set RUDDER_ACME_EMAIL for the ACME account}"
: "${RUDDER_KUBERNETES_CERTIFICATE_ISSUER:?Set RUDDER_KUBERNETES_CERTIFICATE_ISSUER}"
: "${RUDDER_DNS_NAME:?Set RUDDER_DNS_NAME to the delegated Rudder DNS suffix}"
: "${RUDDER_GCP_DNS_ZONE:?Set RUDDER_GCP_DNS_ZONE to the Cloud DNS managed-zone resource name}"
: "${INGRESS_NGINX_CHART_VERSION:?Set INGRESS_NGINX_CHART_VERSION}"
: "${CERT_MANAGER_CHART_VERSION:?Set CERT_MANAGER_CHART_VERSION}"
: "${EXTERNAL_SECRETS_CHART_VERSION:?Set EXTERNAL_SECRETS_CHART_VERSION}"
: "${EXTERNAL_DNS_CHART_VERSION:?Set EXTERNAL_DNS_CHART_VERSION}"
: "${CNPG_CHART_VERSION:?Set CNPG_CHART_VERSION}"

fail() {
  printf 'Phase 4 bootstrap preflight failed: %s\n' "$*" >&2
  exit 1
}

# The manifests cannot validate operator inputs. Fail before installing a
# platform component when the image is mutable, the registry is not Artifact
# Registry, or a hostname falls outside the delegated Rudder DNS suffix.
expected_registry_prefix="${RUDDER_GCP_REGION}-docker.pkg.dev/${RUDDER_GCP_PROJECT}/"
[[ "$RUDDER_REGISTRY" == "$expected_registry_prefix"* ]] || fail \
  "RUDDER_REGISTRY must be an Artifact Registry repository below ${expected_registry_prefix}."
[[ "$RUDDER_CONTROL_PLANE_IMAGE" == "$RUDDER_REGISTRY/"*"@sha256:"* ]] || fail \
  "RUDDER_CONTROL_PLANE_IMAGE must be an immutable digest in RUDDER_REGISTRY."

public_domain="${RUDDER_KUBERNETES_PUBLIC_DOMAIN%.}"
dns_suffix="${RUDDER_DNS_NAME%.}"
[[ "$public_domain" == "$dns_suffix" || "$public_domain" == *".${dns_suffix}" ]] || fail \
  "RUDDER_KUBERNETES_PUBLIC_DOMAIN must equal or be below RUDDER_DNS_NAME."
[[ "$RUDDER_CONTROL_PLANE_HOST" == *".${public_domain}" ]] || fail \
  "RUDDER_CONTROL_PLANE_HOST must be a hostname below RUDDER_KUBERNETES_PUBLIC_DOMAIN."

command -v gcloud >/dev/null || fail "gcloud is required to verify the runtime secret."
gcloud secrets describe "$RUDDER_CONTROL_PLANE_SECRET_NAME" \
  --project "$RUDDER_GCP_PROJECT" >/dev/null || fail \
  "Secret Manager secret ${RUDDER_CONTROL_PLANE_SECRET_NAME} does not exist or is not readable."

"$script_dir/configure-kubectl.sh"

kubectl apply -f "$platform_dir/namespace.yaml"
kubectl apply -f "$platform_dir/rbac.yaml"
kubectl apply -f "$platform_dir/ingress-nginx.yaml"
kubectl apply -f "$platform_dir/cert-manager.yaml"

# Bootstrap is intentionally safe to resume after a transient failure. Helm
# otherwise treats an already-configured repository as an error and aborts
# before it can resume the database migration or control-plane rollout.
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx --force-update >/dev/null
helm repo add jetstack https://charts.jetstack.io --force-update >/dev/null
helm repo add external-secrets https://charts.external-secrets.io --force-update >/dev/null
helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/ --force-update >/dev/null
helm repo add cloudnative-pg https://cloudnative-pg.github.io/charts --force-update >/dev/null
helm repo update >/dev/null

helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace \
  --version "$INGRESS_NGINX_CHART_VERSION" \
  --set controller.nodeSelector.rudder\\.pool=platform \
  --set 'controller.tolerations[0].key=rudder.pool' \
  --set 'controller.tolerations[0].operator=Equal' \
  --set 'controller.tolerations[0].value=platform' \
  --set 'controller.tolerations[0].effect=NoSchedule' \
  --set controller.service.externalTrafficPolicy=Local \
  --wait --timeout 10m
helm upgrade --install cert-manager jetstack/cert-manager \
  --namespace cert-manager --create-namespace \
  --version "$CERT_MANAGER_CHART_VERSION" \
  --set serviceAccount.annotations."iam\\.gke\\.io/gcp-service-account"="$RUDDER_CERT_MANAGER_GSA" \
  --set crds.enabled=true \
  --wait --timeout 10m
helm upgrade --install external-secrets external-secrets/external-secrets \
  --namespace external-secrets --create-namespace \
  --version "$EXTERNAL_SECRETS_CHART_VERSION" \
  --wait --timeout 10m
export RUDDER_GCP_PROJECT RUDDER_GCP_REGION RUDDER_GKE_CLUSTER RUDDER_DNS_NAME
envsubst < "$platform_dir/external-dns-values.yaml" | helm upgrade --install external-dns external-dns/external-dns \
  --namespace external-dns --create-namespace \
  --version "$EXTERNAL_DNS_CHART_VERSION" \
  --values - \
  --wait --timeout 10m
helm upgrade --install cloudnative-pg cloudnative-pg/cloudnative-pg \
  --namespace cnpg-system --create-namespace \
  --version "$CNPG_CHART_VERSION" \
  --wait --timeout 10m

for deployment in \
  'ingress-nginx/ingress-nginx-controller' \
  'cert-manager/cert-manager' \
  'cert-manager/cert-manager-webhook' \
  'external-secrets/external-secrets' \
  'external-dns/external-dns' \
  'cnpg-system/cloudnative-pg'; do
  namespace="${deployment%%/*}"
  name="${deployment##*/}"
  kubectl -n "$namespace" wait --for=condition=Available "deployment/$name" --timeout=10m
done

export RUDDER_GCP_PROJECT RUDDER_GCP_REGION RUDDER_GKE_CLUSTER RUDDER_RUNTIME_GSA
export RUDDER_BACKUP_BUCKET RUDDER_BACKUP_GSA RUDDER_BACKUP_IDENTITY_BROKER_GSA
export RUDDER_SECRET_SYNC_GSA RUDDER_CONTROL_PLANE_IMAGE RUDDER_CONTROL_PLANE_SECRET_NAME
export RUDDER_CONTROL_PLANE_HOST RUDDER_KUBERNETES_PUBLIC_DOMAIN RUDDER_REGISTRY
export RUDDER_ACME_EMAIL RUDDER_KUBERNETES_CERTIFICATE_ISSUER RUDDER_GCP_DNS_ZONE

# Sync runtime credentials before creating an API Pod. The Secret Manager
# version itself is an explicit operator-managed prerequisite; a missing value
# fails here rather than producing an opaque CrashLoopBackOff later.
envsubst < "$platform_dir/external-secrets.yaml" | kubectl apply -f -
kubectl -n rudder-system wait --for=condition=Ready secretstore/rudder-gcp-secret-manager --timeout=5m
kubectl -n rudder-system wait --for=condition=Ready externalsecret/rudder-control-plane-runtime --timeout=5m
kubectl -n rudder-system wait --for=create secret/rudder-control-plane-runtime --timeout=5m

# The platform database and its schema are first-class prerequisites. CNPG
# publishes the application URI only after its writable service is ready.
envsubst < "$platform_dir/control-plane-database.yaml" | kubectl apply -f -
kubectl -n rudder-system wait --for=condition=Ready cluster.postgresql.cnpg.io/rudder-control-plane-db --timeout=15m
kubectl -n rudder-system wait --for=create secret/rudder-control-plane-db-app --timeout=5m
kubectl -n rudder-system delete job/rudder-control-plane-migrate --ignore-not-found --wait=true
envsubst < "$platform_dir/control-plane-migration.yaml" | kubectl apply -f -
kubectl -n rudder-system wait --for=condition=complete job/rudder-control-plane-migrate --timeout=10m

# Only a migrated, configured API receives a Service and public Ingress.
envsubst < "$platform_dir/control-plane.yaml" | kubectl apply -f -
envsubst < "$platform_dir/backup-identity-broker.yaml" | kubectl apply -f -
envsubst < "$platform_dir/cluster-issuer.yaml" | kubectl apply -f -
envsubst < "$platform_dir/control-plane-ingress.yaml" | kubectl apply -f -
kubectl apply -f "$platform_dir/cloudnativepg.yaml"

kubectl -n rudder-system wait --for=condition=Available deployment/rudder-control-plane --timeout=10m
kubectl -n rudder-system wait --for=condition=Available deployment/rudder-backup-identity-broker --timeout=10m
kubectl wait --for=condition=Ready "clusterissuer/$RUDDER_KUBERNETES_CERTIFICATE_ISSUER" --timeout=5m
kubectl auth can-i delete persistentvolumeclaims \
  --as=system:serviceaccount:rudder-system:rudder-control-plane \
  --all-namespaces | grep -qx no

printf 'Rudder production platform is ready.\n'
