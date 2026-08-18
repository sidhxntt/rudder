# Rudder across clouds: a GCP reference and a portable target architecture

This guide explains how Rudder is designed to move from its **GCP-first
reference implementation** toward a multi-cloud deployment platform. It is
written for a reader who knows neither Kubernetes nor public-cloud terminology.
It deliberately separates three things that can otherwise sound the same:

1. **Implemented now** — local Docker/Kind support and the GCP/GKE foundation
   described in this repository.
2. **GCP controlled beta** — the guarded production-shaped path that has
   Terraform, manifests, identities, operational runbooks, and automated
   contract tests, but is not a claim of generally available SaaS hosting.
3. **Target design** — how the same product concepts would map to AWS and
   Azure. Those clouds are *not implemented or provisioned by Rudder today*.

Read [overview.md](overview.md) first for the product story and
[architecture.md](architecture.md) for the control-plane/runtime model.

## 1. The problem in plain language

An application team wants a simple answer to “put this version of my service
online.” A cloud platform must do much more than start a container:

- build an image from a known source revision;
- store it somewhere workers can pull it reliably;
- choose capacity without exposing one customer's application to another;
- wait for readiness before sending public traffic to it;
- preserve logs, metrics, and deployment history when a process dies;
- protect secrets, DNS, database data, and cloud credentials; and
- make rollback and deletion explicit rather than accidental.

Rudder models those responsibilities once in its control plane, then delegates
the provider-specific parts to a runtime adapter and a cloud foundation. This
is the key portability idea: **the product vocabulary stays stable even when
the cloud implementation changes.**

```text
User / CLI / Web / GitHub event
             │ desired state through one API
             ▼
        Rudder control plane
  projects · environments · deployments · operations
             │
             ├── portable Kubernetes runtime contract
             │       namespaces, services, pods, routes, logs, metrics
             │
             └── cloud integration boundary
                   identity · registry · build · DNS · storage · monitoring
```

This is not “write once and forget the cloud.” Identity, networking, pricing,
quotas, and managed-service semantics remain provider-specific. The point is
to keep those differences at deliberate boundaries rather than spreading them
through every web page, CLI command, and deployment state transition.

## 2. The common model that every cloud must preserve

### Control plane versus workload plane

Rudder has two broad planes:

| Plane | Responsibility | Must be portable? |
|---|---|---|
| Control plane | API, authentication, desired state, deployment records, scheduler/reconciler, audit trail | Yes; it should work against supported runtime targets. |
| Workload plane | environment pods/containers, private networking, persistent volumes, public ingress | Yes at the Kubernetes contract level; its cloud backing differs. |
| Shared platform services | ingress controller, DNS automation, certificates, secrets sync, database operator, monitoring integration | Mostly portable charts/manifests; cloud identities and load balancers differ. |
| Cloud foundation | network, cluster, registry, object storage, IAM, quotas, billing accounts | No; managed through provider-specific infrastructure-as-code. |

The control plane records a deployment before it asks a runtime to enact it.
That durable record is why a failed node, lost CLI session, or delayed webhook
does not erase intent. The runtime returns observed facts—ready replicas,
route state, logs, metrics—and the control plane reconciles those facts with
the desired state.

### Tenant and environment boundaries

The current data model is `User → Project → Environment → Service`. A service
has deployments and instances; an environment has variables and domains. On
Kubernetes, an environment becomes an identifier-derived namespace containing
its workloads, `ClusterIP` services, secrets/configuration, default-deny
network policy, resource controls, and a dedicated tokenless ServiceAccount.

This yields an important distinction:

- **Implemented environment isolation:** namespace naming, ownership checks at
  API boundaries, private-by-default service networking, scoped routes, and
  Kubernetes guardrails.
- **Target hardened tenant isolation:** an external organization/tenant model,
  membership and role policy, budgets/chargeback, stronger admission controls,
  per-tenant encryption policy, and possibly dedicated clusters/accounts for
  high-risk tenants.

The latter is not silently implied by the former. Namespaces are valuable
operational boundaries, but by themselves are not a security guarantee for
arbitrary hostile workloads. A production multi-tenant offering requires
defence in depth: workload admission policy, Pod Security standards, image
provenance/scanning, egress control, strict RBAC, resource quotas, runtime
hardening, vulnerability response, and a documented isolation tier.

### The portable release sequence

Across clouds, a safe release has the same logic:

1. Associate the request with an immutable source revision.
2. Build and publish an immutable image digest.
3. Render a candidate workload in the environment boundary.
4. Observe readiness and collect diagnostics.
5. Give the successful candidate a permanent release address where configured.
6. Move the stable service address only after the candidate is healthy.
7. Mark the deployment live in durable state, retire old candidate resources
   according to retention policy, and retain enough history to diagnose or
   roll back.

