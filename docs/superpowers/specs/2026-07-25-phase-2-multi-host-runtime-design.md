# Phase 2 Multi-host Runtime Design

## Goal

Run Rudder's control plane on `rudder-control` and Docker-owning agents on
`rudder-node-a` and `rudder-node-b`; schedule stateless services to a healthy
node, report their observed state, and recover eligible workloads after a node
is lost.

## Scope

This design corrects the current partial Phase 2 implementation before it is
deployed to GCP. It preserves the Phase 1 invariant: the control plane owns
desired state and an agent owns only actual Docker state on its host.

It does not expose Docker, Postgres, registry, or agent ports publicly. It
does not attempt automatic failover of stateful workloads.

## Runtime topology

```text
browser -> web / control-plane on rudder-control
                           |
              private VPC, shared agent secret
                 /                         \
  rudder-node-a agent :9000          rudder-node-b agent :9000
          |                                   |
       Docker                               Docker
```

`rudder-control` hosts the metadata database, control plane, build services,
and UI-facing endpoints. Agents bind port 9000 on their VPC address only.
The VPC allows control-plane-to-agent TCP/9000 and agent-to-control-plane
TCP/8000. Deployment images must be reachable by both agents through a private
registry; a local-only `localhost:5000` registry is not a production runtime.

## Agent contract

At boot, each agent registers `{hostname, cpu_total, memory_total_mb}` with the
control plane and sends a heartbeat every five seconds. A heartbeat contains
observed container IDs, names, raw Docker status, health, image, and IP.

The control plane resolves a selected node to `http://<node.ip_address>:9000`.
Every control-plane-to-agent command carries the shared-secret header. The
production endpoints are the existing agent endpoints:

- `POST /containers`
- `GET /containers/{id}`
- `DELETE /containers/{id}`
- `POST /containers/{id}/health`
- `POST /compose/up`
- `GET /compose/{project}/ps`
- `POST /compose/down`

The reconciler must use those same endpoints and port 9000; it may not use a
parallel `:8001/v1` interface.

## Placement and instance lifecycle

For every deployment, the control plane locks a healthy node row, verifies
available CPU and memory, reserves capacity, and creates an `Instance` record
in the same transaction. Only then does it call that node's agent. On start or
health-check failure, it releases the reservation and marks the deployment
failed without changing the previous live route.

Compose imports are scheduled as one release on one node in Phase 2. The app,
database, cache, and worker containers have individual `Instance` records but
share the selected node and one Compose release lifecycle. The app becomes live
only after its health check passes and every managed Compose container is still
running.

## Reconciliation and failure policy

After 30 seconds without a heartbeat, the control plane marks a node and its
instances `unreachable`. A reconciler runs every 10 seconds and acts only on
fresh observed state. It must be idempotent: a second pass with no state change
sends no commands.

Stateless services with no persistent volume may be rescheduled to another
healthy node. Stateful workloads (database, cache configured with persistence,
or any service with a volume) are marked degraded and require an explicit
operator recovery action. This avoids split-brain data corruption when an
unreachable host is still running.

When a node returns, the control plane compares its reported containers to the
current desired instances. Containers from superseded deployments are drained
and removed; valid current instances are restored to healthy only after a
fresh observation.

## GCP deployment packaging

Create separate production artifacts:

- a control-plane Compose definition for `rudder-control` without source
  mounts, reload mode, public database ports, or local-only registry addresses;
- an agent Compose definition and systemd unit for each node, with Docker socket
  access, an agent state volume, `RUDDER_AGENT_NODE_HOSTNAME`, the private
  control-plane URL, and an agent shared secret obtained from protected host
  environment files;
- a private image registry reachable by both nodes before running source builds.

Secrets remain in protected host files or Secret Manager and are never copied
into Git or image layers.

## Acceptance tests

1. Both GCP agents register and heartbeat with nonzero capacity.
2. A service is placed on the least-loaded healthy node and the UI shows the
   selected node and its instance.
3. Two concurrent placements with capacity for one succeed exactly once.
4. Stopping one agent marks it unreachable after 30 seconds.
5. A stateless service on that node is rescheduled to the survivor within 60
   seconds; a stateful service is visibly degraded and not duplicated.
6. Restoring the agent cleans up obsolete containers and leaves one live
   instance per desired workload.
7. Ten idle minutes produce zero create/delete commands from the reconciler.

## Non-goals

- Public TLS and multi-host ingress.
- Kubernetes orchestration (Phase 2.5).
- Automatic database or persistent-volume failover.
- Running arbitrary untrusted customer repositories in production.
