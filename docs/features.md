# Features: the Rudder operator experience

This page describes what a user sees and what component makes it work. It uses
the labels **implemented**, **verified**, and **planned/mapped** defined in
[overview.md](overview.md).

## Railway-style workspace — implemented

Rudder's authenticated Next.js workspace provides an environment canvas and
resource controls around it. A project can contain production, staging, or PR
environments. Services appear as graph nodes, with relationship edges and
canvas placement retained as part of the environment's declarative state.

The interface is not merely a dashboard. It calls resource APIs for project
creation, environment cloning, service editing, variables, domains,
deployments, operations, imports, Advisor acceptance, logs, and metrics. That
same API contract is available to the CLI.

## Manual repository import and deployment — implemented

The import flow uses GitHub App installations, repository/branch discovery,
and a preview before confirmation. Rudder then either normalizes a supported
repository Compose file or generates a conservative plan from supported source
signals. The resulting services can be deployed manually, with build and
runtime evidence available afterward.

Why confirmation matters: repository analysis is helpful, but an automatic
guess should not create a database, expose a route, or commit deployment intent
without a person reviewing it.

## Automatic GitHub deployment — implemented when GitHub is configured

Signed GitHub webhooks queue the same deployment workflow used by the manual
flow. Pull-request events can create a full, capped preview environment from a
source graph. Close/merge events remove the preview. A durable notification
record lets Rudder retry its ready comment instead of losing it during a brief
GitHub outage.

**Operator dependency:** this feature needs a configured GitHub App, webhook
secret, reachable callback/webhook URL, and the appropriate repository
installation. Those credentials are intentionally not part of the repository.

## Vercel-style release URLs — implemented

Rudder maintains two kinds of domain target:

- A **stable service URL** follows the live deployment; this is the ordinary
  application address.
- A **deployment-pinned URL** names one immutable release; it is useful for
  review, debugging, and proving which release was observed.

Rollbacks move the stable alias to a healthy earlier deployment. They do not
rebuild an artifact or invalidate a release-pinned URL.

## Application and frontend support — implemented

The generic application route supports Dockerfiles and generated build
instructions for common backend patterns. The frontend detector recognizes
Vite, Create React App, Astro static sites, and Next static exports. Static
outputs become unprivileged nginx images with SPA fallback and cache behaviour;
Next SSR remains an ordinary long-running application container.

This is intentionally one execution model: static output is still a container
artifact, and SSR already behaves like an app server.

## Service graph, managed dependencies, and private networking — implemented

An environment can include an app, worker, PostgreSQL, Redis, or other
reviewed catalog services. Variables can wire connections through private
references. Public access is opt-in per service; databases and caches are not
given public routes.

In Kubernetes, the graph becomes private services in one namespace with
default-deny network policy. In the local Docker path, Traefik reaches only
containers on the Rudder network. The exact runtime implementation is detailed
in [architecture.md](architecture.md).

## Environments and pull-request previews — implemented

Cloning creates a new declarative service graph: services, encrypted variables,
and layout are copied; deployments, live instances, historical logs, domains,
and data volumes are not. That choice makes “clone production to staging” a
safe configuration operation rather than an accidental data copy.

PR environments are ephemeral branches of this design. They are limited by
configuration and automatically cleaned up by relevant GitHub events.

## Operations and observability — implemented

Rudder retains deployment/build logs, runtime logs, instance health, CPU and
memory samples, and deployment history. It offers durable operation requests
for actions such as restart, scale, rollback, backup, and observability
configuration. Operations are executed by the control plane/reconciler, not by
a browser making privileged infrastructure calls.

Eligible Kubernetes application workloads can persist autoscaling bounds and
CPU/memory targets. Rudder reconciles those settings as a Kubernetes
`HorizontalPodAutoscaler`; manual replica intent and HPA intent are mutually
exclusive. Docker workloads and GKE cluster/node capacity are not autoscaled by
Rudder.

Persistent Docker volumes have a special rule: they are node-local and cannot
be safely rescheduled to a new host as though their data moved with them. The
Kubernetes model uses StatefulSets/PVCs and, on GKE, CloudNativePG for the
PostgreSQL durability contract.

## CLI — implemented

`rudder` is a TypeScript/Node CLI. It supports:

- interactive GitHub browser sign-in and project onboarding;
- an interactive launcher for deploy, status, logs, services, variables, and
  Advisor-related work;
- explicit commands and `--json` output for automation;
- compact status, detailed raw status, and optional AI summary views;
- followed logs and readable error/cancellation contracts.

The CLI remains deliberately thin: a script still talks to the control plane,
so its state is immediately visible in the web workspace. It can use
`RUDDER_TOKEN` for non-interactive automation.

## Rudder Advisor and Ask Rudder — implemented, read-only AI enhancement

Advisor scans a local repository checkout and returns a proposed graph. The UI
renders proposed services as ghost nodes; acceptance uses ordinary service APIs
and validates the target environment. Advisor cannot autonomously apply an
entire plan.

The build-failure diagnosis API and Ask Rudder panel can use OpenAI to phrase
explanations from bounded, redacted context. They are intentionally read-only.
If `OPENAI_API_KEY` is not configured, Rudder does not fabricate an AI answer;
the deterministic system remains available and reports the missing optional
capability clearly.

## What these features are not

Rudder is not currently a hosted multi-tenant Railway/Vercel replacement, a
serverless functions platform, a billing system, a Docker or cluster/node
autoscaler, or a global edge/CDN. Its autoscaling scope is an HPA for eligible
Kubernetes application workloads. It is a self-hosted deployment control plane
with a carefully scoped container and Kubernetes runtime. That honesty matters
when planning a real production adoption.
