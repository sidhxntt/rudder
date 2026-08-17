# Rudder

A self-hosted, Railway-style PaaS with a canvas UI. Point it at a git repo —
FastAPI, Express, Go, anything — and it builds, runs, and serves that app on a
public URL, on your own hardware. Operate it from the canvas, a CLI, or an SDK.

Single-tenant by design. This is a learning build, not a multi-tenant product.

**Specification lives in [`docs/`](docs/).** [`docs/PRD.md`](docs/PRD.md) is the
source of truth; [`docs/phases/`](docs/phases/) holds the build instructions.

---

## Layout

```
docker-compose.dev.yml     postgres, registry, buildkitd, traefik, control plane, agent
infra/traefik/             static config + the dynamic dir the control plane writes into
control-plane/             FastAPI + SQLModel. Owns desired state.
agent/                     aiohttp + docker SDK. Owns actual state on one host.
sdk-python/                generated from OpenAPI (Phase 1 step 9)
cli/                       `rudder` — thin wrapper over the SDK
web/                       Next.js 15 + React Flow canvas
docs/                      PRD, phase plans, ADRs, design tokens
```

## Setup

```bash
cp .env.example .env
# fill in RUDDER_SECRET_KEYS, RUDDER_JWT_SECRET, RUDDER_ADMIN_*
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
openssl rand -hex 32

docker compose -f docker-compose.dev.yml up -d
# Migrate with `run`, not `exec`: the control plane cannot start against an
# empty database, so on a cold start there is no container to exec into.
docker compose -f docker-compose.dev.yml run --rm control-plane alembic upgrade head
docker compose -f docker-compose.dev.yml restart control-plane
```

On Docker 29 the local registry needs no daemon change — `127.0.0.0/8` is
already trusted as insecure by default. On older daemons, add
`{"insecure-registries": ["localhost:5000"]}` under Docker Desktop → Settings →
Docker Engine, or every pull fails with `server gave HTTP response to HTTPS
client`, which looks unrelated to the real cause.

Check it:

```bash
curl localhost:8000/healthz     # control plane
curl localhost:9000/healthz     # node agent
open http://localhost:8000/docs # OpenAPI
open http://localhost:8080      # Traefik dashboard (dev only)
```

## Status

**Phase 1's deploy pipeline works end to end on real infrastructure.** An
actual GitHub push passed through a signed webhook into live Postgres, BuildKit,
the local registry, Docker, and Traefik on 2026-07-24. The Step 9 SDK and CLI
build successfully; a browser-free CLI create → deploy with followed logs →
routed HTTP 200 cycle was verified on the same day. The Step 10 canvas passes a
production Next.js build. See
[`docs/phases/PHASE-1-single-host.md`](docs/phases/PHASE-1-single-host.md).

Verified on the live stack, not with fakes:

| Check | Result |
|---|---|
| Node repo deploys and serves | `api.production.localhost` → HTTP 200 |
| Python repo deploys and serves | `pyapi.production.localhost` → HTTP 200 |
| GitHub push deployment | GitHub delivery → signed webhook → `webhook-e2e` build → HTTP 200 |
| Migration against real Postgres | applies; `alembic check` reports no drift |
| Enum storage | `queued,building,deploying,live,failed,superseded` — values, not names |
| Failed build | old container keeps serving, HTTP 200 throughout, readable `error_message` |
| Concurrent deploys | two requests 4 ms apart → exactly one healthy instance; newest wins, older deployment superseded |
| Rolling deploy | old container drained and removed after traffic shifted |
| `docker kill` a container | reconciled to `stopped` within a tick; route drops to an empty backend → 503 |
| Containers publish no host ports | `3000/tcp`, unmapped; Traefik reaches them over the shared network |

Test suites (SQLite + injected fakes):

```bash
cd control-plane && pytest -q
cd agent && pytest -q
```

The `web/` tree has been type-checked and passes a production Next.js build.

## Phase 2 — private multi-host runtime

Phase 2 runs a control plane on one private GCP VM and node agents on worker
VMs. Nodes heartbeat with capacity and observed containers; the scheduler
chooses a healthy node with sufficient CPU/memory and the lowest allocated
memory ratio. The workspace page shows registered nodes and their instances.

