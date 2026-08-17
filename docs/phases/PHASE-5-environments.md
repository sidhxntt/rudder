# Phase 5 — Environments

**Target:** 2 weeks

**Demo:** clone production to staging, everything rewires automatically.

Easiest phase after Phase 1. Ordinary programming — graph copy and reference
resolution. No distributed systems, no kernel networking.

**Can be done before Phase 2** if Phase 2 stalls. Environment cloning does not
need multi-host.

---

## Prerequisites

- [ ] Phase 1 verified
- [ ] Phase 3 verified **if** you want cloned environments to land in their own
      Kubernetes namespace. Clone is pure graph copy and works on the Docker
      runtime too; it just has no namespace isolation there.

`wg_subnet` is **not** a prerequisite. It is a deprecated dead column and clone
must leave it null — see [ADR 0004](../decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md).

---

## Steps

### 1. Variable references

Parse `${{ServiceName.VARIABLE}}`. Resolve at deploy time against services in the
**same environment**. That environment-scoping is what makes cloning work at all
— references rewire themselves for free.

Detect cycles and error clearly. `A → B → A` must fail at save time with a
readable message naming both services, not at deploy time with a stack trace.

Resolution happens at deploy, not at save. A reference to a service that does not
exist yet is legal; it fails at deploy with a clear reason.

### 2. Clone

Copy into a new Environment:

- All Services, including canvas positions
- All Variables, including references (they rewire automatically — see above)
- All Volumes, **empty**. Never copy volume data.
- System Domains, regenerated for the new environment's hostname

On the Kubernetes runtime, the clone gets its own environment namespace with the
same default-deny NetworkPolicy, ResourceQuota, and LimitRange as any other
environment. Allocate no subnet — `wg_subnet` stays null.

Do **not** copy: Deployments, Instances, build logs, metrics. A cloned
environment has no deploy history and nothing running until it's deployed.

The whole clone is one transaction. A half-cloned environment is worse than a
failed clone.

### 3. PR environments

GitHub PR opened → clone the default environment → deploy the PR branch →
comment the URL on the PR.

PR closed or merged → destroy the environment namespace (including its PVCs),
drop its domains, and release its runtime resources.

Needs the GitHub webhook to handle `pull_request` events in addition to `push`.

**Note the distinction from Phase 7 branch previews.** A PR environment is a
full clone with its own database. A branch preview deploys new code against the
*existing* environment's backing services. Different features, both valid. This
step builds the first one.

### 4. UI

Environment switcher. Clone button. Destroy with a confirmation that names what
will be deleted.

---

## Where this goes wrong

**Reference cycles.** Catch at save time, not deploy time. Cycle detection is a
DFS over the reference graph and it is cheap — run it on every variable write.

**Clone is not atomic.** Fifteen services copied, the sixteenth fails, you now
have a half-environment that looks real. One transaction, or a compensating
delete on failure.

**Volume data.** Copying volume data on clone will eventually copy a production
database into staging, where someone will then write to it thinking it's
disposable. Volumes clone as empty. No option, no flag.

**Namespace leaks on destroy.** Destroying an environment must delete its
Kubernetes namespace, its PVCs, and its Ingress/certificate. Miss this and PR
environments silently accumulate quota, disk, and load-balancer cost over months.
Verify the namespace is actually gone, not just marked `Terminating` — a stuck
finalizer keeps the name reserved and the next clone of the same PR fails.

**PR environment cost.** Every open PR is a full copy of production's compute.
Ten open PRs is ten environments. Decide a cap and enforce it with a clear error,
rather than discovering it when the nodes fill up.

**Destroy must be idempotent.** Webhooks are delivered at-least-once. A PR
closed event arriving twice must not error.

---

## Verify

```bash
# 1. Clone production to staging
rudder env clone production staging
rudder service list --env staging
# → same services, no deployments, empty volumes

# 2. References rewired to the new environment
rudder var get api DATABASE_URL --env staging --resolved
# → points at staging's postgres, not production's

# 3. Deploy the clone, confirm isolation
rudder --env staging deploy api --follow
# For a stateful service, inspect the new environment namespace/PVC and its
# database connection. It must be a separately provisioned, empty data store.
# → staging's own empty database; production data remains untouched

# 4. Cycle detection
rudder var set a FOO='${{b.BAR}}'
rudder var set b BAR='${{a.FOO}}'
# → error at the second command, naming both services

# 5. PR lifecycle
#    open a PR → environment appears, URL commented
#    close it   → environment namespace, PVCs, routes and domains are gone
rudder env list

# 6. Destroy is idempotent
#    replay the PR-closed webhook
# → 200, no error
```

---

## Done when

- [x] Clone copies services, variables, canvas positions, empty volumes
- [x] Cloned references resolve within the new environment
- [x] Cloned environments are provably isolated at the data layer
- [x] Cycle detection fires at save time with both service names
- [x] Clone is atomic — a mid-clone failure leaves nothing behind
- [x] PR open creates an environment and comments the URL
- [x] PR close destroys its namespace, PVCs, ingress, domains, and runtime resources
- [x] Replayed webhooks do not error
- [x] `README.md` Phase 5 section
