# Phase 5 — Operations

**Target:** 2–3 weeks

**Demo:** a Postgres with a real volume that survives redeploy, live log tailing,
CPU sparklines on the canvas, and one-click rollback.

This is the phase that makes it usable day to day rather than just demoable.

---

## Prerequisites

- [ ] Phase 2 verified (volumes need the scheduler)
- [ ] Phase 3 verified (database templates need the mesh)
- [ ] D15 landed in Phase 1 — rollback depends on the `Domain` table

---

## Steps

### 1. Volumes

Docker named volumes, created on the pinned node.

- The scheduler **must** respect the pin. A service with a volume can only ever
  be placed on `Volume.node_id`.
- If that node is unreachable, the service does **not** reschedule. It stays
  down and reports why. Rescheduling a volume-backed service elsewhere means
  running without its data — worse than being down.
- **Refuse to scale a volume-backed service past 1 replica.** Clear error, not a
  silent cap and not a silent success.

Deleting a service with a volume requires explicit confirmation and does not
delete the volume by default.

### 2. Database templates

Postgres, Redis, MySQL as one-click services.

Each template supplies: image, default env, a volume, generated credentials, and
the variables it exposes for other services to reference.

Credentials are generated at create time and stored encrypted like any other
Variable. Never a default password, never a fixed one.

`kind=database`, so per Phase 3 they get no Domain and no Traefik router.

### 3. Logs

Agent streams container logs to the control plane. Stored to disk with rotation.
UI tails via SSE.

This is a volume problem, not a logic problem. Decide up front:

- Rotation policy — size or age, and the cap per service
- Backpressure — what happens when a service logs 10MB/s. Drop, or slow the
  reader. Dropping is correct; say so in the UI.
- Retention — how long before deletion

Log storage on the control plane's local disk. Do not add object storage.

### 4. Metrics

Agent reports per-container CPU and memory every 10s.

Store downsampled: full resolution for 1h, 1-minute buckets for 24h, 5-minute
for 7d. Discard beyond that.

Sparklines on canvas nodes.

Do not add Prometheus. A table and a downsampling job is the whole feature at
this scale.

### 5. Rollback — depends on D15

**Repoint the Service's system Domain at a previous Deployment.**

No rebuild. No restart of anything already running. An UPDATE plus a Traefik
config write. Sub-second.

This works because Deployments are immutable and `image_tag` is never reused or
deleted (see `../PRD.md` → "Data Model").

Edge case: rolling back to a Deployment whose Instances are already stopped means
starting containers from that image first, then repointing. Rolling back to one
still running is instant.

UI: deploy history list, each entry with a rollback button.

---

## Where this goes wrong

**Volume pin vs reschedule.** The scheduler's default instinct — "node down,
move it" — is exactly wrong for volume-backed services. This is a hard constraint
in the placement filter, and it needs a test that kills a node hosting a volume
and asserts the service does *not* move.

**Log backpressure.** A service in a crash loop can produce logs faster than they
can be written. Unbounded buffering takes down the control plane. Bound the
buffer, drop, and surface the drop.

**Metrics table growth.** 10s resolution × N containers × forever fills the disk.
The downsampling job is not optional and needs to be verified running, not just
written.

**Rollback to a deleted image.** If registry garbage collection ever runs, old
image tags vanish and rollback breaks silently. Either never GC, or make rollback
check tag existence and fail with a clear message.

**Credential generation in templates.** Generated once at create. Redeploying
must not regenerate — that would break every service holding a reference.

---

## Verify

```bash
# 1. Volume survives redeploy
rudder service create db --template postgres
psql -c 'create table t(x int); insert into t values (1);'
rudder deploy db
psql -c 'select * from t'         # → row still there

# 2. Volume pins placement
rudder instance list db              # note the node
docker stop rudder-agent             # on that node
watch rudder service status db
# → reports unavailable, pinned to a down node. Does NOT move.

# 3. Scaling a volume-backed service is refused
rudder service scale db --replicas 2
# → clear error, exit nonzero

# 4. Log tail
rudder logs api -f
# → live output, survives a container restart

# 5. Log backpressure
#    deploy a service that logs in a tight loop
# → control plane stays up, drop is reported

# 6. Metrics downsampling
#    let it run 2h, check row counts per resolution tier

# 7. Instant rollback
time rudder rollback api --to <previous-deployment-id>
# → sub-second, no build, no restart of running containers
curl <url>                         # → serving the old version
```

---

## Done when

- [ ] Volume data survives redeploy
- [ ] Volume-backed services do not reschedule off a dead node
- [ ] Scaling a volume-backed service past 1 replica errors clearly
- [ ] Postgres, Redis, MySQL deploy from templates with generated credentials
- [ ] Redeploy does not regenerate credentials
- [ ] Live log tail works and survives restarts
- [ ] A log flood does not take down the control plane
- [ ] Metrics downsample and the table does not grow unbounded
- [ ] Rollback is sub-second and does not rebuild
- [ ] `README.md` Phase 5 section
