# Phase 4 GKE operations runbook

Use this runbook for the final Phase 4 operational acceptance drills. Run each
drill in the stated order, record the command output in the Phase 4 checkpoint,
and stop if the live public route becomes unhealthy. Do not use a production
customer namespace as the disposable target.

## Prerequisites and safety boundary

```sh
gcloud auth login
gcloud auth application-default login
gcloud config set project invytt-2483d
gcloud container clusters get-credentials rudder-gke \
  --region asia-south1 --project invytt-2483d
```

Confirm that the cluster and active workload are healthy before any drill:

```sh
kubectl get nodes
kubectl get pods -A
curl --fail --show-error --max-time 20 https://api.rudder.invytt.com/healthz
```

Use an explicit disposable namespace and give every temporary resource the
label `app.kubernetes.io/managed-by=rudder-phase4-drill`. Delete only objects
with that label after recording results. Never force-delete a CNPG production
Pod, delete a production PVC, or drain a node without first checking Pod
placement and PodDisruptionBudgets.

## Point-in-time recovery drill

1. Create a fresh physical backup through Rudder and record its CNPG Backup
   name, completion time, base-backup ID, and GCS path.
2. Create a non-public recovery `Cluster` in a disposable namespace. Give it a
   dedicated Kubernetes ServiceAccount bound only to the backup GSA. Its
   `bootstrap.recovery.source` must point to the existing Barman catalog and
   its `recoveryTarget.targetTime` must be between the selected base backup and
   the latest archived WAL.
3. Verify that the recovery Cluster becomes `Ready`, that PostgreSQL reaches
   the requested timestamp, and that a read-only query returns the expected
   seeded row/version.
4. Delete the recovery Cluster and wait for its PVC to be deleted. Remove the
   temporary NetworkPolicy, ServiceAccount, and Workload Identity binding.

Evidence to record:

```sh
kubectl -n <drill-namespace> get cluster,pod,pvc -o wide
kubectl -n <drill-namespace> logs <recovery-pod> --all-containers=true
gcloud storage ls --recursive gs://invytt-2483d-rudder-backups/<catalog-path>
```

CloudNativePG recovery is not in-place. A recovery Cluster is mandatory; do not
attempt to overwrite the live `postgres` Cluster.

## Broken-candidate continuity drill

1. Select a disposable application environment with an already healthy public
   route and capture its immutable digest and public URL.
2. Submit a candidate that reliably fails its readiness probe (for example, a
   dedicated fixture image that listens on no configured service port). Do not
   mutate the existing live Deployment in place.
3. Poll the existing public URL throughout candidate reconciliation. It must
   remain `200`; the candidate operation must become failed and must not replace
   the Ingress backend.
4. Record the candidate operation ID, Kubernetes events, old and candidate
   digests, and all HTTP samples. Delete only the failed candidate resources.

Example continuity probe:

```sh
while true; do
  date -u +%FT%TZ
  curl --fail --silent --show-error --max-time 10 https://<existing-public-host>/health
  sleep 2
done
```

## Node-resilience drill

1. Choose a platform node that does not host the only replica of a critical
   stateful workload. Confirm PodDisruptionBudget allowance and destination
   capacity before draining.
2. Start the continuity probe for a healthy public application.
3. Cordon and drain one selected node with normal eviction semantics:

```sh
kubectl cordon <node>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --timeout=10m
```

4. Verify eligible Pods reschedule to another Ready node, the public route
   remains continuously healthy, and Rudder's observed state converges.
5. Uncordon the node and wait for the cluster to settle:

```sh
kubectl uncordon <node>
kubectl get pods -A -o wide
```

Abort before drain if it would evict the sole live database/cache replica or if
`disruptionsAllowed` is zero for a required PDB. Record the selected node, Pod
placement before/after, drain output, and HTTP samples.

## Operational response drills

| Drill | Exercise | Evidence |
| --- | --- | --- |
| Failed rollout | broken-candidate drill above | operation status, Pod events, unchanged public URL |
| Backup failure | inspect CNPG Backup status and Barman logs; do not corrupt a live catalog | alert receipt, triage log, successful follow-up backup |
| Secret rotation | rotate a disposable Secret Manager secret, wait for the scoped sync, then verify the affected workload rolls/reloads without exposing the value | secret version, workload event, redacted health check |
| Certificate/DNS | inspect Certificate, Ingress, ExternalDNS ownership, and public TLS chain; rehearse the escalation path without deleting DNS records | certificate status, DNS answer, TLS probe |
| Alert routing | apply the reviewed Terraform Monitoring policies, create a disposable controlled restart/image-pull event, then verify the Cloud Monitoring incident and configured notification channel | policy ID, incident ID, redacted notification receipt, cleanup output |

## Private-endpoint and isolation audit

Run this at every introduction of a new workload type and at least once per
quarter. A customer database, cache, worker, queue, or observability service
must never gain a LoadBalancer, NodePort, or Ingress route as a side effect of
the release.

```sh
kubectl get ingress -A
kubectl get svc -A
kubectl get networkpolicy -A
```

Record the public hosts, all non-ClusterIP service types, default-deny policy
names, and any deliberate egress exception. Stop and remove an unreviewed
public endpoint before considering the release complete.
| Identity compromise | revoke the affected generated Workload Identity member, verify access denial, issue a replacement only for the intended service account, then verify recovery | IAM policy diff and redacted access result |

At minimum, capture control-plane logs, Kubernetes events, CNPG logs, Ingress
status, certificate status, and the public health result for every drill. Route
alerts to the approved on-call destination before calling the alerting gate
complete.

## Post-Phase capacity expansion

The dedicated workloads pool is not required for controlled-beta acceptance. It
requires aggregate `CPUS_ALL_REGIONS` capacity for six more vCPUs. Do not set
`enable_workloads_pool=true` until this preflight passes:

```sh
RUDDER_GCP_PROJECT=invytt-2483d \
RUDDER_GCP_REGION=asia-south1 \
RUDDER_GKE_CLUSTER=rudder-gke \
RUDDER_KUBERNETES_WORKLOAD_POOL=platform \
RUDDER_REQUIRED_GKE_CPUS=18 \
RUDDER_REQUIRED_WORKLOAD_CPUS=6 \
bash infra/gcp/scripts/preflight-gke.sh
```

After quota approval, review the Terraform plan, create the pool, switch the
reviewed runtime setting to `workloads`, and repeat the health and placement
checks before recording this gate complete.
