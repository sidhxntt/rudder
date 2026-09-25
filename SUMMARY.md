# Rudder: beginner notes

## 1. The main idea

Rudder is a **control plane**. It records what an operator wants, asks a
runtime to make it real, and keeps checking the result.

```text
Desired state: “Run one healthy copy of this app.”
        ↓
Runtime reports: “Zero copies are running.”
        ↓
Rudder finds the difference and requests a repair.
        ↓
The runtime starts the app and reports again.
```

| Part | Simple job |
|---|---|
| Control plane and database | Save the desired state: what should exist. |
| Runtime | Run the app and report what actually exists. |
| Reconciler | Compare desired and actual state, then request safe repairs. |

The reconciler decides **what** should happen. The runtime does the local work
needed to make it happen.

## 2. Local Docker: how the agent helps

In the local Docker path, every Docker machine has a long-running **Rudder
agent**. It is Rudder software, not a Docker feature.

Before deployments can use a machine, a platform operator sets it up once:

1. Install and start the Rudder agent.
2. Give it access to that machine's Docker API.
3. Configure it to authenticate with the Rudder control plane.

When an operator deploys an app, Rudder does **not** create a new agent. The
control plane picks a healthy machine, and the existing agent uses Docker's API
to create, inspect, and remove containers. It also reports capacity, running
containers, and health.

```text
Control plane chooses a Docker machine
        ↓
Existing agent on that machine receives work
        ↓
Agent uses the local Docker API
        ↓
App container starts and agent reports its status
```

Why use an agent? Rudder could control Docker directly on one trusted machine.
Across several machines, that would require powerful remote access to every
Docker daemon. The agent keeps that access local, even when the network is
unreliable.

Other local Docker pieces:

| Component | Job |
|---|---|
| BuildKit | Builds the application image. |
| Local registry | Makes the image available to the chosen Docker machine. |
| Traefik | Sends web traffic to the correct container. |
| Persistent Docker volume | Stays on its original machine; Rudder does not automatically move it elsewhere. |

## 3. Background work: deploy once, then keep checking

### Deployment worker

Clicking **Deploy** creates a saved job. The web request does not wait for the
full build and rollout. One deployment worker claims the job so two workers do
not deploy the same app at the same time. It then:

1. Builds or gets the application image.
2. Uses Docker or Kubernetes to start a candidate release.
3. Waits for health checks.
4. Records success or failure.
5. Sends traffic to the candidate only when it is healthy.

### Reconciler

The reconciler runs repeatedly after deployment. It can:

- Mark a Docker node unavailable when its agent stops sending heartbeats.
- Notice a missing container or Pod.
- Recreate eligible stateless web apps and workers.
- Process saved actions such as restart, scale, or delete.
- Retry a GitHub pull-request notification after a temporary failure.

It does not automatically move a stateful workload if its data may be tied to
one disk. Retry **backoff** means waiting longer after each repeated failure.

```text
Try now → fail → wait a little → try again → wait longer → try again
```

## 4. Kubernetes: Kind and GKE

Kubernetes replaces much of the node-level work done by the Docker agent.

| Local Docker | Kubernetes |
|---|---|
| Rudder agent manages local containers. | Kubernetes node components, including kubelet, run Pods. |
| Agent uses Docker API. | Rudder's Kubernetes adapter uses the Kubernetes API. |
| Rudder scheduler chooses a Docker host. | Kubernetes scheduler chooses a Kubernetes node. |
| Agent reports containers and capacity. | Kubernetes reports Pod, Deployment, and readiness status. |
| Traefik routes traffic. | Services and Ingress/ingress-nginx route traffic. |

```text
Rudder database: desired application state
        ↓
Rudder Kubernetes adapter: creates Kubernetes resources
        ↓
Cluster: Deployment, Pod, Service, Ingress, Secret, PVC
        ↓
Kubernetes controllers and kubelet run the workload
        ↓
Kubernetes reports status to Rudder
```

There are two reconciling layers:

- **Kubernetes controllers** make Kubernetes resources match their Kubernetes
  specs, such as keeping the requested number of Pods running.
- **Rudder's reconciler** checks whether Kubernetes achieved what Rudder's
  operator requested, and handles Rudder-level operations and history.

### Kind versus GKE

**Kind** is the local Kubernetes test environment. It proves that Rudder can
turn its application intent into correct Kubernetes objects.

**GKE** is Rudder's current production-shaped cloud target. Terraform prepares
the GCP foundation: the cluster, node pools, IAM and Workload Identity, image
registry, build service, DNS, storage/backup services, networking, and shared
platform tools such as ingress-nginx and cert-manager.

Rudder uses an **attach model** on GKE: Terraform owns the cluster and cloud
foundation; Rudder owns the application environments and workloads inside it.

## 5. Multi-cloud: what stays the same and what changes

Multi-cloud would require more than swapping Terraform files.

| Usually portable | Changes by cloud provider |
|---|---|
| Rudder control plane, database, web UI, CLI, API, deployment history, and reconciliation | Terraform for network, cluster, registry, storage, IAM, quotas, and billing |
| Kubernetes objects: Deployments, Services, PVCs, Secrets, and health checks | Identity, load balancers, ingress, DNS, certificates, storage, and backups |
| Immutable releases, promotion, and rollback | Build/registry permissions, pricing, error handling, and cloud-specific tests |

Example GCP-to-AWS mapping:

| GCP | AWS |
|---|---|
| GKE | EKS |
| Artifact Registry | ECR |
| Cloud Build | CodeBuild |
| Cloud DNS | Route 53 |
| Cloud Storage | S3 |
| Workload Identity | IRSA or EKS Pod Identity |
| Cloud Monitoring | CloudWatch |

The goal is to keep cloud differences at the infrastructure boundary, not
spread them through the web UI, CLI, or core deployment logic.

## 6. Engineering challenges, in brief

| Phase | Challenge | Rudder's answer |
|---|---|---|
| 0 | Avoid a throwaway demo architecture. | Start with a control plane, desired state, and runtime adapters. |
| 1 | Do not replace a healthy release with a broken one. | Use queued immutable releases, locks, health checks, and safe promotion. |
| 2 | Recover across Docker hosts without duplicate or unsafe stateful work. | Lock placement, ignore stale reports, and replace only stateless work automatically. |
| 3 | Turn application intent into safe Kubernetes resources. | Use namespaces, private Services, NetworkPolicy, readiness checks, and stateful safeguards. |
| 4 | Run a real cloud path safely. | Use GKE, Terraform, scoped identity, immutable images, backups, and recovery drills. |
| 5 | Make PR previews safe and disposable. | Clone safely, avoid production data, use idempotency, and retry cleanup. |
| 6 | Protect stateful data and prevent unbounded logs/metrics. | Pin volumes, protect PVC deletion, bound telemetry, and roll back known releases. |
| 7 | Deploy static and server-rendered frontends correctly. | Use nginx for static files and app containers for SSR; keep release URLs immutable. |
| 8 | Use AI without giving it deployment power. | Keep AI advisory and read-only; make real changes through normal APIs. |
| 9 | Give the CLI the same safe behavior as the web UI. | Use the same authenticated API and redact secrets. |
