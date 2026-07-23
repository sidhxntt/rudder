# Phase 1 completion record

Status: complete locally on 2026-07-24.

Phase 1 delivers a single-host PaaS control plane. It runs a control plane,
build agent, private registry, Postgres, and Traefik on one Docker host. The
host is intentionally the scheduling boundary for this phase; multi-host
scheduling and durable runtime-log storage are later-phase work.

## Delivered

- Authenticated project, environment, service, domain, variable, deployment,
  and instance APIs with OpenAPI documentation and a generated Python SDK.
- Git-based builds with language detection, generated Dockerfiles, BuildKit,
  private image registry storage, health checks, and immutable deployment
  records.
- Safe rollout behaviour: a replacement is routed only after it is healthy;
  build or health failures leave the previous live instance serving traffic.
- Traefik routing for generated `*.localhost` service URLs and service-managed
  custom domains.
- Browser UI with login/session handling, a live project canvas, deployment
  history, build logs, variables, and clear failed-deployment/previous-live
  state.
- `rudder` CLI, generated Python SDK, signed GitHub push-webhook deployment,
  and deployment supersession/concurrency protection.
- Runtime-safe service, environment, and project deletion: owned containers
  are removed and Traefik is rendered before database records are deleted.

## Acceptance checks completed

The following were exercised against the local running stack on 2026-07-24:

- Deployed and reached a Node service (`api`) and Python service (`pyapi`) via
  their generated production URLs.
- Verified UI build logs, deployment history, service variables, login, and
  browser navigation.
- Forced a deliberately invalid Dockerfile on an isolated service. Its new
  deployment was marked `failed` while the old live URL continued returning
  HTTP 200. The configuration was restored afterwards.
- Stopped an isolated live container, confirmed its route stopped serving it,
  then redeployed and confirmed recovery.
- Created and deployed a service entirely through the CLI, including streamed
  deploy status and build-log retrieval.
- Created a temporary GitHub repository and signed push webhook. A real push
  returned HTTP 202, built the pushed commit, and changed the deployed
  response. Two near-simultaneous deploy requests resulted in one `live`
  deployment, one `superseded` deployment, and one healthy instance.
- Deleted the temporary services `rollout-test`, `cli-acceptance-e2e`, and
  `webhook-e2e`. Only the intended `api` and `pyapi` production services
  remain. The temporary GitHub webhook was also removed.

The temporary GitHub repository is pending deletion only because the local
GitHub CLI token needs the `delete_repo` scope. It is not a product
requirement and has no remaining active webhook.

## Automated validation

Run these commands from the stated package directory:

```sh
# control-plane
uv run --extra dev pytest -q
uv run --extra dev ruff check .

# agent
uv run --extra dev pytest -q
uv run --extra dev ruff check .

# SDK and CLI
cd ../sdk-python && uv build
cd ../cli && uv build && uv run rudder --help

# web
cd ../web && npm run typecheck && npm run build
```

Final results on 2026-07-24:

| Area | Result |
| --- | --- |
| Control plane tests | 255 passed |
| Control plane lint | passed |
| Agent tests | 50 passed |
| Agent lint | passed |
| Python SDK build | source distribution and wheel built |
| CLI build and smoke test | source distribution and wheel built; `rudder --help` passed |
| Web type check | passed |
| Web production build | passed (run in an isolated temporary copy to avoid modifying a running dev server) |

## Cleanup and repeatability

Test deployments and the one-time Cloudflare quick tunnel were intentionally
removed after acceptance testing. To repeat GitHub webhook testing, create a
new disposable repository, use a temporary public tunnel, configure the
existing webhook secret, and delete both artifacts afterwards.
