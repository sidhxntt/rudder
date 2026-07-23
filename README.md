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

One-time host prerequisite — the local registry runs without TLS, so the Docker
daemon must be told to trust it. Docker Desktop → Settings → Docker Engine:

```json
{ "insecure-registries": ["localhost:5000"] }
```

Apply & Restart. Skipping this makes every image pull fail with
`server gave HTTP response to HTTPS client`, which looks unrelated to the real cause.

Then:

```bash
cp .env.example .env
# fill in RUDDER_SECRET_KEYS, RUDDER_JWT_SECRET, RUDDER_ADMIN_*
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
openssl rand -hex 32

docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml exec control-plane alembic upgrade head
```

Check it:

```bash
curl localhost:8000/healthz     # control plane
curl localhost:9000/healthz     # node agent
open http://localhost:8000/docs # OpenAPI
open http://localhost:8080      # Traefik dashboard (dev only)
```

## Status

Phase 1, step 1 (repo scaffold) complete. Steps 2–10 in
[`docs/phases/PHASE-1-single-host.md`](docs/phases/PHASE-1-single-host.md).

Each phase gets a demo section here as it lands.

## Notes on the dev stack

`buildkitd` runs with `network_mode: service:registry`. That is deliberate:
BuildKit pushes the image and the host Docker daemon pulls it, and both must
resolve the *same* tag string. Sharing the registry's network namespace makes
`localhost:5000` mean the registry inside buildkitd too, so one tag works on
both sides. The control plane therefore reaches buildkitd at `tcp://registry:1234`.

Deployed containers publish no host ports. Traefik reaches them over the shared
`rudder` Docker network — that is what lets two versions of a service run at the
same time during a rolling deploy.