Route writes and database changes cannot form one distributed database
transaction. Rudder therefore treats promotion as a small saga: order the
operations safely, compensate a failed route write, preserve the old stable
route where possible, and persist a clear failure rather than claiming success.
That rule is cloud-independent.

## 3. What GCP currently provides

### Current status and scope

GCP is Rudder's implemented cloud reference. The intended production-shaped
target is a regional GKE Standard cluster in **attach mode**: Terraform creates
and owns the shared cloud foundation; Rudder attaches from `rudder-system` and
creates environment namespaces and workloads. It does not let a normal Rudder
deployment create, resize, upgrade, or destroy the cluster itself.

This repository records a controlled-beta foundation, not an assurance that a
fully enabled multi-tenant commercial service is running. In particular, the
workloads node pool is deliberately gated by regional aggregate CPU quota, the
backup path has an explicit identity-and-restore gate, and local Kind remains
the normal disposable acceptance environment. See
[Phase 4 narrative](phases/phase-4.md) and the
[controlled-beta evidence record](evidence/phase-4-controlled-beta.md).

### GCP reference topology

```text
Internet
  │ DNS records in a delegated Cloud DNS zone
  ▼
Cloud load balancer created for ingress-nginx
  ▼
Regional private-node GKE Standard cluster
  ├─ system pool: GKE-managed components (not Rudder-tainted)
  ├─ platform pool: ingress/control-plane, tainted for platform workloads
  └─ workloads pool: environment workloads, quota-gated and disabled until safe
       │
       ├─ rudder-system: control plane and platform controllers
       └─ environment namespaces: service graphs
              Deployment / StatefulSet / Service / Ingress / NetworkPolicy
```

The VPC-native GKE design uses a dedicated VPC, private nodes, separate pod and
service address ranges, Cloud NAT for egress, and a DNS/IAM operator endpoint.
Kubernetes NetworkPolicy enforcement is explicitly enabled. This avoids the
old Phase 2 VM/WireGuard model for production workload networking: Kubernetes
Services and CoreDNS provide in-cluster discovery; namespace policy constrains
traffic.

### GCP service map

| Rudder need | GCP reference service or mechanism | Why it exists |
|---|---|---|
| Managed container runtime | GKE Standard, regional | Kubernetes API and failure domain across zones; node-pool separation. |
| Network | VPC, subnet secondary ranges, Cloud Router/NAT | private nodes, pod/service IP allocation, controlled outbound access. |
| Image registry | Artifact Registry (Docker) | immutable platform and workload image distribution. |
| Build | Cloud Build | build from an already-authorized revision, using a separate publisher identity. |
| Build source/log retention | separate private Cloud Storage buckets | short source expiry, durable build-log view, no mixing with database backups. |
| Database backup object store | Cloud Storage with versioning/lifecycle | CloudNativePG/Barman backup/WAL target, retention managed at bucket level. |
| Runtime secrets | Secret Manager + External Secrets integration | Terraform creates container/access policy, but not secret values in state. |
| Public naming | Cloud DNS + ExternalDNS + ingress-nginx | delegated-zone routes without giving applications project-wide DNS power. |
| TLS certificates | cert-manager DNS challenge | automated certificate issuance through a dedicated DNS identity. |
| Workload cloud identity | GKE Workload Identity | Kubernetes ServiceAccounts federate to narrowly scoped Google identities; no JSON keys. |
| Metrics/log alerting | Cloud Logging and Cloud Monitoring policies | durable cloud-side evidence and alert evaluation for restarts/image pulls. |
| Infrastructure lifecycle | Terraform + reviewed bootstrap scripts | reproducible foundation, not ad-hoc console state. |

### GCP identities and least privilege

The reference separates node, build publisher, control-plane runtime, backup,
backup-identity broker, certificate manager, and secret synchronization
identities. The control plane may start a build but does not receive Artifact
Registry write permission; Cloud Build runs as the narrower publisher identity.
ExternalDNS can discover zones at project scope but mutates only the delegated
Rudder zone. The backup broker, not the general control plane, holds the tiny
permission surface that can bind a per-environment Kubernetes ServiceAccount
to the backup Google service account.

These distinctions matter in every cloud. “The cluster can access the cloud”
is not an acceptable permission model. The desired rule is: **each workload
and controller gets only the identity and resource scope needed for its job.**

### GCP cost and capacity behavior

Cloud bills cannot be inferred from a service's container status. The dominant
cost centres are usually:

