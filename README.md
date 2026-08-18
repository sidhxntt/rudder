# Rudder

Rudder is a self-hosted deployment control plane for turning a Git repository
or Compose-style service graph into running services. It provides a visual,
Railway-style canvas and a terminal CLI, while keeping deployment state,
releases, logs, metrics, domains, and rollback decisions in one control plane.

It is a learning build and controlled GKE beta, designed for a **single
operator/tenant** today. It is not a hosted multi-tenant PaaS. GCP is the
implemented cloud reference; AWS and Azure are documented future mappings.

## What it does

- Import repositories and service graphs from GitHub.
- Build immutable container releases and promote traffic only after health
  checks succeed.
- Run services locally with Docker or through Kubernetes-oriented runtime
  adapters; GKE is the production-reference platform.
- Keep private dependencies private, expose only explicitly public services,
  and support stable service URLs plus deployment-pinned review URLs.
- Create isolated environments and GitHub pull-request preview environments.
- Operate deployments, logs, metrics, rollbacks, domains, variables, and
  service topology from the web canvas or the `rudder` CLI.
- Offer proposal-only AI assistance through Rudder Advisor, build diagnosis,
  and the read-only Ask Rudder experience.

## Architecture at a glance

```text
GitHub / CLI / Web canvas
          |
          v
FastAPI control plane + PostgreSQL
          |
          +-- builds and immutable image registry
          +-- Docker node-agent runtime (local / legacy multi-host)
          `-- Kubernetes runtime (Kind contract / GKE reference)
                   |
                   v
          isolated environment workloads, routes, logs, and metrics
```

The control plane owns desired state. Runtime adapters create the actual
workloads, and reconciliation compares the two. A failed candidate release
does not replace a healthy live release; rollback repoints the stable route to
a healthy immutable release instead of rebuilding it.

## Repository layout

```text
control-plane/  FastAPI, PostgreSQL models, deployments, runtime adapters
agent/          Docker node agent for local and multi-host runtimes
web/            Next.js / React Flow operator canvas
cli/node/       Node.js / TypeScript `rudder` CLI
infra/          Local, Kubernetes, and GCP Terraform/platform assets
docs/           Beginner-friendly architecture, phase, cloud, and stack guides
```

## Local development

Prerequisites: Docker Compose, Python, Node.js, and a local `.env` based on
`.env.example`.

```bash
cp .env.example .env
# Set RUDDER_SECRET_KEYS, RUDDER_JWT_SECRET, and RUDDER_ADMIN_* values.

docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml run --rm control-plane alembic upgrade head
docker compose -f docker-compose.dev.yml restart control-plane
```

Useful local endpoints:

```bash
curl http://localhost:8000/healthz  # control plane
curl http://localhost:9000/healthz  # Docker node agent
```

## Documentation

Read the complete guide in the live [Rudder GitHub Wiki](https://github.com/sidhxntt/rudder/wiki).
The repository [documentation index](docs/index.md) is the source of truth
from which that Wiki is generated. Together, they cover:

- [Overview](docs/overview.md) — problem, concepts, and phased strategy
- [Architecture](docs/architecture.md) — deployment flow and boundaries
- [Features](docs/features.md) — UI, CLI, GitHub, previews, releases, and AI
- [Technology stack](docs/tech-stack.md) — components and rationale
- [Configuration](docs/configuration.md) — local, GitHub, Kubernetes, GKE,
  backup, CLI, and optional AI settings
- [GKE operations](docs/gke-operations.md) — preflight, Terraform, bootstrap,
  verification, capacity gates, and recovery boundaries
- [Multi-cloud mapping](docs/multi-cloud.md) — GCP implementation and
  future AWS/Azure architecture
- [Phase 4 evidence](docs/evidence/phase-4-controlled-beta.md) — dated,
  point-in-time controlled-beta verification and remaining gates
- [Phase 0–9 retrospectives](docs/phases/) — design choices, challenges,
  verification, operations, and cost considerations

To update the published Wiki after changing these documents, use the
[Wiki publishing guide](docs/wiki-publishing.md).

## Scope and status

Rudder has progressed from a single-host Docker deployment path through
multi-host and Kubernetes runtime work, a private GKE landing zone, isolated
environments, operations, frontend releases, AI assistance, and CLI parity.
The detailed documents distinguish what is implemented, what has verification
evidence, and what remains future work. Read those status labels before using
the project as a production platform.

The GKE reference uses one shared regional cluster. A three-zone
`e2-standard-2` node pool requires six vCPUs; the recorded project-wide
`CPUS_ALL_REGIONS` quota was already 12 used of 12, so a dedicated workloads
pool was deliberately not enabled. This is a capacity and cost boundary, not a
claim that Rudder operated six clusters or that hardened multi-tenancy exists.

## Contributing

Keep behavior changes and documentation together. Update the relevant phase
guide and [documentation index](docs/index.md) when changing product behavior,
and do not present planned multi-cloud or multi-tenant work as implemented.
