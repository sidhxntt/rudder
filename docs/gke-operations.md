# GKE operations

This guide covers the implemented single-cluster, attach-mode GKE reference.
Terraform owns the cloud foundation; Rudder owns environment namespaces and
workloads after attachment. Normal Rudder requests never create, resize,
upgrade, or delete the cluster or its node pools.

## Safety boundary

- Use a dedicated GCP project or an explicitly reviewed shared project.
- Use an operator identity with only the permissions required by Terraform and
  the bootstrap scripts.
- Keep runtime, build, backup, DNS, certificate, and secret-sync identities
  separate.
- Review `terraform plan` before applying cloud changes.
- Never bypass the quota gate by weakening workload requests, isolation, or
  placement rules.

The recorded controlled-beta environment used one regional cluster and shared
tainted platform capacity. Read the
[Phase 4 evidence record](evidence/phase-4-controlled-beta.md) before making a
production claim.

## Required operator inputs

Start from [the configuration guide](configuration.md). The GKE scripts fail
early when required `RUDDER_*` inputs are missing. In addition to GCP project,
region, cluster, registry, build, domain, and certificate values, bootstrap
requires the runtime, backup, backup-broker, secret-sync, and cert-manager
Google service accounts; an immutable control-plane image digest; and a Secret
Manager secret name.

Authenticate Application Default Credentials and configure the expected GCP
project before running Terraform or GKE scripts. Do not store credentials or
secret values in Terraform variables.

## 1. Provision or review the foundation

Terraform lives in `infra/gcp/terraform`. Initialize it with the reviewed state
backend, then inspect the proposed changes:

```bash
terraform -chdir=infra/gcp/terraform init
terraform -chdir=infra/gcp/terraform fmt -check
terraform -chdir=infra/gcp/terraform validate
terraform -chdir=infra/gcp/terraform plan
```

Apply only a reviewed plan. Rudder's attach mode assumes the cluster and cloud
foundation already exist.

## 2. Run the read-only preflight

```bash
make gke-preflight
```

The preflight checks credentials, cluster health, Workload Identity shape,
expected workload-pool selection, and project-wide CPU quota. It is deliberately
read-only. A regional three-zone `e2-standard-2` pool requires six vCPUs; the
recorded project was already 12 used of 12, so the dedicated workloads pool
remained disabled.

## 3. Configure kubectl

```bash
bash infra/gcp/scripts/configure-kubectl.sh
```

Confirm the generated context names the intended project, region, and cluster
before applying anything. Do not rely on whichever kubectl context happened to
be active previously.

## 4. Bootstrap or reconcile platform components

```bash
make gke-bootstrap
```

The bootstrap script validates its inputs and installs/reconciles pinned
ingress-nginx, cert-manager, External Secrets, ExternalDNS, CloudNativePG,
backup-broker, migration, and control-plane resources. It does not provision
the GKE cluster.

## 5. Verify the platform contract

```bash
make gke-verify
```

Verification is read-only and checks the shared platform contract. A complete
release acceptance additionally exercises GitHub delivery, immutable image
publication, workload readiness, HTTPS, failed-candidate continuity, rollback,
isolation, and backup restore as described in the evidence record.

## Capacity expansion

Do not enable a dedicated workloads pool until `CPUS_ALL_REGIONS` provides at
least 18 total vCPUs; 24 is the documented recommendation for headroom. After
enabling it through reviewed Terraform:

1. select the workloads pool through configuration;
2. rerun preflight, bootstrap, and platform verification;
3. repeat workload placement and readiness checks;
4. repeat HTTPS promotion and failed-candidate continuity;
5. repeat backup, restore, and point-in-time recovery;
6. repeat namespace isolation and workload-identity checks.

## Failure and recovery rules

- A failed candidate must leave the existing healthy route intact.
- DNS, certificate, image, migration, secret-sync, and database readiness
  failures must fail closed rather than report a live release.
- Backups require periodic restore and point-in-time recovery drills.
- Namespace deletion remains time-bounded and retryable while Kubernetes
  finalizers or resources still exist.
- Node drain must respect CloudNativePG and PodDisruptionBudget behavior.
- Alert policies are not an alerting service until notification channels are
  configured and exercised.
- Destructive cluster or node-pool changes remain explicit Terraform/operator
  work outside the Rudder API.

## Cost controls

Track node-pool minimums, load balancer/public IP, NAT and egress, Artifact
Registry, Cloud Build, GCS backup/WAL retention, PVCs, DNS, and logging/metrics
ingestion. Rudder does not implement tenant billing or measured shared-cost
allocation. The shared-pool controlled-beta compromise is a documented
capacity decision, not evidence of hardened multi-tenancy.
