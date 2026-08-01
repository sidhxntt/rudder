# Phase 1 — Single-host deploy

**Target:** 3–4 weeks (+1 day for D15)

**Demo:** push to GitHub, a container comes up, a public URL serves it.

Everything runs on one machine. No scheduler, no private service network, no
multi-node anything.
The point of this phase is a working end-to-end pipeline, not a distributed
system.

---

## Prerequisites

From `../NEED-FROM-YOU.md`:

- [ ] D1–D6 and D15 resolved
- [ ] Repo root confirmed, project name decided
- [ ] `GITHUB_TOKEN` in `.env` (or confirmation that all repos are public)
- [ ] `localhost:5000` added to Docker daemon `insecure-registries`
- [ ] ngrok or cloudflared installed
- [ ] Two test repos identified (one Node, one Python)
- [ ] Domain strategy chosen (`dev` is fine)

---

## Steps

### 1. Repo scaffold

Monorepo. Layout is in `../PRD.md` → "What and How — Phase 1" → "Repo structure".

`docker-compose.dev.yml` brings up:

| Service | Image | Notes |
|---|---|---|
| postgres | `postgres:16` | control plane DB |
| registry | `registry:2` | insecure, port 5000 |
| traefik | `traefik:v3` | file provider watching a mounted dir |
| buildkitd | `moby/buildkit:rootless` | D7, TCP listener |

All on one Docker network. Traefik must be on the same network as deployed
containers or it cannot reach them.

Deployed containers **publish no host ports.** Traefik reaches them on the shared
Docker network. This matters — it's what makes two versions of a service able to
run simultaneously during a rolling deploy.

### 2. Data model + migrations

Alembic. Every table in `../PRD.md` → "Data Model", including `Node` (unused this
phase) and `Domain` (D15).

Schema deltas from that section are listed in the PRD under "Schema deltas".
Do not skip the `Domain` CHECK constraint.

### 3. Auth

Single user, seeded from `.env` on first boot. JWT. **Do not build signup.**

Decide and record: token in an httpOnly cookie or an `Authorization` header. The
CLI and SDK want a header; the browser wants a cookie. Supporting both is fine,
supporting neither well is not.

### 4. CRUD API

Projects, environments, services, variables, domains. OpenAPI docs at `/docs`.

Follow the API design rules in `../PRD.md` → "Interfaces". Resource-oriented,
idempotent `PUT`, full resource in every mutation response, uniform errors.

`Variable` responses **never** include the decrypted value. Write-only field.

Name validation per D9: `^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$` on service and
environment names, because they become hostnames.

### 5. Build pipeline

- GitHub webhook endpoint, HMAC signature verification against the webhook secret
- Clone to a temp dir at the pushed SHA, using `GITHUB_TOKEN` (D2)
- **Language detection, heuristics only, no LLM:**
  - `Dockerfile` present → use it directly, skip generation
  - `package.json` → Node
  - `requirements.txt` / `pyproject.toml` → Python
  - `go.mod` → Go
- Generate a Dockerfile from a Jinja2 template if none exists. Templates live in
  `control-plane/dockerfile_templates/` and are checked in.
- `buildctl` build → push to the local registry, tag `{service_id}:{sha}`
- Stream build logs to a file, expose via an SSE endpoint

Build runs in a background worker started in the FastAPI lifespan, not in the
request. `POST /services/{id}/deploy` creates `Deployment(status=queued)` and
returns 202.

### 6. Deploy

Docker API — the `docker` SDK, not `subprocess.run(["docker", ...])`.

Create container with resolved env vars injected, CPU and memory limits applied,
then start.

**Depends on D3.** If (b), this happens over HTTP to a locally-running agent from
day one. If (a), it's a direct Docker API call isolated in
`services/runtime.py` with a surface shaped like the future agent API.

### 7. Health check + traffic shift

Poll `health_check_path` on `health_check_port` (defaults to `container_port`,
D1) until 200.

Parameters per D12: 60s timeout, 2s interval, 1 consecutive success, 5s start
grace period.

- **Success:** write Traefik config, mark Instance healthy, drain the old
  Instance 10s then stop it (D10)
