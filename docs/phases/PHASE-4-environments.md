# Phase 4 — Environments

**Target:** 2 weeks

**Demo:** clone production to staging, everything rewires automatically.

Easiest phase after Phase 1. Ordinary programming — graph copy and reference
resolution. No distributed systems, no kernel networking.

**Can be done before Phase 2** if Phase 2 stalls. Environment cloning does not
need multi-host.

---

## Prerequisites

- [ ] Phase 1 verified
- [ ] Phase 3 verified **if** you want `wg_subnet` allocation on clone. Without
      Phase 3, clone works but leaves `wg_subnet` null.

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

Allocate a new `wg_subnet`.

Do **not** copy: Deployments, Instances, build logs, metrics. A cloned
environment has no deploy history and nothing running until it's deployed.

The whole clone is one transaction. A half-cloned environment is worse than a
failed clone.

### 3. PR environments

GitHub PR opened → clone the default environment → deploy the PR branch →
comment the URL on the PR.

PR closed or merged → destroy the environment, release the subnet, drop the
domains.

Needs the GitHub webhook to handle `pull_request` events in addition to `push`.

**Note the distinction from Phase 5.5 branch previews.** A PR environment is a
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

**Subnet leaks on destroy.** Destroying an environment must release its
`wg_subnet` back to the pool. Miss this and you exhaust the space silently over
months of PR environments.

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
rudder deploy --env staging --all
docker exec <staging-api> psql "$DATABASE_URL" -c '\dt'
# → staging's own empty database

# 4. Cycle detection
rudder var set a FOO='${{b.BAR}}'
rudder var set b BAR='${{a.FOO}}'
# → error at the second command, naming both services

# 5. PR lifecycle
#    open a PR → environment appears, URL commented
#    close it   → environment gone, subnet released
rudder env list

# 6. Destroy is idempotent
#    replay the PR-closed webhook
# → 200, no error
```

---

## Done when

- [ ] Clone copies services, variables, canvas positions, empty volumes
- [ ] Cloned references resolve within the new environment
- [ ] Cloned environments are provably isolated at the data layer
- [ ] Cycle detection fires at save time with both service names
- [ ] Clone is atomic — a mid-clone failure leaves nothing behind
- [ ] PR open creates an environment and comments the URL
- [ ] PR close destroys it and releases the subnet
- [ ] Replayed webhooks do not error
- [ ] `README.md` Phase 4 section
