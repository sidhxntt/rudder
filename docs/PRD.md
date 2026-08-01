# Rudder — Self-Hosted PaaS

A Railway-style PaaS with a canvas UI. Multi-host container scheduling, a private
Kubernetes service network, environment cloning, and git-push deploys.

**This is a learning build.** Single-tenant by design. Not multi-tenant, not
production-hardened for untrusted workloads. See "Explicit Non-Goals".

---

## Documents

| File | What it is |
|---|---|
| `PRD.md` (this file) | Source of truth. Goal, architecture, data model, interfaces, decisions, non-goals. |
| [`NEED-FROM-YOU.md`](NEED-FROM-YOU.md) | Everything blocking or gating work that only you can provide — decisions, credentials, hardware, accounts. Read this first. |
| [`phases/`](phases/) | One file per phase. Build instructions: steps, failure modes, verify commands, done checklist. |
| [`DESIGN-supabase.md`](DESIGN-supabase.md) | UI design tokens. See D5 — adopt the scales, not the white-canvas mandate. |
| `decisions/` | ADRs. One per phase minimum, per the Definition of Done. |

When a phase file and this document disagree, **this document wins** and the
phase file is a bug.

---

## Goal

Point Rudder at a git repo — FastAPI, Express, Go, anything — and it builds, runs,
and serves that app on a public URL. Operate it from a canvas UI, a CLI, or an
SDK. On your own hardware.

**The end-to-end flow, stated once:**

```
git push
  → GitHub webhook (HMAC verified)
  → clone at pushed SHA
  → detect language (package.json / requirements.txt / go.mod / Dockerfile)
  → generate Dockerfile if absent
  → BuildKit build → push to local registry
  → create container: resolved env vars, CPU/memory limits
  → poll health check until 200 or timeout
  → on success: write Traefik config, URL goes live, drain old container
  → on failure: mark Deployment failed, old container keeps serving
```

Same flow for every language. Only the Dockerfile template differs.

Add a Postgres as a one-click service and `DATABASE_URL` wires into the app
automatically over the private service network. The database never gets a public
port.

**Success = this works with no browser open:**

```bash
rudder project create shop
rudder service create api --repo me/shop-api --port 8080
rudder var set DATABASE_URL='${{postgres.DATABASE_URL}}'
rudder deploy api --follow
rudder logs api -f
```

If any step requires the UI, the API is incomplete. See "Interfaces".

**Scope: backends are primary, frontends are supported.** The moat is container
orchestration — multi-host scheduling, a private service network, stateful services,
environment cloning. Frontends ride the same pipeline (see "Phase 5.5") because a
static build is just an artifact wrapped in nginx and run as a container, and an
SSR app is already just a long-running container. That costs one new
`Service.kind`, not a second execution model. Deploy your API, your worker, your
Postgres, and your Next.js frontend to the same place.

**What this is not:** Railway's deploy experience, not Railway's business. No
signup, no teams, no billing, no autoscaling, no multi-region. Not a serverless
platform — no per-request function invocation, no edge, no ISR. See "Explicit
Non-Goals".

---

## Working Agreement

Read this section before doing anything else.

1. **Do not write code until we agree on the plan.** For each task, propose the
   approach first — files touched, data model changes, interfaces. Wait for
   confirmation.
2. **Small diffs.** One concern per change. If a change touches more than ~4
   files, stop and propose splitting it.
3. **No speculative abstraction.** Build the concrete thing. Do not add plugin
   systems, generic drivers, or config layers "for later." We will refactor when
   the second case actually appears.
4. **Ask when the spec is ambiguous.** Do not invent product decisions. If this
   document doesn't say, ask.
5. **Every phase must end demoable.** No phase leaves the system in a state
   where nothing runs.
6. **Flag risk explicitly.** When touching the scheduler, runtime networking, or
   anything concurrent, say so and explain the failure modes you considered.

### Where you are likely to be wrong

Be extra careful in these areas. Reason out loud before writing.

- **Scheduler concurrency.** Two deploys racing, stale node capacity, a health
  check racing a traffic shift. Code that looks correct here is often wrong
  under load. Write tests that actually exercise concurrency.
