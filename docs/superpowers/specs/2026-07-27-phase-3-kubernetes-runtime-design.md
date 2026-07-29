# Phase 3 Kubernetes Runtime Design

## Purpose

Phase 3 makes Kubernetes Rudder's production runtime. It is delivered in two
ordered stages: prove the adapter on a disposable local `kind` cluster, then
move the same workload model to GKE Standard. The Phase 2 Docker-agent runtime
remains the verified scheduling/failover laboratory; it is not the production
customer workload runtime.

The previous Phase 2.5 Kubernetes roadmap becomes Phase 3. The previous
WireGuard mesh roadmap becomes Phase 4. Later phase numbers shift by one:
environments to 5, operations to 6, frontends to 6.5, and advisor to 7.

## Architecture

Rudder's control plane remains the owner of product intent: projects,
environments, services, deployments, immutable revisions, domains, and audit
history. A Kubernetes runtime adapter translates a confirmed Compose release
into resources in one namespace per Rudder environment.

| Rudder service role | Kubernetes resource |
|---|---|
| web, API, worker, scheduler, realtime | Deployment and ClusterIP Service |
| PostgreSQL, Redis, broker, search, storage | StatefulSet, ClusterIP Service, PVC |
| public HTTP service | Ingress/Gateway route, Service, TLS policy |
| configuration | Secret and ConfigMap |
| environment isolation | Namespace, ServiceAccount, ResourceQuota, LimitRange, default-deny NetworkPolicy |

Every deploy uses a unique immutable image digest. The adapter creates a
candidate revision, waits for Kubernetes readiness, then changes the public
route only after success. A rollback never rebuilds: it points the workload and
route at the recorded prior immutable digest.

## Stage 1: Local Kubernetes acceptance environment

`kind` is the local platform because it is upstream-Kubernetes-compatible and
can grow into a multi-node test cluster without changing the resource model.

Local topology:

```text
Rudder web + control plane (docker-compose.dev.yml)
              │ kubeconfig
              ▼
kind cluster ── namespace rudder-<project>-<environment>
              ├── app/worker Deployments
              ├── database/cache StatefulSets + PVCs
              ├── ClusterIP Services + NetworkPolicies
              └── local ingress → *.localhost public test URL
```

Step 1 includes:

1. Reproducible `kind` bootstrap, local image registry, ingress controller, and
   a multi-node optional profile.
2. A typed Kubernetes adapter behind the existing runtime boundary; no direct
   `kubectl` shell-outs in product code.
3. Namespace ownership labels, deterministic resource names, and safe cleanup.
4. Compose-to-Kubernetes translation for the supported imported topology:
   web/API, worker, Postgres, Redis, volumes, environment variables, ports,
   health checks, dependencies, and public-service selection.
5. Deployment/event/log status projection into the existing Rudder UI.
6. Automated local acceptance: private service discovery, namespace isolation,
   readiness-gated traffic, failed-release safety, immutable restore, and
   teardown.

The local cluster is a verification target only. It must be destroyable and
must not contain credentials or durable production data.

## Stage 2: GKE Standard

Once the local acceptance suite passes unchanged against the adapter, provision
a private GKE Standard cluster in the existing GCP project. Standard is the
chosen target because Rudder needs explicit control over node pools, ingress,
network policy, build capacity, and workload scheduling during this phase.

GCP components:

- private GKE Standard cluster with separate system, builder, and customer
  workload node pools;
- Artifact Registry for immutable images;
- Workload Identity, least-privilege Kubernetes RBAC, and Google service
  accounts;
- Gateway/Ingress, managed certificates, DNS, and a stable public endpoint;
- Cloud SQL/object storage for control-plane metadata and artifact/log backup;
- secret storage through Secret Manager or an equivalent encrypted integration;
- Terraform for all cloud resources and reproducible teardown.

Customer namespaces remain isolated through RBAC, ResourceQuota, LimitRange,
NetworkPolicies, and explicit ingress routing. A first live GKE acceptance
deploys `web + worker + PostgreSQL + Redis`; only `web` gets a public URL.

## Failure handling

- Kubernetes API errors leave the recorded revision failed and preserve the
  currently live route and workloads.
- Readiness timeout captures pod events and logs in the deployment record.
- Controller restart reconciles desired state against namespace-labelled
  resources; it does not create a second release.
- Restore selects an existing successful immutable revision; it does not invoke
  the build pipeline.
- Namespace deletion is idempotent and retains Rudder history according to the
  retention policy.

## Verification and success criteria

Local Stage 1 must prove:

1. Two environments receive distinct namespaces and cannot resolve or reach
   each other's private services.
2. An imported `web + worker + PostgreSQL + Redis` release gives only `web` a
   public local URL.
3. A failed candidate does not disrupt the previous live URL.
4. Restoring a prior revision uses its existing digest without a build.
5. Service, pod, event, and log state agree in Kubernetes and the Rudder UI.

GKE Stage 2 repeats those tests against the GKE cluster, adds HTTPS/DNS,
workload identity, quota enforcement, and full teardown verification.

## Out of scope

- Replacing all cloud databases with in-cluster stateful services for production
  critical workloads before backup/restore guarantees exist.
- Cross-cluster federation, multi-region traffic management, or autoscaling
  beyond safe initial limits.
- Removing the Docker runtime before the Kubernetes path passes its acceptance
  suite.