- regional GKE node pools and their per-zone minimum capacity;
- load-balancer, public IP, DNS-query, and network-egress charges;
- Artifact Registry image storage and Cloud Build execution minutes;
- Cloud Storage capacity, object operations, and backup retention;
- Cloud Logging ingestion/retention and Cloud Monitoring metrics/alerts;
- persistent disks/PVCs and database replication;
- NAT traffic and any cross-zone or Internet traffic.

The reference intentionally surfaces an early GKE quota reality: a regional
three-zone `e2-standard-2` node pool consumes six vCPUs, and GKE checks the
project-wide `CPUS_ALL_REGIONS` quota. The system and platform pools can
consume 12 vCPUs before dedicated environment workload capacity exists. The preflight script
checks both credentials and quota before Terraform tries to create the gated
workloads pool. This is a capacity safety mechanism, not a cost quote.

For a real tenant billing model, Rudder would need measured usage attribution
(CPU/memory requests and usage, persistent storage, build minutes, egress,
load-balancer/DNS share, and managed-service usage), a pricing policy,
budget/alert thresholds, currency/tax handling, and explicit rules for shared
overhead. None of those are implemented as product billing today.

## 4. What stays the same on AWS and Azure

Kubernetes makes a large part of the workload contract portable:

| Product contract | Same on GCP, AWS, and Azure |
|---|---|
| Desired state | Control-plane Postgres records, API resources, operations, audit semantics. |
| Deployment shape | Deployment/StatefulSet, Service, PVC, ConfigMap/Secret, readiness probes. |
| Environment isolation baseline | namespace per environment, owner checks, default-deny policy, quotas, dedicated ServiceAccount. |
| Release semantics | immutable image digest, candidate readiness, permanent revision route, stable promotion, failure compensation. |
| Platform services | ingress-nginx, cert-manager, ExternalDNS-compatible controller, CloudNativePG, External Secrets, telemetry collectors can be deployed as Kubernetes workloads. |
| Client experience | CLI, web UI, GitHub integration, Advisor proposals, logs/metrics/status models. |
| IaC discipline | provider-specific Terraform modules plus pinned Helm/manifests and read-only preflight/verification. |

The wording “same” does not mean the cloud control planes behave identically.
For example, storage class semantics, load-balancer controller permissions,
identity federation subjects, DNS APIs, and quota error formats need distinct
adapter/configuration code and acceptance tests.

## 5. AWS target mapping — design only

AWS is not provisioned by Rudder today. A future AWS implementation should
retain the contracts above while replacing GCP integrations as follows.

| GCP reference | Probable AWS equivalent | Important difference to design/test |
|---|---|---|
| GKE Standard | Amazon EKS | EKS version/add-on lifecycle, endpoint exposure, node groups/Fargate choice, and IAM integration differ. |
| VPC-native pod/service ranges | VPC + EKS CNI (or another approved CNI) | IP consumption and security-group model are materially different; plan subnet capacity early. |
| Cloud NAT | NAT Gateway | billed per gateway/hour and per GB; multi-AZ resilience can be expensive. |
| Artifact Registry | Amazon ECR | repository policies, lifecycle rules, scanning, and cross-account distribution must be defined. |
| Cloud Build | CodeBuild, or another isolated build service | use immutable source handoff and separate publish role; do not give the control-plane role ECR write by default. |
| Cloud Storage | S3 | define versioning, object lock/retention policy, lifecycle, encryption/KMS, and bucket policy separately for source, logs, and backups. |
| Secret Manager | AWS Secrets Manager or SSM Parameter Store | decide rotation, KMS key ownership, External Secrets provider, and replication behavior. |
| Cloud DNS | Route 53 hosted zone | delegated zone and TXT ownership remain important; DNS API IAM should be hosted-zone scoped where possible. |
| Workload Identity | EKS Pod Identity or IRSA | pod ServiceAccount-to-IAM-role association replaces GKE federation; trust policies must constrain issuer, namespace, and service-account subject. |
| Cloud Logging/Monitoring | CloudWatch Logs, Metrics, Alarms | retention and ingestion costs/labels differ; consider OpenTelemetry for a consistent application layer. |
| GCP load balancer via ingress | AWS Load Balancer Controller / NLB or ALB design | choose controller and route model deliberately; ingress-nginx behind NLB is not equivalent to ALB Ingress resources. |

### AWS multi-tenant design decisions

An AWS tenant can live in a namespace inside one EKS cluster, a dedicated EKS
cluster, or a dedicated AWS account. These are increasing isolation tiers, not
interchangeable implementation details:

- **Shared EKS / namespace:** lowest operational overhead and fastest to start;
  requires strong admission, network, IAM, resource, and observability policy.
