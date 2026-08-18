# Phase 3 — Kubernetes runtime contract, Kind acceptance, and isolation

> **Evidence status:** implemented and tested locally. Kind is an acceptance
> environment, not production. Some live Kind behavioural re-verification is
> constrained by the existing local cluster capacity; this document does not
> convert unit tests into a production claim.

## Goal and plan

Phase 3 moved the production-runtime design from individual Docker hosts to
Kubernetes without discarding Rudder's product model. Rudder still owns GitHub
imports, deployment records, domains, rollback intent, and the service graph;
Kubernetes owns Pod scheduling and private service networking.

The planned proof was a disposable Kind cluster and local registry bridge that
could import a Compose repository, build an immutable image, render an isolated
environment, make only the public app reachable, and retain the old public
revision on candidate failure. The consolidated design is recorded here and in
the [architecture guide](../architecture.md), supported by the Kubernetes
runtime implementation and tests.

## Resource translation design

Each Rudder environment maps to a namespace derived from its identifier.
Within it, the adapter translates the service catalog as follows:

| Rudder intent | Kubernetes primitive | Reason |
| --- | --- | --- |
| stateless app/worker/realtime/scheduler | Deployment | rolling readiness, replicas, resource limits |
| managed database/cache/broker | StatefulSet + PVC (or later CNPG for Postgres) | stable identity and data lifecycle |
| private dependency | ClusterIP Service + CoreDNS name | no public host port or ad-hoc mesh |
| explicitly public app | Ingress/Gateway route | controlled public surface |
| configuration and secrets | ConfigMap and Secret | per-environment configuration boundary |

The adapter applies CPU/memory requests and limits, probes, rolling-update
rules, HPA bounds, Jobs/CronJobs under allowlisted controls, node selectors and
placement preferences, and a PodDisruptionBudget where appropriate. Runtime
logs and pod resource metrics are collected through the Kubernetes API and
presented through Rudder's logs/metrics surfaces.

## Environment isolation model

An environment namespace is not merely an organisational label. It is paired
with a ResourceQuota, LimitRange, default-deny NetworkPolicy, controlled
ingress, and workload ServiceAccount/RBAC. Private services use Kubernetes DNS
such as `postgres.<namespace>.svc.cluster.local`; public exposure requires an
explicit public service. A workload identity has no broad Kubernetes token
privileges. The verifier includes guardrails and probes for cross-namespace
network isolation and quota behaviour.

This replaced the planned WireGuard mesh. The
[architecture guide](../architecture.md) explains why: CoreDNS, ClusterIP,
namespaces, and NetworkPolicy solve the same
problem on GKE/EKS/AKS with fewer peer/key/IP lifecycles to operate. The Phase 2
Docker path remains a lab; cross-host private Docker networking is not claimed.

## Rollout, rollback, and deletion logic

Rudder creates a release-qualified candidate workload and waits for Kubernetes
readiness before routing traffic. A stable route represents the environment's
current release; release-qualified routes can preserve permanent deployment
URLs. Failures remove candidate stateless resources, retain the old route and
mark the deployment failed. The subsequent audit hardened partial-route
compensation and ensured failure cleanup runs even if `runtime.apply` fails
before all local flags are set. Stateful data is intentionally retained rather
than casually deleted by release cleanup.

Rollback re-points a known healthy immutable release rather than rebuilding the
current Git branch. This is why deployment history contains image identity, not
just source branch names.

## Challenges and solutions

| Challenge | Treatment |
| --- | --- |
| Compose has public and private components | Compose import records roles; only an explicitly public app receives an ingress. |
| Kubernetes readiness can be mistaken for product success | Deployment status, health/readiness, instance accounting, and route promotion are sequenced; a desired replica is not displayed healthy merely because it was requested. |
| Partial API failures leave routes/resources inconsistent | Deploy compensation deletes candidate releases and restores/reconciles routes; tests exercise apply and cleanup paths. |
| State deletion risks workload data | Stateful PVC deletion is structurally restricted; explicit lifecycle controls are required. |
| Local cluster differs from production | Kind validates translation and failure semantics; GKE validates registry identity, TLS, durable backup, IAM, and operations. |

## Local cloud/cost perspective

Kind and a local registry minimise development cost and make repeatable tests
possible, but their laptop CPU/memory and networking do not model production
capacity, DNS delegation, workload identity, durable object storage, or a cloud
load balancer. The `make verify-kind` path is therefore an acceptance harness,
not a billing or resilience benchmark. A memory-saturated pre-existing Kind
cluster can legitimately block live verification; no workload is deleted merely
to make a test appear green.

## Evidence and remaining limits

Automated runtime, deployment, namespace, logs, metrics, and verifier tests
cover manifest translation, readiness, candidate cleanup, namespace teardown,
and observation. The project also added a public namespace-removal wrapper,
namespace derivation helper, and defensive verifier handling after audit.

The remaining boundary is honest: local static/automated checks are not the
same as a fresh live Kind proof of cross-namespace denial and quota exhaustion.
That live proof needs a healthy disposable Kind cluster; GKE production evidence
is documented in Phase 4.
