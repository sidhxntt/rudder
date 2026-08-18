# Phase 0 — Baseline, vocabulary, and decisions

> **Evidence status:** historical record. Phase 0 was documentation and decision
> work, not a deployable runtime. It is complete only in the sense that its
> baseline artifacts exist; it makes no availability or cloud-security claim.

## Purpose and plan

Rudder is a control plane for taking a source repository through build,
deployment, routing, observability, and rollback. Before building that path we
needed a shared definition of the product, a local setup that another developer
could reproduce, and explicit answers for choices that otherwise leak into every
later layer. Phase 0 therefore froze the starting point rather than creating
infrastructure.

The plan was deliberately small:

1. record the product requirements, constraints, non-goals, data model, and
   interfaces;
2. document a local development environment;
3. record the Phase 1 open decisions explicitly; and
4. publish a phase order and a rule that a phase needs evidence, not a demo
   anecdote, before it is considered complete.

The source baseline, requirements, environment setup, and initial architecture
decisions are consolidated in this retrospective and the [project overview](../overview.md).

## Design established

The most important choice was to make Rudder a **control plane**, not an
application-specific hosting script. The database owns desired state (projects,
environments, services, deployments, instances, domains, and variables); a
runtime executor observes or applies that state. This distinction is why later
Docker agents and Kubernetes adapters can change without changing the product
history presented to users.

The consolidated baseline accepted these early foundations:

| Decision | Why it mattered later |
| --- | --- |
| Build the localhost node agent in Phase 1 | Avoided a future rewrite from direct Docker calls to remote execution. |
| Put domains in their own table | One hostname can point at a particular release; this enables rollback, custom domains, previews, and permanent deployment URLs. |
| Persist canvas coordinates as UI metadata | The visual canvas is useful but never becomes deployment truth. |
| Use a GitHub token initially | Kept the first build path small; OAuth/App integration could be introduced with a clearer boundary later. |
| Treat Phase 1 logs as build logs | Prevented a misleading promise that runtime logging already existed. |

## Challenges and how the baseline addressed them

The hard problem at this stage was not code; it was avoiding accidental
architecture. A quick implementation that routes directly by service name,
creates containers with shell commands, or assumes a single host makes later
rollout and multi-tenant work disproportionately expensive. The baseline chose
interfaces and data concepts that would survive those changes. For example,
domains were modelled independently before any custom domain feature existed,
and the agent boundary was created before there was more than one machine.

## Cloud, security, and cost posture

No production cloud resources were created in this phase. The cost was
engineering time and local Docker prerequisites, not a cloud bill. Security
guidance was nevertheless established early: secrets belong in environment
configuration, variables must be write-only in API responses, and the local
registry needs an explicitly documented insecure-development exception rather
than silently weakening a production registry.

## Verification and handoff

The baseline is preserved in this phase narrative, the
[overview](../overview.md), [architecture](../architecture.md), and
[configuration guide](../configuration.md). Its handoff criterion was simple:
a Phase 1 implementer could explain what to build and how to start it without
oral history. Later phases provide runtime evidence; Phase 0 does not claim it.

## Limitations retained intentionally

- It did not prove deployments, cloud provisioning, or tenant isolation.
- It did not choose a universal multi-cloud abstraction; Kubernetes portability
  became a later, evidence-led decision.
- It recorded defaults that needed later review as GitHub, runtime logging,
  stateful services, and production cloud concerns appeared.