- **Shared account / dedicated cluster:** better blast-radius and upgrade
  separation, but costs more and makes shared control-plane connectivity and
  fleet management more complex.
- **Dedicated account / cluster:** strongest billing and IAM boundary; requires
  account vending, cross-account control-plane roles, central logging, DNS
  delegation, and an explicit support model.

EKS Pod Identity or IRSA roles must be tenant/environment scoped. Never solve
tenant cloud access by placing broadly privileged AWS credentials in a
namespace secret or inheriting the node instance profile. For database backups,
a dedicated role should be restricted to the appropriate S3 prefix/bucket and
KMS permissions, with an independently verified restore drill.

## 6. Azure target mapping — design only

Azure is not provisioned by Rudder today. A future Azure implementation would
make the following substitutions.

| GCP reference | Probable Azure equivalent | Important difference to design/test |
|---|---|---|
| GKE Standard | Azure Kubernetes Service (AKS) | node pool, upgrade channel, private cluster, and Azure RBAC choices must be fixed in the foundation contract. |
| GCP VPC/subnet/NAT | Azure VNet, subnets, NAT Gateway | Kubernetes network plugin choice (Azure CNI overlay/other approved mode) drives IP and policy behavior. |
| Artifact Registry | Azure Container Registry (ACR) | use managed identity/RBAC pull and push assignments; define retention/geo-replication/scanning. |
| Cloud Build | Azure DevOps Pipelines, GitHub Actions with Azure identity, or Azure Container Registry Tasks | select one isolated build authority and preserve digest/provenance controls. |
| Cloud Storage | Azure Blob Storage | distinct containers/accounts for build source, build logs, and backups; lifecycle, immutability, and customer-managed keys require explicit policy. |
| Secret Manager | Azure Key Vault | workload identity access policies/RBAC, secret rotation, and CSI/External Secrets delivery need an agreed pattern. |
| Cloud DNS | Azure DNS | limit DNS update identity to the delegated zone and preserve ExternalDNS TXT ownership convention. |
| GKE Workload Identity | Microsoft Entra Workload ID / managed identities | federated identity credentials bind a Kubernetes ServiceAccount subject to a user-assigned managed identity. |
| Cloud Monitoring | Azure Monitor, Log Analytics, Managed Prometheus | workspace topology, retention, and ingestion costs differ from GCP. |
| ingress load balancer | Azure Load Balancer / Application Gateway / approved ingress controller | choose the controller and WAF/L7 model before promising route behaviour. |

### Azure multi-tenant design decisions

The shared cluster versus dedicated cluster/subscription decision has the same
security trade-off as AWS, but Azure's management-group/subscription/resource-
group model adds another useful organization boundary. A target design should
decide whether an organization/tenant receives:

- a namespace in a shared AKS cluster;
- a resource group and delegated identity scope;
- a dedicated AKS cluster in a shared subscription; or
- a dedicated subscription with central-policy and management-group controls.

Use Entra Workload ID with subject-restricted federated credentials and
least-privilege Azure RBAC. Do not use kubelet/node credentials or long-lived
service-principal secrets as a shortcut. Backups require a separate managed
identity restricted to the intended Blob container/path; restoration must be
tested before the feature is advertised.

## 7. The cloud-adapter boundary Rudder should maintain

The current Kubernetes runtime already hides many implementation details behind
runtime operations such as apply, observe readiness, get logs/metrics, delete
release, and route management. A future multi-cloud design should avoid a
single giant `if provider == ...` branch. Instead, retain small boundaries:

```text
Portable deployment service
   ├─ source/build publisher interface
   ├─ image registry interface
   ├─ Kubernetes runtime interface
   ├─ DNS/route integration interface
   ├─ secrets/identity broker interface
   ├─ backup object-store interface
   └─ monitoring/alert integration interface
```

Each provider module should expose the same safety-oriented capabilities, not
just raw SDK calls. For example, a DNS method should accept a managed Rudder
route and enforce its delegated-zone boundary; an identity broker should bind
only an approved namespace/service-account subject; a storage module should
make retention/encryption policy visible. The control plane must not need to
know whether a route became an ALB listener rule, an Azure gateway rule, or a
GCP-backed ingress.

## 8. Multi-tenant security requirements before expansion

Before advertising multi-cloud or generalized multi-tenancy, validate each
provider against a common acceptance matrix:

1. **Identity:** a workload can obtain only its intended cloud identity; a
   tenant workload cannot impersonate another tenant, platform controller, or
   node identity.
2. **Network:** default deny works; allowed dependencies work; cross-namespace
   traffic and unauthorized public exposure fail.