The complete Git-source path has been verified on the lab: Git checkout →
generated Dockerfile → BuildKit → private registry → remote worker pull →
health check → `live` deployment. Stopping an agent marks its node unreachable
and reschedules an eligible stateless service to the surviving node.

This is deliberately a private lab runtime, not production ingress: services
have no public cross-host URL yet. Persistent-volume services are not
automatically duplicated after node loss; see
[ADR 0003](docs/decisions/0003-phase-2-split-brain-policy.md). The production
runtime path is [Phase 3 Kubernetes](docs/phases/PHASE-3-kubernetes-runtime.md).

## Phase 3 — local Kubernetes runtime

Phase 3 uses Kind locally before moving the same resource model to GKE. Rudder
maps an imported Compose graph to a dedicated namespace: stateless apps and
workers become Deployments, stateful dependencies become StatefulSets with
PVCs, private members receive ClusterIP Services, and only an explicitly public
app receives an Ingress route. A candidate route is promoted only after every
member is ready; a failed candidate is removed without changing the existing
public route.

```bash
make kind-up
make kind-control-plane
make verify-kind
```

During local UI development, the first confirmed GitHub import now performs
those first two setup steps automatically: it creates or reuses `rudder-kind`,
switches the local control plane to the Kubernetes runtime, and waits until
`/healthz` reports `runtime: "kubernetes"` before creating the release. Later
imports reuse the existing cluster and do not restart the control plane. Set
`RUDDER_LOCAL_KUBERNETES_AUTO_BOOTSTRAP=false` to use the manual commands
instead.

`make verify-kind` creates a disposable `web + worker + PostgreSQL + Redis`
release, proves ingress reaches only `web`, deliberately fails a new candidate
without disrupting the live route, then removes its temporary namespace.

## Phase 4 — GKE landing zone (planned, not started)

Phase 4 takes the Phase 3 resource contract unchanged onto a private regional GKE
Standard cluster and adds what Kind cannot prove: Artifact Registry immutable
digests, Workload Identity and least-privilege RBAC, one HTTPS edge, durable
backed-up state, observability, and Terraform as the source of truth.

**Kubernetes-only, including in production** — ingress-nginx, cert-manager, and
Postgres under the CloudNativePG operator all run in the cluster. Managed GCP
services are used only where nothing can run in-cluster by nature: the L4 load
balancer, object storage, the registry, and workload identity. Terraform provisions
the cluster once (**attach mode**); Rudder owns namespaces and workloads, never
cluster lifecycle. Public hostnames sit under `rudder.invytt.com`. See
[ADR 0005](docs/decisions/0005-phase-4-kubernetes-only-attach-mode.md).

**WireGuard is cancelled.** The private service network is Kubernetes networking —
Services, CoreDNS, namespaces, and default-deny NetworkPolicies. See
[ADR 0004](docs/decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md).

GCP is the first provider adapter, not the product assumption. Phase 4 writes the
provider contract and its conformance tests so EKS and AKS can follow without
changing deployment records, UI semantics, or the service graph; it creates no AWS
or Azure resources. Effort for those adapters is estimated in
[PHASE-4-gke-production-runtime.md](docs/phases/PHASE-4-gke-production-runtime.md) → "Cost of adding AWS and Azure".

Prerequisites are sorted as of 2026-07-29: `invytt-2483d` audited, all ten APIs
enabled, Terraform 1.15.8 and `gke-gcloud-auth-plugin` installed, and the four
architecture decisions recorded. Phase 4 now waits on item 13 of
[`docs/NEED-FROM-YOU.md`](docs/NEED-FROM-YOU.md) — budget confirmation, GoDaddy NS
records for the `rudder` subdomain, the `rudder-vpc` reuse-or-replace call, and an
acceptance repository. **Do not deploy customer workloads until that file's
acceptance checklist passes.**

## Notes on the dev stack

`buildkitd` runs with `network_mode: service:registry`. That is deliberate:
BuildKit pushes the image and the host Docker daemon pulls it, and both must
resolve the *same* tag string. Sharing the registry's network namespace makes
`localhost:5000` mean the registry inside buildkitd too, so one tag works on
both sides. The control plane therefore reaches buildkitd at `tcp://registry:1234`.

Deployed containers publish no host ports. Traefik reaches them over the shared
`rudder` Docker network — that is what lets two versions of a service run at the
same time during a rolling deploy.
