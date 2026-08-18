# Rudder configuration

This guide maps Rudder's configuration surfaces without duplicating live
values. [`.env.example`](../.env.example) is the authoritative local template;
the Pydantic settings in
[`control-plane/rudder_cp/config.py`](../control-plane/rudder_cp/config.py) are
the authoritative control-plane validation rules.

Never commit populated `.env` files, private keys, bearer tokens, database
passwords, Fernet keys, JWT secrets, or cloud credentials.

## Local control plane

Copy `.env.example` to `.env` and set the required local identity and secret
values:

```bash
cp .env.example .env
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
openssl rand -hex 32
```

Use the generated values for `RUDDER_SECRET_KEYS` and `RUDDER_JWT_SECRET`, then
set `RUDDER_ADMIN_EMAIL` and `RUDDER_ADMIN_PASSWORD`. The development database,
registry, BuildKit, Docker network, node agent, Traefik directory, and build-log
defaults are already grouped in `.env.example`.

Start and migrate the local stack:

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml run --rm control-plane alembic upgrade head
docker compose -f docker-compose.dev.yml restart control-plane
```

## GitHub authentication and delivery

GitHub OAuth browser sign-in uses:

- `RUDDER_GITHUB_OAUTH_CLIENT_ID`
- `RUDDER_GITHUB_OAUTH_CLIENT_SECRET`
- `RUDDER_GITHUB_OAUTH_REDIRECT_URI`
- `RUDDER_WEB_URL`

Repository import and signed delivery use the GitHub App settings:

- `RUDDER_GITHUB_APP_ID`
- `RUDDER_GITHUB_APP_SLUG`
- either `RUDDER_GITHUB_APP_PRIVATE_KEY` or
  `RUDDER_GITHUB_APP_PRIVATE_KEY_FILE`
- `RUDDER_GITHUB_WEBHOOK_SECRET`

The callback and webhook URLs configured in GitHub must match the reachable
Rudder endpoints. Do not place a private key directly in shell history.

## Runtime selection

`RUDDER_RUNTIME=docker` selects the Docker/node-agent path.
`RUDDER_RUNTIME=kubernetes` selects the Kubernetes adapter and requires the
matching Kubernetes settings. Important shared controls include:

- `RUDDER_KUBERNETES_TARGET` (`kind` locally or `gke` for the cloud reference)
- `RUDDER_KUBERNETES_KUBECONFIG`
- `RUDDER_KUBERNETES_NAMESPACE_PREFIX`
- `RUDDER_KUBERNETES_INGRESS_CLASS`
- `RUDDER_KUBERNETES_WORKLOAD_POOL`
- `RUDDER_KUBERNETES_READINESS_TIMEOUT_SECONDS`

For local Kind, use `make kind-up`, `make kind-control-plane`, and
`make verify-kind`. `RUDDER_LOCAL_KUBERNETES_AUTO_BOOTSTRAP` controls whether a
local GitHub import may start/reuse the Kind runtime automatically.

## GKE and public routing

The GKE control plane validates that the runtime target, public domain,
certificate issuer, registry, build buckets, build identity, and workload pool
form a coherent configuration. The principal runtime settings are:

- `RUDDER_GCP_PROJECT_ID`, `RUDDER_GCP_REGION`
- `RUDDER_GCP_BUILD_SOURCE_BUCKET`, `RUDDER_GCP_BUILD_LOGS_BUCKET`
- `RUDDER_GCP_BUILD_SERVICE_ACCOUNT`
- `RUDDER_REGISTRY`
- `RUDDER_BASE_DOMAIN`, `RUDDER_KUBERNETES_PUBLIC_DOMAIN`
- `RUDDER_KUBERNETES_CERTIFICATE_ISSUER`
- `RUDDER_KUBERNETES_API_SERVER_ENDPOINT_CIDR`

The platform bootstrap script also requires operator inputs such as
`RUDDER_GKE_CLUSTER`, workload-identity service accounts, delegated DNS names,
the immutable control-plane image digest, and the Secret Manager container.
Those inputs are validated at the start of
[`infra/gcp/scripts/bootstrap-platform.sh`](../infra/gcp/scripts/bootstrap-platform.sh).
Follow [GKE operations](gke-operations.md) rather than trying to infer the
production sequence from individual manifests.

## Backups

Local Kind/S3-compatible backup testing uses the
`RUDDER_KUBERNETES_BACKUP_S3_*` group. The GKE reference uses native GCS and
Workload Identity through:

- `RUDDER_KUBERNETES_BACKUP_GCS_BUCKET`
- `RUDDER_KUBERNETES_BACKUP_GCP_SERVICE_ACCOUNT`
- `RUDDER_KUBERNETES_BACKUP_GCS_IDENTITY_READY`
- `RUDDER_KUBERNETES_BACKUP_IDENTITY_BROKER_URL`
- `RUDDER_KUBERNETES_BACKUP_SCHEDULE`

GKE validation rejects static S3 credentials. A successful backup request is
not proof of recoverability; use a restore drill.

## CLI

The Node/TypeScript CLI recognizes:

- `RUDDER_URL` for the control-plane endpoint;
- `RUDDER_TOKEN` as a process-local automation credential;
- `RUDDER_CONFIG` to override the local config-file path;
- `RUDDER_WEB_URL` when constructing the browser authorization URL.

Interactive credentials and selected context are stored in the local config
file. Treat that file as sensitive. See [`cli/README.md`](../cli/README.md).

## Optional AI assistance

Rudder Advisor's deterministic repository scan does not require a model key.
Model-assisted diagnosis and Ask Rudder require an operator-supplied
`OPENAI_API_KEY`. Repository content and logs are untrusted inputs; model output
is advisory and has no direct mutation authority.

## Authoritative references

- Local defaults: [`.env.example`](../.env.example)
- Control-plane validation: [`config.py`](../control-plane/rudder_cp/config.py)
- GKE Terraform inputs: [`infra/gcp/terraform/variables.tf`](../infra/gcp/terraform/variables.tf)
- GKE operator inputs: [`bootstrap-platform.sh`](../infra/gcp/scripts/bootstrap-platform.sh)
- CLI configuration: [`cli/README.md`](../cli/README.md)
