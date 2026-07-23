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

**Phase 1 works end to end on real infrastructure.** A push-to-URL deploy was
run against live Postgres, BuildKit, a local registry, Docker, and Traefik on
2026-07-23. Steps 9 (SDK + CLI) and 10 (canvas UI, written but never compiled)
remain. See [`docs/phases/PHASE-1-single-host.md`](docs/phases/PHASE-1-single-host.md).

Verified on the live stack, not with fakes:

| Check | Result |
|---|---|
| Node repo deploys and serves | `api.production.localhost` → HTTP 200 |
| Python repo deploys and serves | `pyapi.production.localhost` → HTTP 200 |
| Migration against real Postgres | applies; `alembic check` reports no drift |
| Enum storage | `queued,building,deploying,live,failed,superseded` — values, not names |
| Failed build | old container keeps serving, HTTP 200 throughout, readable `error_message` |
| Two deploys 1s apart | exactly one `live` deployment, newest wins, loser superseded |
| Rolling deploy | old container drained and removed after traffic shifted |
| `docker kill` a container | reconciled to `stopped` within a tick; route drops to an empty backend → 503 |
| Containers publish no host ports | `3000/tcp`, unmapped; Traefik reaches them over the shared network |

Test suites (SQLite + injected fakes):

```bash
cd control-plane && pytest -q     # 227
cd agent && pytest -q             #  50
```

Not verified: the `web/` tree has never been compiled — `npm` is blocked in this
environment, so its dependencies were never installed.

## Notes on the dev stack

`buildkitd` runs with `network_mode: service:registry`. That is deliberate:
BuildKit pushes the image and the host Docker daemon pulls it, and both must
resolve the *same* tag string. Sharing the registry's network namespace makes
`localhost:5000` mean the registry inside buildkitd too, so one tag works on
both sides. The control plane therefore reaches buildkitd at `tcp://registry:1234`.

Deployed containers publish no host ports. Traefik reaches them over the shared
`rudder` Docker network — that is what lets two versions of a service run at the
same time during a rolling deploy.