- **Private networking lifecycle.** NetworkPolicy ordering (default-deny must
  exist before workloads), DNS resolution inside a namespace, and route promotion
  on a candidate revision. Failures are silent — traffic just doesn't arrive, and
  a too-permissive policy looks identical to a correct one from inside the Pod.
- **Container lifecycle races.** Container reports healthy, then dies during
  traffic shift. Old container drains while new one crashes.
- **State reconciliation.** DB says a service is running; the node disagrees.
  Reconciliation must be idempotent and must not thrash.

Do not tell me something works because it compiles. If you have not verified
behavior, say so.

---

## Stack

Fixed. Do not substitute.

| Layer | Choice |
|---|---|
| Control plane API | Python 3.12, FastAPI, SQLModel |
| Control plane DB | Postgres 16 |
| Node agent | Python 3.12, aiohttp, docker SDK |
| Container runtime | Docker via API (not shell-outs) |
| Image build | BuildKit (`buildctl`) |
| Registry | `registry:2`, local |
| Proxy | Traefik v3, file provider, dynamic config |
| TLS | Traefik ACME (Let's Encrypt), HTTP-01 |
| Private service network | Kubernetes Services + CoreDNS + NetworkPolicy (Phase 3 on Kind, Phase 4 on GKE) |
| Production runtime | GKE Standard, regional, VPC-native, private nodes — attach mode, Terraform-provisioned |
| Production registry | Artifact Registry, immutable digests |
| Production ingress | ingress-nginx (one controller) |
| Production TLS | cert-manager + Let's Encrypt |
| Production Postgres | CloudNativePG operator, in-cluster, WAL archived to object storage |
| Infrastructure-as-code | Terraform, remote state in GCS |
| Frontend | Next.js 15 App Router, TypeScript |
| Canvas | React Flow |
| Styling | Tailwind |
| State | TanStack Query |
| Tests | pytest, pytest-asyncio |

**Python style:** type hints everywhere, `async def` for anything doing I/O,
Pydantic for all boundary types, no bare `except`.

**TS style:** strict mode, no `any`, colocate components with routes.

---

## Architecture

```
                        ┌──────────────┐
                        │  Next.js UI  │
                        │  (canvas)    │
                        └──────┬───────┘
                               │ REST
                        ┌──────▼───────┐
                        │ Control Plane│──── Postgres
                        │   (FastAPI)  │
                        └──────┬───────┘
                               │ HTTP (agent API)
              ┌────────────────┼────────────────┐
              │                │                │
        ┌─────▼─────┐    ┌─────▼─────┐   ┌─────▼─────┐
        │ Node Agent│    │ Node Agent│   │ Node Agent│
        │  Docker   │    │  Docker   │   │  Docker   │
        └───────────┘    └───────────┘   └───────────┘
              └────── shared Docker network ─────┘

        Traefik sits on an edge node, file-provider config
        written by the control plane.
```

That is the Phase 1–2 lab runtime. The production runtime is Kubernetes, and the
control plane reaches it through a runtime adapter rather than an agent API:

```
                        ┌──────────────┐
                        │ Control Plane│──── Postgres
                        └──────┬───────┘
                               │ Kubernetes API (runtime adapter)
                        ┌──────▼──────────────────────────┐
                        │ Kind (local) / GKE (production) │
                        │                                 │
                        │  rudder-system namespace        │
                        │  rudder-<environment-id> ns     │
                        │    app Deployment ── Ingress ───┼── public HTTPS
                        │    worker Deployment            │
                        │    postgres/redis StatefulSet   │
                        │    PVCs, Secrets, NetworkPolicy │
                        └─────────────────────────────────┘

        Private traffic resolves by Kubernetes service DNS
        (postgres.rudder-<environment-id>.svc.cluster.local).
        Default-deny NetworkPolicy isolates every environment.
```

**Control plane owns desired state. Nodes own actual state. A reconciler closes
the gap.** This is the core invariant — do not let nodes make placement
decisions, and do not let the control plane assume its view is current.

---

## Interfaces

Three clients, one API. The canvas is a peer of the CLI, not a layer above it.

```
Canvas UI          CLI          SDK (Python / TS)
     └─────────────┬─────────────┘
                   │ REST
            Control Plane API
                   │
              Reconciler
                   │
                 Agents
```

**The discipline:** every UI action is an API call. No backdoors, no
endpoint that exists only to serve a UI quirk. Build the endpoint first, then
make the UI consume it. If the CLI cannot do something the UI can, that is a bug.

**API design rules** — cost nothing now, keep the declarative layer open later:

- Resource-oriented, not RPC. `PATCH /services/{id}`, never `POST /rename-service`.
- `PUT` is idempotent. Same body twice, same result.
- Every mutation returns the full resource so clients can cache.
- Errors are uniform: `{code, message, details}`.

**Build order:**

| Layer | Phase | Notes |
|---|---|---|
| REST API | 1 | The substrate. Everything else is a client. |
| Python SDK | 1 (tail) | Generated from OpenAPI. ~2 days. |
| CLI | 1 (tail) | Thin wrapper over the SDK. ~2 days. |
| TS SDK | with `web/` | Free — `web/` needs a typed client regardless. |
| Canvas UI | 1 | Consumes the TS SDK. |

**Deferred, not rejected:** a declarative `rudder apply` (infra defined in code,
diffed against live state) is a natural fit because the Phase 2 reconciler is
already the engine such a tool needs. If built, it replaces most of Phase 4 —
environment cloning becomes `RUDDER_ENV=staging rudder apply`, and typed object
references remove the `${{Service.VAR}}` string parser. Do not build it before
Phase 4. See Decision D6 for the one thing that must not be painted into a
corner.

---

## Data Model

Build this first. Everything else depends on it.

```
User
  id, email, password_hash, created_at

Project
  id, name, owner_id → User

Environment
  id, project_id → Project, name, is_production
  wg_subnet                     -- DEPRECATED, see ADR 0004. Isolation is the
                                -- environment namespace plus its default-deny
                                -- NetworkPolicy. Phase 4 removes the allocator
                                -- that still populates this; the column then
                                -- stays null.
  unique(project_id, name)

Service
  id, environment_id → Environment, name, kind
  kind ∈ {app, database, static}
  -- static: build output wrapped in nginx. Still a container. See Phase 5.5.
  source_repo, source_branch, dockerfile_path, build_config (JSON)
  start_command, health_check_path, health_check_port
  cpu_limit, memory_limit_mb, replica_count
  canvas_x, canvas_y            -- UI position, control plane stores it
  unique(environment_id, name)

Variable
  id, service_id → Service, key, value_encrypted, is_reference
  -- is_reference: value is "${{Postgres.DATABASE_URL}}", resolved at deploy
  unique(service_id, key)

Volume
  id, service_id → Service, mount_path, size_mb, node_id → Node
  -- volume pins a service to a node. enforce this in the scheduler.

Node
  -- Docker runtime only. The Kubernetes runtime has no Node rows: the cluster
  -- schedules Pods. See ADR 0004.
  id, hostname, ip_address, wg_public_key, wg_ip     -- wg_* DEPRECATED, null
  cpu_total, memory_total_mb, cpu_allocated, memory_allocated_mb
  status ∈ {healthy, unreachable, draining}
  last_heartbeat_at

Deployment
  id, service_id → Service, image_tag, commit_sha
  status ∈ {queued, building, deploying, live, failed, superseded}
  build_log_url, created_at, became_live_at
  -- image_tag is never reused or deleted. A Deployment is an immutable
  -- artifact; a Domain can point at any past one. This is what makes
  -- rollback instant.

Instance
  id, deployment_id → Deployment, node_id → Node
  container_id, status ∈ {starting, healthy, unhealthy, draining, stopped}
  wg_ip, started_at             -- wg_ip DEPRECATED, null. See ADR 0004.

Domain
  id, hostname (unique), environment_id → Environment
  target_type ∈ {service, deployment}
  service_id → Service          -- set when target_type=service
  deployment_id → Deployment    -- set when target_type=deployment
  is_system                     -- true for auto-generated {service}.{env}.{domain}
  tls_enabled
  -- exactly one of service_id / deployment_id is non-null. Enforce with a
  -- CHECK constraint, not application code.
```

**Notes:**
- `Instance` is the running-container record. `Deployment` is the intent.
  Rolling deploy = old Instances draining while new Instances start, both
  pointing at different Deployments of the same Service.
- Variable values encrypted at rest with a key from env. Use `cryptography`
  Fernet. Do not roll your own.
- **Environment isolation is a Kubernetes namespace with a default-deny
  NetworkPolicy**, not a `wg_subnet`. The `wg_*` columns are deprecated, kept only
  to avoid a migration on a pre-production schema. `Node.wg_*` and `Instance.wg_ip`
  are already always null. `Environment.wg_subnet` is still allocated on create by
  leftover Phase 1 code and still appears in `EnvironmentRead`; Phase 4 removes
  that allocator, and the column then stays null too. Do not build on it. See
  ADR 0004.
- `Domain` is the routing unit. **Traefik config is generated from Domains, never
  from Services.** Two targeting modes:
  - `target_type=service` — Railway semantics. Routes to whatever Deployment is
    currently live. The hostname follows the service.
  - `target_type=deployment` — Vercel semantics. Pinned to one immutable build
    forever. Rollback is an UPDATE on a Domain row, not a rebuild.

  See D15. This is in Phase 1 even though most of what it enables is Phase 5.5.

---

## Phases

Each phase has its own file in [`phases/`](phases/). Those files are the build
instructions — steps, failure modes, verification commands, and a done checklist.
This document stays the source of truth for goal, architecture, data model,
interfaces, decisions, and non-goals. If a phase file contradicts this document,
this document wins.

| Phase | File | Target | Demo |
|---|---|---|---|
| 1 | [Single-host deploy](phases/PHASE-1-single-host.md) | 3-4 wk | Push to GitHub, container comes up, public URL serves it |
| 2 | [Multi-host](phases/PHASE-2-multi-host.md) | 3-4 wk | Two nodes, service lands on the less loaded one, node dies, service reschedules |
| 3 | [Kubernetes runtime](phases/PHASE-3-kubernetes-runtime.md) | 3-5 wk | Imported Compose app deploys in an isolated namespace; failed revisions roll back |
| 4 | [GKE landing zone](phases/PHASE-4-mesh.md) | 3-5 wk | The Phase 3 namespace model runs on a private regional GKE cluster; only the app is publicly routed |
| 5 | [Environments](phases/PHASE-5-environments.md) | 2 wk | Clone production to staging, everything rewires |
| 6 | [Operations](phases/PHASE-6-operations.md) | 2-3 wk | Volumes, DB templates, logs, metrics, instant rollback |
| 6.5 | [Frontends](phases/PHASE-6.5-frontends.md) | 1 wk | Vite SPA + Next.js deploy, every push gets a permanent URL |
| 7 | [Deploy advisor](phases/PHASE-7-advisor.md) | 1-2 wk | Point at a repo, get a proposed service graph as ghost nodes |

Total: 18-26 weeks on the Kubernetes production track.

**Production runtime track.** Phase 3 follows the verified Phase 2 control-plane
semantics and introduces Kubernetes as a runtime adapter, proven locally on Kind.
Phase 4 carries that identical resource contract to GKE and adds what Kind cannot
prove: private cluster networking, Artifact Registry digests, Workload Identity,
a single managed HTTPS edge, durable managed state, and infrastructure-as-code.

**WireGuard is cancelled.** Kubernetes Services, CoreDNS, namespaces, and
NetworkPolicies are the private service network — Rudder allocates no mesh IPs,
manages no peers, and writes no host-level DNS. `phases/PHASE-4-mesh.md` keeps its
filename to preserve links only. See
[ADR 0004](decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md).

**Multi-cloud.** GCP is the first provider adapter, not the product assumption.
Phase 4 writes the provider contract and its acceptance tests so EKS and AKS can
satisfy the same behaviour later without changing deployment records, UI
semantics, or the service graph. It creates no AWS or Azure resources. Scope and
effort for those adapters: `phases/PHASE-4-mesh.md` → "Cost of adding AWS and
Azure".

**Do not start a phase until the previous one is verified working end to end.**
Each phase is demoable. "It compiles" and "the happy path worked once" are not
verification -- every phase file has a `## Verify` section with actual commands.

**Reordering.** Phase 5 is the easiest phase after 1, has high payoff, and does
not need multi-host -- it can move earlier freely. Phase 6.5 depends only on D15
landing in Phase 1 and can also move earlier if frontends become urgent. Phase 4
cannot move earlier: it depends on a verified Phase 3 Kubernetes resource
contract.


## Explicit Non-Goals

Do not build these. If you think one is needed, ask first.

- Multi-tenancy or untrusted workload isolation
- Autoscaling
- Global edge / multi-region
- HA control plane
- Billing or metering
- Signup, teams, RBAC
- Custom buildpack plugin system
- A second container runtime
- Natural-language-to-SQL, chat interfaces, or agent frameworks
- **Serverless functions.** Per-request invocation is a second execution model:
  cold starts, function-level routing, concurrency limits, and a reconciler that
  no longer assumes long-lived instances. ~6 weeks and it fights the core
  architecture. If you want Next.js API routes, run the app as a normal
  container — that is 90% of the value for none of the machinery.
- **Edge runtime, CDN, ISR / on-demand revalidation.** Follows from the above,
  and from "global edge" already being on this list.
- **Image optimization as a platform service.** Let the framework do it in-process.

---

## Definition of Done (per phase)

- Runs from `docker-compose.dev.yml` with no manual steps beyond documented env
- Tests pass, including at least one concurrency test for anything in the
  scheduler
- README section updated with what this phase added and how to demo it
- One architecture decision written up in `docs/decisions/` — what you chose,
  what you rejected, why

---

## Open Decisions

**All resolved 2026-07-23 — every proposal below accepted as written.** See
[`decisions/0001-phase-1-decisions.md`](decisions/0001-phase-1-decisions.md).
D7–D14 stand as silent defaults. The reasoning below is kept as the record of why.

| # | Decision | Resolution | Status |
|---|---|---|---|
| D1 | Service needs an app port distinct from `health_check_port` | Add `container_port: int = 8080` | accepted |
| D2 | How the control plane authenticates to GitHub for clone | Single `GITHUB_TOKEN` in env for Phase 1; no per-repo model | accepted |
| D3 | Build the node agent in Phase 1 or Phase 2 | (b) Build in Phase 1, running on localhost | accepted |
| D4 | Scope of "logs" in Phase 1 UI | Build logs only; runtime logs are Phase 5 | accepted |
| D5 | Design system for `web/` | Take DESIGN-supabase.md token scales, invert surfaces to dark | accepted |
| D6 | Who owns truth — DB or code | DB owns truth; `canvas_x/y` is UI-only metadata no declarative layer manages | accepted |
| D15 | Routing keyed on Service, or on a first-class Domain | Add `Domain` in Phase 1; generate Traefik config from Domains | accepted |

### D1 — Missing app port

`Service` has `health_check_port` but nothing telling Traefik which port to route
to. They are not always the same. Proposal: add `container_port`, and default
`health_check_port` to it when null.

### D2 — GitHub authentication is absent from the data model

`source_repo` is a bare string. Private repos need a token to clone. Either a
single env-level PAT (Phase 1 default) or a `GitHubInstallation` table now.

### D3 — The agent timing tradeoff

The phase plan has the control plane driving Docker directly in Phase 1, then
introduces the agent in Phase 2. That rewrites the entire deploy path and every
test around it.

- **(a) Follow the plan.** Isolate all container operations in
  `services/runtime.py` with a surface shaped like the future agent API. Phase 2
  moves that file into `agent/` and swaps the caller to HTTP.
- **(b) Build the agent in Phase 1**, running on localhost, control plane talks
  to it over HTTP from day one. Costs ~4 days now, saves ~1 week in Phase 2.

Recommendation: (b). It is not speculative abstraction — it is building the real
component earlier. (a) risks becoming exactly the "interface for later" this
document bans.

### D4 — Phase 1 logs contradiction

Phase 1 step 5 streams *build* logs. Phase 1 step 9 says the detail panel shows
"logs". Container runtime logs are Phase 5. Assuming build logs only in Phase 1.

### D5 — `DESIGN-supabase.md` is the wrong shape as written

It specifies a white-canvas marketing skin with an emerald CTA and a
"white-canvas commitment is non-negotiable" rule. Rudder is a dark, dense operator
console with a React Flow canvas. The token scales (radii, spacing, type scale,
grey ladder) transfer cleanly. The white-canvas mandate does not.

Proposal: adopt the token scales, invert app-shell surfaces to `canvas-night`,
keep emerald as the single accent.

### D6 — Truth ownership

Only matters for `canvas_x/canvas_y`, which is in the Phase 1 schema.

- DB owns truth → keep the fields, drag persists, a future declarative layer must
  reconcile against UI edits.
- Code owns truth → drop the fields, canvas auto-layouts and is read-only.

Recommendation: keep `canvas_x/y`, but treat layout as UI metadata that no
declarative layer ever manages. Code owns structure, DB owns layout. Nothing to
unwind later.

### D15 — Routing must key on Domain, not Service

Phase 1 as originally written hardcodes one Traefik router per Service at
`{service}.{env}.{domain}`. That assumption gets baked into `traefik.py` on day
one and is expensive to unwind, because everything downstream — previews,
immutable deployment URLs, custom domains, instant rollback — needs *many*
hostnames pointing at *different* Deployments at the same time:

```
abc123-shop.rudder.dev     → Deployment abc123   immutable, permanent
feat-auth.shop.rudder.dev  → Deployment def456   branch alias, moves on push
shop.com                 → Deployment abc123   production alias, moves on promote
```

Proposal: add the `Domain` table in Phase 1 and generate Traefik config from it.
Phase 1 still only ever creates one system Domain per service, so behavior is
identical — but the routing code reads the right table from the start.

**Cost:** ~1 day. **Buys immediately:** instant rollback in Phase 5 becomes an
UPDATE instead of a rebuild-and-restart, which is strictly better on its own
terms. **Buys later:** all of Phase 5.5, with no routing rewrite.

Take this even if Phase 5.5 is never built.

### Resolved by default unless objected to

- **D7 Buildkitd placement.** `moby/buildkit:rootless` in
  `docker-compose.dev.yml`; control plane talks to it over TCP. The local
  registry must appear in the host Docker daemon's `insecure-registries` — a
  documented one-time host prerequisite, and the one exception to
  "no manual steps".
- **D8 TLS in dev.** ACME HTTP-01 cannot work on localhost. Add
  `RUDDER_TLS_MODE=off|acme`. Dev uses `{service}.{env}.localhost`, no TLS.
- **D9 Name validation.** Service and environment names become hostnames.
  Enforce `^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$` at the API boundary.
- **D10 Drain policy.** After traffic shifts to a healthy new instance, the old
  container drains 10s, then stops. No connection tracking in Phase 1.
- **D11 Concurrent deploys.** Postgres advisory lock keyed on `service_id` around
  the deploy path. When a Deployment reaches `deploying`, every older
  non-terminal Deployment for that service becomes `superseded` and its
  instances drain.
- **D12 Health check parameters.** The spec gives only a 60s timeout. Adding:
  2s interval, 1 consecutive success required, 5s start grace period.
- **D13 Secret key rotation.** `MultiFernet` over `RUDDER_SECRET_KEYS`
  (comma-separated, first key encrypts). Costs nothing now, avoids a data
  migration later.
- **D14 Phase 1 concurrency test.** The DoD requires a concurrency test "for
  anything in the scheduler", but no scheduler exists until Phase 2. In Phase 1
  that test targets the deploy path (D11).

---

## What and How — Phase 1

### Repo structure

```
rudder/
├── docker-compose.dev.yml        # postgres, registry, traefik, buildkitd
├── .env.example
├── README.md
├── docs/decisions/
├── control-plane/
│   ├── pyproject.toml
│   ├── Dockerfile
│   ├── alembic.ini
│   ├── migrations/
│   ├── dockerfile_templates/     # node / python / go, Jinja2
│   ├── rudder_cp/
│   │   ├── main.py               # app factory, router mount, lifespan
│   │   ├── config.py             # pydantic-settings
│   │   ├── db.py                 # engine, session dependency
│   │   ├── security.py           # JWT, password hash, Fernet
│   │   ├── models/               # SQLModel tables
│   │   ├── schemas/              # request/response types, NOT the tables
│   │   ├── routers/              # auth, projects, environments, services,
│   │   │                         #   variables, deployments, webhooks
│   │   ├── services/             # domain logic, no FastAPI imports
│   │   │   ├── deploy.py         # build → run → healthcheck → route
│   │   │   ├── builder.py        # detect, render, buildctl, push
│   │   │   ├── detect.py         # language heuristics
│   │   │   ├── runtime.py        # Docker API surface (see D3)
│   │   │   ├── health.py         # poll loop
│   │   │   ├── traefik.py        # render dynamic/{service}.yml
│   │   │   └── variables.py      # encrypt / decrypt / resolve
│   │   └── logs/                 # build log file store + SSE
│   └── tests/
├── agent/                        # scaffold only unless D3 = (b)
├── sdk-python/                   # generated from OpenAPI
├── cli/                          # thin wrapper over sdk-python
└── web/
    ├── app/                      # Next 15 App Router
    ├── components/
    ├── lib/api.ts                # generated TS client
    └── styles/tokens.css
```

### FastAPI layout

Three layers, one direction of dependency:

```
routers/  →  services/  →  models/
```

- **routers** — parse, authorize, call one service function, serialize. No
  business logic.
- **services** — all logic. Takes `Session` as an argument, never imports
  `fastapi`. Tests hit this layer directly.
- **models** — SQLModel tables only. No methods that perform I/O.
- **schemas** — separate from tables. Tables carry `value_encrypted`; the API
  must never return it.

**Long work never runs in the request.** `POST /services/{id}/deploy` creates a
`Deployment(status=queued)` and returns 202. A background worker started in the
FastAPI lifespan polls the queue. No Celery.

### Schema deltas from the Data Model section

- `Service.container_port: int = 8080` — D1
- `Service.kind` gains `static` — Phase 5.5, no rows use it in Phase 1
- `Deployment.error_message: str | None` — failures need a readable reason
- `Instance.stopped_at: datetime | None` — drain audit trail
- **`Domain` table** — D15. New table, wired into `traefik.py` from Phase 1.

Everything else matches the Data Model section as written. All Phase 1 tables use
UUID primary keys and timezone-aware timestamps. `Variable.value_encrypted` is
`LargeBinary`, not text. `Domain` carries a CHECK constraint enforcing exactly
one of `service_id` / `deployment_id`.

`traefik.py` renders from Domain rows, not Service rows:

```python
async def render_all(session: Session) -> None:
    """Regenerate every dynamic config file. Idempotent, whole-dir rewrite."""
    for domain in session.exec(select(Domain)).all():
        target = resolve_target(session, domain)   # → live Instance set
        write_router(domain, target)
```

Called on: deploy success, domain create/delete, instance state change.

---

## Current Task

**Phase 1, steps 1–8 are written.** Decisions D1–D6 and D15 are accepted as
defaults ([ADR 0001](decisions/0001-phase-1-decisions.md)); the project is named
Rudder, not Helm ([ADR 0002](decisions/0002-project-name-rudder.md)).

The Phase 1 `## Verify` script has been run against live Postgres, BuildKit, a
local registry, Docker, and Traefik. A Node repo and a Python repo both deploy
from a git SHA to a serving URL. Failed builds, concurrent deploys, rolling
drain, and `docker kill` reconciliation all behave as specified — see the table
in `README.md` → Status.

Remaining in Phase 1: step 9 (Python SDK + CLI, not started) and step 10 (canvas
UI — written, but never compiled, because `npm` is blocked in this environment).

One addition to the phase as written: `services/monitor.py`. Phase 1's own
"done when" requires that killing a container be reflected, and nothing else in
Phase 1 observes actual state — the reconciler is Phase 2. The monitor observes
and records only; it never schedules, never restarts, and holds off on instances
the deploy path currently owns.

Still needed from you before step 5 — see [`NEED-FROM-YOU.md`](NEED-FROM-YOU.md):
`GITHUB_TOKEN` in `.env` (or confirmation that all repos are public), the
`insecure-registries` daemon change, a webhook tunnel, and two test repos.
