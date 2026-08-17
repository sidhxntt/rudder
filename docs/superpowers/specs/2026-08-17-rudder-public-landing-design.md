# Rudder public landing page

## Approved direction

**Hybrid control-plane / solo-workbench.** The first viewport proves Rudder's differentiated mechanism: a commit moves through a build into an observable service graph and a live release. Its language remains approachable for a solo developer.

## Audience and action

The audience is solo developers. Primary action: **Deploy from GitHub**. Signed-out visitors begin GitHub OAuth and land in the existing import workflow; signed-in visitors go directly there. Secondary action: **Run locally**, which scrolls to the verified local Docker start.

## Product truth

Local Docker and Kind are available. GKE is a shared-pool controlled beta. AWS/EKS and Azure/AKS are planned adapters only. Comparisons with Vercel and Railway describe operating models, never benchmark, cost, or availability claims.

## Surface structure

1. Public navigation and hero with service-graph proof.
2. Developer workflow from GitHub import through a live release.
3. Product capabilities: topology, logs and analytics, environments and restore, frontends.
4. Runtime posture and restrained comparison table.
5. Copyable local setup and documentation footer.

## Constraints

Preserve the existing dark Rudder identity, use no invented social proof, support reduced motion, and keep authenticated workspace routes protected under `/dashboard`.
