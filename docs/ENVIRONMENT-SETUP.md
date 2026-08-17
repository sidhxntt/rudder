# Environment configuration guide

This guide covers every configuration variable used by Rudder: local Docker, Kind, GitHub, Phase 7 frontend builds, Phase 8 Advisor, and Phase 4 GKE bootstrap. It never contains real secrets.

## Separate development and production inventories

Use the versioned templates as the canonical shape for each environment:

~~~bash
cp .env.local.development.example .env.local.development
cp .env.local.production.example .env.local.production
~~~

Both resulting files are ignored by Git. Keep the existing .env as the active
local Docker Compose file; it avoids breaking the current stack. Copy values
from .env into .env.local.development yourself, then treat that file as the
development inventory. Production uses .env.local.production only as an
operator checklist: inject its real secrets through Secret Manager and
Kubernetes Secrets, never by copying a dotenv file into the cluster.

The development template has local Docker defaults and optional GitHub/Advisor
placeholders. The production template has the validated GKE topology and lists
which entries must be secret-managed. The templates intentionally never contain
credentials.

## Safe start

~~~bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
openssl rand -hex 32
~~~

Set RUDDER_SECRET_KEYS to the Fernet key, RUDDER_JWT_SECRET to the random hex, choose an admin email/password, and generate a separate RUDDER_AGENT_SHARED_SECRET. Never commit .env or paste its values into chat.

Compose loads .env into the control plane and agent, then overrides container-only URLs such as RUDDER_DATABASE_URL, RUDDER_BUILDKIT_ADDR, and RUDDER_AGENT_URL. Host defaults in .env.example are for local tools; Docker services use service DNS.

## Required local Docker values

| Variable | Source | Safe local rule |
| --- | --- | --- |
| POSTGRES_USER | Choose | rudder is fine locally. |
| POSTGRES_PASSWORD | Choose | Do not expose the sample value outside the laptop. |
| POSTGRES_DB | Choose | rudder is the default. |
| RUDDER_SECRET_KEYS | Fernet command above | One or more comma-separated Fernet keys. First key encrypts new values; retain old keys during rotation. |
| RUDDER_JWT_SECRET | openssl command above | Random session-signing secret. |
| RUDDER_ADMIN_EMAIL | Choose | Seeded only on first start. |
| RUDDER_ADMIN_PASSWORD | Choose | Change the template value; seeded only on first start. |
| RUDDER_AGENT_SHARED_SECRET | openssl command above | Must match every agent. |
| RUDDER_TLS_MODE | Choose | off for local Docker and Kind. |
| RUDDER_BASE_DOMAIN | Choose | localhost for local Docker and Kind. |
| RUDDER_RUNTIME | Choose | docker for docker-compose.dev.yml. |
| RUDDER_KUBERNETES_TARGET | Choose | kind locally; do not set gke until production prerequisites are ready. |

~~~bash
docker compose -f docker-compose.dev.yml up -d --build
docker compose -f docker-compose.dev.yml ps
curl -fsS http://localhost:8000/healthz
~~~

Docker Desktop needs this local registry trust for Docker-runtime image pulls:

~~~json
{"insecure-registries":["localhost:5000"]}
~~~

## Control-plane runtime settings

| Variable | Default | Purpose |
| --- | --- | --- |
| RUDDER_DATABASE_URL | local Postgres URL | SQLAlchemy database. Compose replaces localhost with postgres service DNS. |
| RUDDER_JWT_TTL_SECONDS | 43200 | Session lifetime in seconds. |
| RUDDER_REGISTRY | localhost:5000 | Docker/Kind registry; GKE must use Artifact Registry. |
| RUDDER_BUILDKIT_ADDR | tcp://registry:1234 | Docker/Kind BuildKit endpoint; not used by GKE Cloud Build. |
| RUDDER_DOCKER_NETWORK | rudder | Shared Docker network for Traefik and deployed containers. |
| RUDDER_AGENT_URL | http://agent:9000 | Local agent endpoint; Compose overrides it. |
| RUDDER_TRAEFIK_DYNAMIC_DIR | /traefik/dynamic | Writable Traefik dynamic-config mount. |
| RUDDER_BUILD_LOG_DIR | /var/log/rudder/builds | Persistent build-log directory. |
| RUDDER_RUNTIME_LOG_DIR | /var/log/rudder/runtime | Runtime log directory; mount persistent storage in production. |
| RUDDER_HEALTH_TIMEOUT_SECONDS | 60 | Health-check deadline. |
| RUDDER_HEALTH_INTERVAL_SECONDS | 2 | Health probe interval. |
| RUDDER_HEALTH_START_GRACE_SECONDS | 5 | Delay before health checks. |
| RUDDER_HEALTH_SUCCESSES_REQUIRED | 1 | Consecutive successes required for promotion. |
| RUDDER_DRAIN_SECONDS | 10 | Docker release drain period. |
| RUDDER_GITHUB_PR_ENVIRONMENT_LIMIT | 10 | Maximum simultaneous Phase 5 PR environments. |

