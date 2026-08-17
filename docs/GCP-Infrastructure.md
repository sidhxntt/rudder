# GCP Infrastructure for Phase 2

This document outlines the Google Cloud Platform (GCP) infrastructure set up for Phase 2 of the project, including virtual machines, network configurations, and firewall rules.

## Project Details

*   **Project ID:** `invytt-2483d`
*   **GCP Console Link:** [Project Dashboard](https://console.cloud.google.com/home/dashboard?project=invytt-2483d)

## Network Configuration

*   **VPC Network Name:** `rudder-vpc`
*   **Subnet Name:** `rudder-subnet`
*   **Subnet IP Range:** `10.42.0.0/20`
*   **Region:** `asia-south1`
*   **Zone:** `asia-south1-a`
*   **GCP Console Link (VPC Networks):** [VPC Networks](https://console.cloud.google.com/networking/vpc/list?project=invytt-2483d)

## Virtual Machines (VMs)

The following Compute Engine instances have been created:

### rudder-control

*   **Name:** `rudder-control`
*   **Machine Type:** `e2-standard-2`
*   **Boot Disk Size:** `40GB`
*   **Internal IP:** `10.42.0.2`
*   **External IP:** `34.14.195.107`
*   **Tags:** `rudder-control`, `rudder-admin`
*   **Docker Installed:** Yes

### rudder-node-a

*   **Name:** `rudder-node-a`
*   **Machine Type:** `e2-standard-2`
*   **Boot Disk Size:** `50GB`
*   **Internal IP:** `10.42.0.4`
*   **External IP:** `34.47.217.191`
*   **Tags:** `rudder-node`, `rudder-admin`
*   **Docker Installed:** Yes

### rudder-node-b

*   **Name:** `rudder-node-b`
*   **Machine Type:** `e2-standard-2`
*   **Boot Disk Size:** `50GB`
*   **Internal IP:** `10.42.0.3`
*   **External IP:** `8.231.75.210`
*   **Tags:** `rudder-node`, `rudder-admin`
*   **Docker Installed:** Yes

*   **GCP Console Link (VM Instances):** [VM Instances](https://console.cloud.google.com/compute/instances?project=invytt-2483d)

## Firewall Rules

The following firewall rules have been configured for the `rudder-vpc` network:

*   **rudder-control-to-agent**
    *   **Description:** Allows TCP traffic on port `9000` from instances tagged `rudder-control` to instances tagged `rudder-node`.
*   **rudder-agent-to-control**
    *   **Description:** Allows TCP traffic on port `8000` from instances tagged `rudder-node` to instances tagged `rudder-control`.
*   **allow-ssh**
    *   **Description:** Allows TCP traffic on port `22` (SSH) from all IP addresses (`0.0.0.0/0`) to instances tagged `rudder-admin`.

*   **GCP Console Link (Firewall Rules):** [Firewall Rules](https://console.cloud.google.com/networking/firewalls/list?project=invytt-2483d)

## Next Steps

The next phase involves building the application code for node registration, heartbeat, scheduler, and reconciler, which will utilize this infrastructure.

## Phase 4: GKE production foundation

The Phase 2 VM lab above is historical and has been decommissioned. Phase 4
uses a separate, regional GKE Standard foundation rather than reusing the VM
network. Terraform in `infra/gcp/terraform` owns the cloud resources; Rudder
attaches to Kubernetes from its `rudder-system` namespace using Workload
Identity.

The operator workflow is intentionally split:

1. Before enabling the `workloads` node pool, run
   `infra/gcp/scripts/preflight-gke.sh`. It is read-only and verifies the live
   cluster is running, Workload Identity is configured, Terraform Application
   Default Credentials are valid, and project-wide `CPUS_ALL_REGIONS` has at
   least 18 total and six available vCPUs. GKE evaluates this aggregate quota
   when admitting a regional node pool; the regional `CPUS` display alone is
   not sufficient. It exits non-zero with the exact credential or
   quota shortfall; it never changes GCP. If it reports invalid ADC, run
   `gcloud auth application-default login` and complete the browser flow.
2. Apply Terraform to create the VPC, private-node regional cluster, Artifact
   Registry, backup bucket, and least-privilege Google service accounts.
3. Run `infra/gcp/scripts/configure-kubectl.sh` to obtain an operator context
   through the cluster DNS endpoint.
4. Run `infra/gcp/scripts/bootstrap-platform.sh` with reviewed image digests,
   pinned Helm chart versions, `RUDDER_CONTROL_PLANE_HOST`,
   `RUDDER_KUBERNETES_CERTIFICATE_ISSUER`, `RUDDER_ACME_EMAIL`,
   `RUDDER_DNS_NAME`, and pinned chart versions. It installs ingress-nginx,
   cert-manager, External Secrets Operator, ExternalDNS, CloudNativePG, a
   Workload-Identity-backed Cloud DNS ACME issuer, and the Rudder control plane.
   ExternalDNS is restricted to the delegated Rudder zone and Ingresses marked
   `app.kubernetes.io/managed-by=rudder`; it owns only its TXT-marked records.
5. Run `infra/gcp/scripts/verify-gke.sh` for read-only acceptance checks.

Before enabling the `workloads` node pool, the project must have sufficient
`CPUS_ALL_REGIONS` quota: a regional three-zone `e2-standard-2` pool consumes
six vCPUs. The currently observed project quota is 12/12 vCPUs consumed by the
system/platform baseline. A request for 24 was submitted on 2026-07-30 and was
not granted, so do not enable the pool until Google grants at least 18. The
normal control-plane identity intentionally cannot delete
PersistentVolumeClaims; state destruction requires an explicit, audited
break-glass role binding outside Rudder.

### Live GKE baseline verification — 2026-07-30

The imported `system` node pool was initially tainted
`rudder.pool=system:NoSchedule`. That prevented GKE-managed Pods such as
CoreDNS from scheduling even though the nodes reported Ready. Terraform removed
the taint in place; it did not destroy a pool or node. The system nodes are now
untainted, both CoreDNS replicas are Running, and the Terraform plan is
converged. The `platform` pool remains tainted and is reserved for Rudder's
control-plane and ingress workloads, whose manifests include the matching
toleration. This is a cluster-health repair, not completion of the public
platform or customer-workload acceptance path.

### Backup identity gate

The Terraform backup bucket and `rudder-backup` Google service account are
foundation resources, not permission to put storage keys in workloads. The
legacy `RUDDER_KUBERNETES_BACKUP_S3_*` settings are local Kind/MinIO-only and
the control plane rejects them for `RUDDER_KUBERNETES_TARGET=gke`.

Rudder now has a GKE-native CNPG manifest contract: when enabled it renders
`googleCredentials.gkeEnvironment: true` and a `serviceAccountTemplate` that
annotates the dedicated Google service account. It never creates a credential
Secret for this path. That contract is intentionally disabled until a separately
authorised broker creates and verifies the exact per-environment Kubernetes
ServiceAccount-to-Google-Service-Account Workload Identity binding.

After that verification, configure all three values below in the control-plane
runtime; `IDENTITY_READY` is an operator attestation, not a substitute for the
binding or restore proof:

```sh
RUDDER_KUBERNETES_BACKUP_GCS_BUCKET=<approved-gcs-bucket>
RUDDER_KUBERNETES_BACKUP_GCP_SERVICE_ACCOUNT=rudder-backup@<project>.iam.gserviceaccount.com
RUDDER_KUBERNETES_BACKUP_GCS_IDENTITY_READY=true
```

Until the final flag is true, Rudder does not render the CNPG backup block and
does not expose backup controls. The broker must not use a node identity, an
all-cluster/namespace grant, HMAC key, or service-account JSON file. The gate
closes only after an actual disposable restore drill.
