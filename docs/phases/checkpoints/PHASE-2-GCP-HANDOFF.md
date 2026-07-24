# Phase 2 GCP handoff

**Updated:** 2026-07-24  
**Current branch:** `phase-1`  
**Merged implementation:** PR [#1](https://github.com/sidhxntt/rudder/pull/1), merge commit `979ae25`  
**Status:** Phase 1 plus the GitHub/Compose import extension is merged. GCP
infrastructure for Phase 2 has been created by the operator; Phase 2 scheduler,
node registration, and reconciliation code are not implemented yet.

This document is the context handoff for the next session. It intentionally
contains no passwords, private keys, OAuth secrets, private IP addresses, or
cloud project identifiers.

## Product and architecture snapshot

Rudder is a self-hosted Railway-style PaaS. The user connects GitHub, selects a
repository and branch, and Rudder builds and runs the resulting application.

The current local runtime has these responsibilities:

| Component | Responsibility |
|---|---|
| `web/` | Next.js canvas UI, GitHub login and import wizard |
| `control-plane/` | FastAPI desired state, deployments, routing intent, GitHub OAuth/App integration |
| `agent/` | aiohttp service that owns Docker/Compose operations on one host |
| Postgres | Rudder metadata; not customer application data |
| BuildKit + registry | builds and stores immutable app images |
| Traefik | routes public domains to healthy live services |

The product-level invariant is: **the control plane decides desired state; an
agent only executes idempotent host-local instructions and reports actual
state.** This remains true on GCP and later under Kubernetes.

## What is already implemented and merged

### Phase 1 runtime

- Single-host Docker deployment, health-gated rollout, deployment history,
  build logs, variables, Traefik routing, and old-live-on-failure behaviour.
- Node agent API: health, create/inspect/delete container, health probe, and
  Compose project up/down/status operations.
- Local development stack in `docker-compose.dev.yml`: Postgres, registry,
  BuildKit, Traefik, control plane, and one local agent.
- The dev control plane now runs `alembic upgrade head` before Uvicorn starts.
  This fixes the earlier failure where the import API code was ahead of the
  local database schema.

### GitHub import and Compose extension

- GitHub OAuth sign-in and a GitHub App repository picker.
- Four-step import wizard: source → repository/branch → service review →
  release confirmation.
- Rudder uses a repository `compose.yaml`/`compose.yml` if present. If absent,
  it generates a constrained Compose release from detected Node processes and
  reviewed add-ons.
- Service graph and roles are persisted: web/API, worker, scheduler, realtime,
  database, cache, broker, search, storage, and observability.
- Imported Compose services deploy together as one Compose project. The UI
  displays release lifecycle/build logs for app and managed child services.
- Public URLs are opt-in per eligible service; databases/caches remain private
  by default.
- Starter templates are import presets, not repositories or downloadable source
  files. They only influence generated infrastructure when the selected repo has
  no Compose manifest.

### Current known boundaries

- The repository remains a single-tenant learning build; it is **not** ready to
  execute arbitrary untrusted customer repositories in production.
- Phase 2's registered-node model is not yet implemented. Current agent config
  only knows host-local settings (`RUDDER_AGENT_BIND`, `RUDDER_AGENT_PORT`,
  Compose state directory); it does not register or heartbeat to the control
  plane yet.
- Do not expose Docker port `2375`, Postgres, Redis, or agent port `9000` to
  the public internet.

## Git and workspace state

- Active branch: `phase-1`, up to merge commit `979ae25`.
- PR #1 merged all GitHub OAuth/import, Compose runtime, service catalog, and
  Kubernetes-roadmap documentation.
- Do not add arbitrary untracked files. Local notes and PEM files are expected
  to stay outside Git. In particular, never commit `*.pem`, `.env`, OAuth
  client secrets, GitHub App keys, cloud credentials, or GCP IP inventories.

## GCP infrastructure status

The operator confirmed the initial GCP setup is complete: project
`invytt-2483d`, VPC `rudder-vpc`, subnet `10.42.0.0/20`, region `asia-south1`,
and zone `asia-south1-a`. External VM addresses are deliberately omitted from
Git; retrieve them with `gcloud compute instances list` when needed.

The Phase 2 topology is three Ubuntu 24.04 Compute Engine VMs in one
VPC/subnet:

```text
rudder-control  ── private TCP/8000 ──> rudder-node-a (agent TCP/9000)
       │         └─ private TCP/8000 ──> rudder-node-b (agent TCP/9000)
       └─ UI/API; later: metadata DB, build queue, image registry
```

| VM | Internal IP | Size / disk | State at handoff |
|---|---|---|---|
| `rudder-control` | `10.42.0.2` | `e2-standard-2`, 40 GB | Docker installed |
| `rudder-node-a` | `10.42.0.4` | `e2-standard-2`, 50 GB | Docker installed |
| `rudder-node-b` | `10.42.0.3` | `e2-standard-2`, 50 GB | Docker installed |

Before starting code work, capture the actual resource names, zone, internal
IPs, and firewall rule names in a secure operator-owned location—not in Git:

```bash
gcloud compute instances list
gcloud compute firewall-rules list --filter='network:rudder-vpc'
```

Expected firewall posture:

- **Current lab exception:** `allow-ssh` permits TCP/22 from `0.0.0.0/0` to
  `rudder-admin` hosts. Restrict it to IAP or a known operator source range
  before exposing any real Rudder control-plane functionality.
- SSH should ultimately be available only via IAP or a known operator source
  range.
- Control plane → node agents: TCP `9000`, private VPC only.
- Nodes → control plane: TCP `8000`, private VPC only.
- No public Docker daemon, database, cache, registry, or agent ports.
- Public `80/443` is deferred until multi-host routing is designed; do not open
  it merely to make the current local stack work.

Verify each VM before integration:

```bash
gcloud compute ssh rudder-node-a --zone=YOUR_ZONE --tunnel-through-iap
docker version
curl -fsS http://localhost:9000/healthz
```

At this point, the last command will work only after deploying the agent to the
VM. That deployment mechanism is part of the Phase 2 implementation below.

## Required secrets and configuration

Existing local development uses `.env` values documented in `.env.example`.
For a real deployment, keep them in a secret manager or host-local protected
files, never this repository:

- Rudder database URL, Fernet keys, JWT secret, and seeded admin credentials
- GitHub App ID/slug/private key and webhook secret
- GitHub OAuth client ID/client secret/callback URL
- Agent shared secret (to be introduced in Phase 2)
- Registry credentials and cloud service credentials
- TLS/ACME email and production base domain

GitHub OAuth and GitHub App are different:

- OAuth identifies the person signing into Rudder.
- The GitHub App grants Rudder access to selected repositories and receives
  webhooks.

## Phase 2 objective

**Demo:** two agents register; a service is placed on the lower-loaded node;
one node is lost; an eligible instance is rescheduled to the survivor within
60 seconds. See [Phase 2 — Multi-host](../PHASE-2-multi-host.md).

### Build sequence

1. Add `Node`, heartbeat, and observed-instance persistence to the control
   plane, plus authenticated node registration.
2. Add agent registration at boot and a 5-second heartbeat containing host
   capacity and actual containers/Compose release members.
3. Authenticate all control-plane-to-agent commands with a shared secret.
4. Build the transactional scheduler: healthy nodes only, resource filtering,
   lowest allocated-memory ratio, and `SELECT … FOR UPDATE` capacity locking.
5. Add `Instance` desired-state records and a reconciler that runs every 10
   seconds. It must act on an intent/generation, not stale raw counts.
6. Add unreachable-node handling at 30 seconds and write an ADR for the
   split-brain policy. Stateful workloads must not be blindly duplicated.
7. Package and deploy the agent as a systemd-managed service on both GCP nodes.
8. Add UI/CLI: node list, health/capacity, and instance-to-node mapping.

### Required tests and live proof

- Concurrent placements with capacity for one instance: exactly one succeeds.
- Stale heartbeat reports: reconciler converges without create/stop thrashing.
- Two identical reconciler passes: the second sends zero commands.
- Node A and B register and heartbeat accurately.
- Load Node A; a new service lands on Node B.
- Stop agent or isolate Node A; eligible workload moves to Node B in ≤60s.
- Restore Node A; obsolete containers are stopped and no duplicate live
  instances remain.
- Leave the reconciler idle for 10 minutes; it issues no create/delete calls.

## Production path after Phase 2

The desired production target is Kubernetes, recorded as
[Phase 2.5 — Kubernetes runtime](../PHASE-2.5-kubernetes-runtime.md).

Phase 2 proves Rudder's scheduling, desired-state, reconciliation, and
failure semantics. Phase 2.5 then adds a Kubernetes runtime adapter and maps
the service graph to Deployments, StatefulSets, Services, Ingress/Gateway,
Secrets, namespaces, quotas, and NetworkPolicies. For the Kubernetes track,
that replaces Phase 3's Docker-host/WireGuard networking work; Phase 3 remains
the path for a multi-Docker-host runtime.

## Useful commands for the next session

```bash
# Repository / branch
git switch phase-1
git pull --ff-only

# Local full stack
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps
docker compose -f docker-compose.dev.yml logs --tail=100 control-plane

# Local checks
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:9000/healthz
cd control-plane && uv run pytest tests -q
cd ../agent && uv run pytest tests -q
cd ../web && npm test && npm run typecheck && npm run build

# GCP inventory (read-only)
gcloud compute instances list
gcloud compute firewall-rules list --filter='network:rudder-vpc'
```