## Routing and TLS

| Variable | Local Docker / Kind | GKE |
| --- | --- | --- |
| RUDDER_TLS_MODE | off | acme after public DNS and issuer validation |
| RUDDER_BASE_DOMAIN | localhost | must equal RUDDER_KUBERNETES_PUBLIC_DOMAIN |
| RUDDER_ACME_EMAIL | blank | monitored ACME contact email |
| RUDDER_TRAEFIK_HTTP_PORT | 8082 | Compose-only host port; not a Python setting |
| RUDDER_REGISTRY_PORT | 5000 | Compose-only registry port; not a Python setting |

ACME HTTP-01 cannot validate a localhost name. Do not enable acme with a localhost suffix.

## GitHub: three separate features

### Private clone access and deployment webhooks

| Variable | Source | Needed for |
| --- | --- | --- |
| GITHUB_TOKEN | GitHub fine-grained/classic PAT with repository read access | Private-repo clone without a GitHub App installation token |
| RUDDER_GITHUB_WEBHOOK_SECRET | Random shared value configured in GitHub Webhook settings | Signed push and pull_request webhooks |

Webhook payload URL is the public control-plane URL plus /webhooks/github. GitHub cannot reach localhost directly; use a secure tunnel for local webhook development.

### GitHub OAuth user login

Create a GitHub OAuth App. Set all three values, then restart the control plane.

| Variable | Get it from |
| --- | --- |
| RUDDER_GITHUB_OAUTH_CLIENT_ID | OAuth App Client ID |
| RUDDER_GITHUB_OAUTH_CLIENT_SECRET | OAuth App generated client secret |
| RUDDER_GITHUB_OAUTH_REDIRECT_URI | Public Rudder API URL plus /auth/github/callback. Local Docker: http://localhost:8000/auth/github/callback |
| RUDDER_WEB_URL | Browser UI origin after success. Local Next.js: http://localhost:3000; production: the public Rudder web URL |

github_oauth_unavailable means one or more of these are blank.

### GitHub App repository picker

Create a separate GitHub App, grant Contents: Read, and install it on the intended account/repositories.

| Variable | Get it from |
| --- | --- |
| RUDDER_GITHUB_APP_ID | GitHub App settings, App ID |
| RUDDER_GITHUB_APP_SLUG | GitHub App URL/name |
| RUDDER_GITHUB_APP_PRIVATE_KEY | Generated PEM, with newline characters encoded if stored directly in env |
| RUDDER_GITHUB_APP_PRIVATE_KEY_FILE | Preferred path to a mounted PEM; takes precedence over the env value |

Compose mounts the configured PEM read-only at /run/secrets/rudder-github-app.pem. A missing key keeps the integration unavailable instead of crashing the API.

## Phase 7 frontend build values

Static projects are detected only when there is no repository Dockerfile. These are service build_config.build_env values, not global .env values:

| Framework | Allowed browser-public prefix |
| --- | --- |
| Vite | VITE_ |
| Next static export | NEXT_PUBLIC_ |
| Astro static | PUBLIC_ |
| Create React App | REACT_APP_ |

~~~json
{"build_config":{"build_env":{"VITE_API_URL":"https://api.example.com"}}}
~~~

These values are baked into browser assets. Never put a database URL, token, private key, or secret there; a change requires a new deployment.

## Agent settings