3. **Compute:** quotas and limit ranges prevent one environment from exhausting
   the cluster; scheduler/auto-scaler behavior is observable.
4. **Storage:** a PVC, backup object, registry repository, and secret are not
   readable across tenants; destructive restore/delete paths require explicit
   authority.
5. **Routing:** only declared public services receive managed DNS/TLS routes;
   a failed candidate cannot replace a stable route.
6. **Build provenance:** source revision, build identity, image digest, and
   deployment record are linked; unapproved images cannot be substituted.
7. **Observability:** operators can diagnose a tenant incident without leaking
   another tenant's logs, environment variables, or identifiers.
8. **Offboarding:** environment/project deletion removes workloads and managed
   routes safely, applies retention rules, and leaves an auditable record.
9. **Recovery:** backup restoration is tested for the provider's identity,
   storage, and database operator path—not assumed from a manifest.

Testing should include real provider acceptance environments where possible.
Unit tests and Kind are excellent for contract coverage, but cannot prove IAM
federation, cloud DNS authority, quota admission, load-balancer behavior, or
billed egress semantics.

## 9. Cost controls and operational model across clouds

### Shared principles

- Keep the platform foundation in reviewed Terraform, with no secret values in
  Terraform state or Git.
- Separate short-lived build source, durable build logs, and database backups.
- Require explicit retention periods; storage that never expires becomes both a
  privacy risk and a cost surprise.
- Preflight quotas before provisioning regional/zone-replicated capacity.
- Tag/label every provider resource with platform, environment/project when
  appropriate, owner class, and lifecycle so costs and incident evidence can
  be attributed.
- Maintain independent cluster, provider, and restore runbooks.
- Treat public egress, NAT, load balancers, log ingestion, and cross-zone data
  transfer as first-class cost signals, not background noise.

### What changes by provider

| Concern | GCP | AWS | Azure |
|---|---|---|---|
| Regional capacity gotcha | aggregate CPU quota for regional pools | account/region vCPU quota, ENI/IP/subnet capacity, NAT-per-AZ choice | regional vCPU quota, subnet/IP allocation, SKU availability |
| Identity primitive | Workload Identity federation | Pod Identity or IRSA role trust | Entra Workload ID / managed identity federation |
| Object storage pricing shape | storage class + operations + network | class + requests + retrieval/egress | access tier + operations + retrieval/egress |
| Ingress cost shape | cloud LBs and egress | ALB/NLB, LCU, NAT, data transfer | LB/App Gateway/WAF, data processing, egress |
| Logging | Logging ingestion/retention | CloudWatch ingestion/retention | Log Analytics ingestion/retention |

Numbers vary by region, contracts, traffic, and date. This document therefore
does not quote prices. A production rollout should use each provider's current
pricing calculator and export billing data into a cost model before committing
to a tenant tier or margin.

## 10. Migration and rollout approach

The safest way to become multi-cloud is not to run every provider at once.

1. **Stabilize the GCP reference.** Complete GKE controlled-beta acceptance:
   quota-backed workload pool, identity/backup restore proof, route/DNS/TLS
   verification, failure drills, observability, and cost baselines.
2. **Make provider assumptions explicit.** Keep cloud SDK calls, IAM policy
   templates, registry naming, DNS behavior, and storage settings behind
   documented modules/interfaces.
3. **Add one cloud at a time.** First implement its foundation Terraform,
   identity federation, registry/build path, storage/backup path, ingress/DNS,
   telemetry, and provider acceptance matrix.
4. **Run a non-production compatibility suite.** Deploy the same bounded
   sample graph, exercise candidate failure/promotion/rollback, test isolation
   probes, and perform a restore drill.
5. **Choose tenant isolation tiers.** Do not put customers into shared clusters
   before their risk, compliance, billing, and support requirements are known.
6. **Publish capability truthfully.** A provider is supported only when its
   implementation, runbooks, operational ownership, and recovery evidence are
   complete—not when a diagram maps service names.

## 11. Current boundaries and honest conclusion

Rudder has a strong portable direction: one durable control plane, a
Kubernetes-oriented runtime contract, safe promotion semantics, and a GCP
foundation with least-privilege cloud identities. That gives AWS and Azure a
clear map, but a map is not an implementation.

Today, use GCP as the cloud reference and local Kind/Docker for development and
contract verification. Treat AWS/Azure material in this guide as a detailed
target architecture and checklist for future work. Treat namespace isolation
as a useful baseline, not a substitute for a published hardened multi-tenant
security model. This clarity is intentional: it lets readers understand both
what Rudder can do now and what must be proven before it promises more.
