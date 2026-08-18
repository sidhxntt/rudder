# Documentation Gap Closure Design

## Goal

Make Rudder's consolidated documentation internally consistent, traceable, and
operationally useful without restoring the retired documentation archive.

## Scope

The work closes five identified gaps:

1. Remove stale SDK claims and references to deleted documentation from
   `PRODUCT.md`.
2. Describe the implemented Kubernetes HPA autoscaling path accurately while
   distinguishing it from unsupported platform or node-pool autoscaling claims.
3. Preserve the Phase 4 controlled-beta verification record in one focused
   evidence page linked from the phase narrative and documentation index.
4. Use `environment` and `workload` for current isolation boundaries, reserving
   `tenant` and `multi-tenant` for the explicitly future hardened SaaS design.
5. Add consolidated configuration and GKE operations guides to replace the
   practical information lost when the old setup and runbook documents were
   retired.

## Documentation structure

- `README.md` remains the concise project entry point.
- `PRODUCT.md` describes the current product truth and points only to existing
  evidence.
- `docs/index.md` remains the documentation source-of-truth index.
- `docs/configuration.md` becomes the operator-facing configuration map. It
  groups local, GitHub, CLI, Kubernetes, GKE, backup, and AI settings without
  copying secrets or pretending every variable is required in every runtime.
- `docs/gke-operations.md` becomes the focused GKE preflight, bootstrap,
  verification, capacity, and recovery guide. Commands reference existing
  repository scripts and Terraform rather than inventing a second process.
- `docs/evidence/phase-4-controlled-beta.md` preserves the dated Phase 4
  acceptance boundary, verified drills, quota result, and remaining gates.
- Existing architecture, feature, phase, multi-cloud, technology, and
  conclusion pages receive small consistency edits and links to these focused
  references.
- The Wiki renderer and sidebar publish the three new operator/evidence pages.

## Claim boundaries

Autoscaling means Rudder can persist autoscaling intent and reconcile a
Kubernetes `HorizontalPodAutoscaler` for eligible application workloads. It
does not mean Rudder provisions cluster autoscalers, guarantees spare GKE
capacity, or supports autoscaling on every runtime.

Present-day namespaces isolate environments inside a single-operator product.
They are not represented as a hardened boundary for mutually hostile tenants.
Future AWS, Azure, organization, billing, and hardened multi-tenant designs
remain clearly labelled as planned mappings.

The Phase 4 evidence page records point-in-time controlled-beta evidence. It is
not a general-availability, unlimited-capacity, or multi-tenant production
claim.

## Verification

The finished documentation must satisfy all of the following:

- no current-product SDK claim remains;
- no link or evidence pointer targets a deleted file;
- autoscaling claims agree across the docs and with the Kubernetes HPA code;
- current isolation terminology does not imply implemented SaaS multitenancy;
- every configuration and GKE command points to an existing variable, script,
  Make target, or Terraform path;
- all relative Markdown targets exist;
- the GitHub Wiki renderer includes and successfully renders the new pages;
- searches for the retired paths and known contradictory phrases return no
  unintended matches.

## Non-goals

- Restoring the deleted PRD, ADR, phase-plan, checkpoint, or runbook archive.
- Changing application, CLI, control-plane, Kubernetes, or Terraform behavior.
- Claiming exact cloud spend, six GKE clusters, production multitenancy, AWS,
  or Azure implementation.