| Variable | Default | Rule |
| --- | --- | --- |
| RUDDER_AGENT_BIND | 0.0.0.0 | Listener address |
| RUDDER_AGENT_PORT | 9000 | Listener port |
| RUDDER_AGENT_CONTROL_PLANE_URL | http://localhost:8000 | Control-plane URL reachable from this node |
| RUDDER_AGENT_SHARED_SECRET | secret | Must equal control-plane secret; never use default outside tests |
| RUDDER_AGENT_NODE_HOSTNAME | localhost | Stable unique node identity |
| RUDDER_AGENT_ADVERTISE_ADDRESS | 127.0.0.1 | Private IP/DNS reachable by control plane, not a Docker-only address on multi-host systems |
| RUDDER_AGENT_DRAIN_SECONDS | 10 | Agent fallback drain window |
| RUDDER_AGENT_PROBE_TIMEOUT_SECONDS | 5 | One health probe timeout |
| RUDDER_AGENT_STOP_TIMEOUT_SECONDS | 10 | Docker SIGTERM-to-SIGKILL time |
| RUDDER_AGENT_COMPOSE_STATE_DIR | /var/lib/rudder-agent/compose | Persistent host-local imported-Compose state |

## Local Kind

~~~env
RUDDER_RUNTIME=kubernetes
RUDDER_KUBERNETES_TARGET=kind
RUDDER_REGISTRY=kind-registry:5000
RUDDER_KUBERNETES_LOCAL_DOMAIN=localhost
RUDDER_KUBERNETES_NAMESPACE_PREFIX=rudder
RUDDER_KUBERNETES_INGRESS_CLASS=nginx
RUDDER_LOCAL_KUBERNETES_AUTO_BOOTSTRAP=true
~~~

RUDDER_KUBERNETES_KUBECONFIG is optional; blank uses the normal developer kubeconfig. Keep RUDDER_KUBERNETES_WORKLOAD_POOL=platform. For optional local S3/MinIO backups, set every S3 value below; otherwise leave every one blank:

~~~env
RUDDER_KUBERNETES_BACKUP_S3_ENDPOINT=
RUDDER_KUBERNETES_BACKUP_S3_BUCKET=
RUDDER_KUBERNETES_BACKUP_S3_ACCESS_KEY=
RUDDER_KUBERNETES_BACKUP_S3_SECRET_KEY=
RUDDER_KUBERNETES_BACKUP_S3_REGION=us-east-1
RUDDER_KUBERNETES_BACKUP_SCHEDULE="0 0 2 * * *"
~~~

## GKE production

Never reuse local Docker/Kind registry or backup credentials on GKE.

~~~env
RUDDER_RUNTIME=kubernetes
RUDDER_KUBERNETES_TARGET=gke
RUDDER_KUBERNETES_WORKLOAD_POOL=platform
RUDDER_KUBERNETES_PUBLIC_DOMAIN=<public-domain>
RUDDER_BASE_DOMAIN=<same-public-domain>
RUDDER_KUBERNETES_CERTIFICATE_ISSUER=<existing-clusterissuer>
RUDDER_REGISTRY=<region>-docker.pkg.dev/<project>/<repository>
RUDDER_GCP_PROJECT_ID=<google-cloud-project-id>
RUDDER_GCP_REGION=<gke-region>
RUDDER_GCP_BUILD_SOURCE_BUCKET=<private-source-bucket>
RUDDER_GCP_BUILD_LOGS_BUCKET=<private-build-log-bucket>
RUDDER_GCP_BUILD_SERVICE_ACCOUNT=<cloud-build-publisher-gsa-email>
RUDDER_KUBERNETES_API_SERVER_ENDPOINT_CIDR=<private-gke-api-cidr>/32
~~~

GKE uses in-cluster Workload Identity, not a local kubeconfig. Set RUDDER_KUBERNETES_POSTGRES_OPERATOR=cloudnativepg only after that operator is installed.

For local Kind deployments that use CloudNativePG, set
`RUDDER_KUBERNETES_API_SERVER_ENDPOINT_CIDR=10.96.0.1/32`. Rudder's private
network policy then permits the managed PostgreSQL instance to reach the
in-cluster Kubernetes API during initialization.

If port 5000 is unavailable locally, use another free port consistently, for
example `RUDDER_REGISTRY=localhost:5001` and `RUDDER_REGISTRY_PORT=5001`.
Add that same address to Docker Desktop's `insecure-registries`; Rudder's
local registry intentionally uses HTTP only.

