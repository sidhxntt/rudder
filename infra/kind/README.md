# Local Kind runtime

Phase 3's local target is an isolated Kind cluster, not the Docker/Traefik
development runtime.

```bash
make kind-up
make verify-kind
```

The verification creates a temporary Rudder project/environment and its real
persisted GitHub-import graph: public web, private worker, PostgreSQL, and
Redis. It enters through the normal control-plane deployment path, verifies
the ingress at `localhost:8081`, submits a deliberately broken immutable
candidate, confirms the live URL still works, then removes the namespace.

To make the normal development control plane use Kubernetes for real imported
releases:

```bash
make kind-up
make kind-control-plane
```

`kind-control-plane` uses the generated ignored `infra/kind/kubeconfig` and
sets `RUDDER_RUNTIME=kubernetes` plus `RUDDER_REGISTRY=kind-registry:5000`.
That registry alias is visible to both BuildKit and the Kind nodes, so Rudder
keeps one immutable image reference. Return to the Docker runtime with:

```bash
docker compose -f docker-compose.dev.yml up -d --force-recreate control-plane
```