- **Failure:** mark Deployment failed with `error_message`, leave the old
  Instance serving, stop and remove the new container

The old instance keeps serving throughout. A failed deploy is a no-op from the
user's perspective.

### 8. Traefik routing — D15

Control plane writes `dynamic/{domain_id}.yml`. Traefik's file provider watches
the directory.

**One router per `Domain` row, not per Service.**

On service create, auto-insert a system Domain:
- hostname `{service}.{env}.{base_domain}`
- `target_type=service`
- `is_system=true`

Phase 1 only ever creates system domains. But `traefik.py` reads from the Domain
table from day one — see the `render_all` sketch in `../PRD.md` → "Schema
deltas".

Regenerate on: deploy success, domain create/delete, instance state change.
Whole-directory rewrite, idempotent.

TLS per D8: `RUDDER_TLS_MODE=off` in dev, hostnames `{service}.{env}.localhost`.

### 9. Python SDK + CLI

Generate the SDK from the OpenAPI schema. CLI is a thin wrapper over it.

The acceptance test is in `../PRD.md` → "Goal": the full create-deploy-logs cycle
with no browser open. If any step needs the UI, step 4 is incomplete — fix the
API, don't work around it in the CLI.

### 10. Canvas UI

React Flow. Service nodes showing name, status, URL. Drag to reposition, persist
`canvas_x/y` (D6 — UI metadata only).

Click a node → detail panel with build logs (D4 — build logs only this phase),
variables, deploy history. Deploy button.

Design per D5.

---

## Where this goes wrong

Reason about these before writing. Say so explicitly when you touch them.

**Concurrent deploys (D11).** Two pushes 2s apart. Without a lock you get two
builds racing to write Traefik config and two containers both claiming to be
live. Postgres advisory lock keyed on `service_id` around the deploy path. When a
Deployment reaches `deploying`, mark every older non-terminal Deployment for that
service `superseded` and drain its instances.

**Health check racing the traffic shift.** Container reports 200, then dies
before Traefik config is written. Re-check liveness immediately before the shift,
not just before the decision.

**Build log SSE and connection lifecycle.** Client disconnects mid-build; the
build must not stop. Logs go to a file, SSE tails the file. Never hold the build
open on a client connection.

**Registry push failures look like unrelated TLS errors.** If a pull fails with
`server gave HTTP response to HTTPS client`, the `insecure-registries` step was
missed. Check that first, not last.

**Temp dir cleanup.** Clones accumulate. Clean up on both success and failure
paths, including exceptions.

---

## Verify

Not "it compiled." Run these.

```bash
# 1. Cold start, no manual steps beyond .env
docker compose -f docker-compose.dev.yml up -d
alembic upgrade head

# 2. Full cycle, no browser
rudder project create shop
rudder service create api --repo <node-repo> --port 3000
rudder deploy api --follow
curl -H "Host: api.production.localhost" http://localhost

# 3. Same for Python
rudder service create pyapi --repo <python-repo> --port 8000
rudder deploy pyapi --follow

# 4. Kill a container manually, confirm the UI reflects it
docker ps
docker kill <container_id>
# → canvas shows the service as unhealthy

# 5. Failed deploy does not take down the live service
#    push a commit that fails to build
#    → old container still serving, Deployment marked failed with a reason

# 6. Concurrent deploys
#    trigger two deploys ~1s apart
#    → exactly one live Instance, older Deployment marked superseded
```

Automated: `pytest`, including at least one concurrency test on the deploy path
(D14).

---

## Done when

- [ ] `docker compose up` + `alembic upgrade head` is the entire setup
- [ ] A Node repo and a Python repo both deploy from a real `git push`
- [ ] The full CLI cycle works with no browser open
- [ ] Killing a container is reflected in the UI
- [ ] A failed build leaves the previous version serving
- [ ] Concurrent deploys produce exactly one live instance
- [ ] Traefik config is generated from `Domain` rows
- [ ] `pytest` green, deploy-path concurrency test included
- [ ] `README.md` has a Phase 1 demo section
- [ ] At least one ADR in `../decisions/`