### GKE bootstrap-script inputs

These are used by infra/gcp/scripts/bootstrap-platform.sh or preflight-gke.sh, not the Python settings model.

| Variable | Source |
| --- | --- |
| RUDDER_GCP_PROJECT | Google Cloud project ID |
| RUDDER_GCP_REGION | Regional GKE location |
| RUDDER_GKE_CLUSTER | Existing regional cluster name |
| RUDDER_DNS_NAME | Delegated Cloud DNS suffix, no trailing dot |
| RUDDER_GCP_DNS_ZONE | Cloud DNS managed-zone resource name |
| RUDDER_CONTROL_PLANE_IMAGE | Immutable Artifact Registry digest |
| RUDDER_CONTROL_PLANE_SECRET_NAME | Existing Secret Manager secret |
| RUDDER_CONTROL_PLANE_HOST | Public API/UI hostname under the public domain |
| RUDDER_CERT_MANAGER_GSA | GSA bound to cert-manager Workload Identity |
| RUDDER_RUNTIME_GSA | GSA bound to Rudder runtime |
| RUDDER_BACKUP_BUCKET | Approved GCS backup bucket |
| RUDDER_BACKUP_GSA | GSA for CNPG backup identity |
| RUDDER_BACKUP_IDENTITY_BROKER_GSA | GSA for private identity broker |
| RUDDER_SECRET_SYNC_GSA | GSA for Secret Manager synchronization |
| EXTERNAL_DNS_CHART_VERSION | Reviewed pinned Helm chart version; never latest |
| RUDDER_REQUIRED_GKE_CPUS | Optional total CPU preflight requirement; default 12 |
| RUDDER_REQUIRED_WORKLOAD_CPUS | Optional available workload CPU requirement; default 0 |
| RUDDER_TF_STATE_BUCKET | Versioned, public-access-prevented GCS bucket for Terraform state; used by bootstrap-state.sh |

~~~bash
RUDDER_GCP_PROJECT=<project> \
RUDDER_GCP_REGION=<region> \
RUDDER_GKE_CLUSTER=<cluster> \
RUDDER_KUBERNETES_WORKLOAD_POOL=platform \
bash infra/gcp/scripts/preflight-gke.sh
~~~

### GKE CloudNativePG backups

GKE rejects every RUDDER_KUBERNETES_BACKUP_S3_* credential. Use GCS and Workload Identity only after the identity broker is live:

~~~env
RUDDER_KUBERNETES_BACKUP_GCS_BUCKET=<approved-gcs-bucket>
RUDDER_KUBERNETES_BACKUP_GCP_SERVICE_ACCOUNT=rudder-backup@<project>.iam.gserviceaccount.com
RUDDER_KUBERNETES_BACKUP_IDENTITY_BROKER_URL=http://<private-broker-service>
RUDDER_KUBERNETES_BACKUP_GCS_IDENTITY_READY=true
~~~

Do not set identity-ready true until the broker has created and verified the exact per-environment binding.

## Advisor, web, and SDK

| Variable | Used by | Source |
| --- | --- | --- |
| OPENAI_API_KEY | Phase 8 Advisor and read-only operator assistant | OpenAI API keys page; optional. Leave blank to keep deterministic Rudder features available without model-backed diagnosis or chat. |
| RUDDER_API_URL | web development client | Optional browser API base URL |
| RUDDER_URL | SDK generator | Optional OpenAPI URL; defaults to http://localhost:8000 |

## Validate without exposing secrets

~~~bash
docker compose -f docker-compose.dev.yml config --quiet
docker compose -f docker-compose.dev.yml ps
curl -fsS http://localhost:8000/healthz

awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' .env.example | sort -u > /tmp/rudder-example-keys
awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{print $1}' .env | sort -u > /tmp/rudder-current-keys
comm -23 /tmp/rudder-example-keys /tmp/rudder-current-keys
~~~

After changing .env, restart affected local services:

~~~bash
docker compose -f docker-compose.dev.yml restart control-plane agent
~~~

Changing runtime, registry, Kubernetes target, domain, TLS, or GKE variables is not a routine restart: review the relevant infrastructure phase first.
