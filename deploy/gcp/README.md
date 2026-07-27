# Phase 2 GCP runtime

This is a deliberately private, multi-host runtime for the three VMs already
provisioned in `invytt-2483d`:

| Host | Role |
| --- | --- |
| `rudder-control` | control plane, PostgreSQL, BuildKit, internal image registry |
| `rudder-node-a` | node agent and scheduled workload host |
| `rudder-node-b` | node agent and scheduled workload host |

The control plane talks to each agent at its registered private VPC address on
port 9000. Agents heartbeat the control plane on port 8000. The registry is
private on the VPC at port 5000. No workload is given a public URL in this
phase: cross-host ingress is intentionally deferred to the Kubernetes/mesh
phase.

## Required secrets

Create a deployment-only `.env` beside each Compose file. Do not commit it.

```dotenv
POSTGRES_USER=rudder
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=rudder
RUDDER_REGISTRY=<rudder-control-private-ip>:5000
RUDDER_AGENT_SHARED_SECRET=<long-random-secret>
RUDDER_AGENT_CONTROL_PLANE_URL=http://<rudder-control-private-ip>:8000
RUDDER_AGENT_NODE_HOSTNAME=rudder-node-a # change on node-b
RUDDER_AGENT_ADVERTISE_ADDRESS=<this-node-private-ip>
RUDDER_SECRET_KEYS=<existing-fernet-key>
RUDDER_JWT_SECRET=<existing-jwt-secret>
RUDDER_ADMIN_EMAIL=<admin-email>
RUDDER_ADMIN_PASSWORD=<admin-password>
RUDDER_GITHUB_APP_ID=<app-id>
RUDDER_GITHUB_APP_SLUG=<app-slug>
# Optional only when GitHub App repository import is being exercised:
# RUDDER_GITHUB_APP_PRIVATE_KEY_FILE=/opt/rudder/keys/rudder-github-app.pem
RUDDER_GITHUB_OAUTH_CLIENT_ID=<oauth-client-id>
RUDDER_GITHUB_OAUTH_CLIENT_SECRET=<oauth-client-secret>
RUDDER_GITHUB_OAUTH_REDIRECT_URI=<public-control-plane-callback>
```

The GitHub OAuth callback cannot be `localhost` for a real browser flow. Phase
2 verification uses the existing authenticated local flow, or a tunnel with a
matching GitHub OAuth callback. A public production control-plane URL is an
explicit Phase 3 prerequisite.

## Bring-up

1. Configure every worker Docker daemon with the private registry as an
   insecure registry for the lab (`<control-private-ip>:5000`) and restart
   Docker. Add an internal-only VPC firewall rule permitting worker subnet
   traffic to the control VM on TCP 5000; without it workers time out while
   pulling source-built images. Replace this HTTP registry with Artifact
   Registry/TLS before production launch.
2. Copy source, `control-plane.compose.yml` or `agent.compose.yml`, and `.env`
   to `/opt/rudder` on the appropriate VM. Copy the GitHub App PEM only when
   GitHub App repository import is being exercised.
3. On `rudder-control`, run:

   ```sh
   docker compose -f deploy/gcp/control-plane.compose.yml up -d --build
   ```

4. On both workers, run:

   ```sh
   docker compose -f deploy/gcp/agent.compose.yml up -d --build
   ```

5. Tunnel the control plane to the developer machine with IAP for API/UI
   verification. Confirm two healthy nodes via `GET /nodes`.

## Verification target

Deploy one sample image-backed service. The scheduler should pick a healthy
node, its agent creates the container, the node heartbeats it back, and the UI
shows the instance under that node. Stop an agent to confirm the node becomes
unreachable and the instance becomes unreachable. This validates Phase 2's
control loop; it does not claim public traffic failover.
