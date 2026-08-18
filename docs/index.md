# Rudder documentation

Welcome. This is the guided entry point for Rudder: a self-hosted deployment
control plane with a Railway-style canvas, a terminal peer, GitHub-driven
delivery, and a Kubernetes-oriented runtime model.

The documentation is deliberately candid about evidence:

- **Implemented**: source/configuration is present in this repository.
- **Verified**: a test, evidence record, or documented acceptance run supports the
  claim. Read the cited verification rather than treating the label as a blanket
  production guarantee.
- **Planned / mapped**: a future design, including AWS/Azure provider mapping;
  it is not an existing deployment.

## GitHub Wiki publication

The published [Rudder GitHub Wiki](https://github.com/sidhxntt/rudder/wiki)
is generated from this repository documentation. These Markdown files remain
the source of truth; follow [the Wiki publishing guide](wiki-publishing.md) to
render and push updates without maintaining a second hand-edited copy.

## Start here: no prior Rudder knowledge required

1. [Overview](overview.md) — what Rudder is, the problem it addresses, its
   concepts, and the vocabulary used everywhere else.
2. [Architecture](architecture.md) — desired state, runtime adapters, source
   to release flow, security boundaries, and GCP topology.
3. [Features](features.md) — manual/automatic deployment, Railway-style UI,
   Vercel-style release URLs, CLI, Advisor, Ask Rudder, and observability.
4. [Technology stack](tech-stack.md) — what each component does and why it was
   selected.
5. [Configuration](configuration.md) — local, GitHub, runtime, GKE, backup,
   CLI, and optional AI settings.
6. [GKE operations](gke-operations.md) — preflight, provisioning boundary,
   bootstrap, verification, capacity, and recovery.
7. [Conclusion](conclusion.md) — the overall narrative, evidence boundary, and
   current product limits.

## Project framing and setup

| Document | Use it for |
|---|---|
| Project overview | Canonical goal, data model, interfaces, non-goals, and original acceptance decisions, consolidated in this documentation set. |
| [Configuration](configuration.md) | Local, GitHub, Advisor/OpenAI, Kind, GKE, backup, and CLI settings. |
| [GKE operations](gke-operations.md) | GCP landing-zone preflight, Terraform boundary, bootstrap, verification, capacity, and recovery. |
| [Phase 4 evidence](evidence/phase-4-controlled-beta.md) | Dated controlled-beta acceptance evidence and remaining gates. |
| [Multi-cloud mapping](multi-cloud.md) | GCP-as-reference mapping to AWS/Azure; explicitly planned, not provisioned adapters. |
| Architecture decisions | Why key alternatives such as WireGuard and direct cluster ownership were rejected; see the Phase 2–4 narratives. |
| Operational handoff | GKE operational context is consolidated in the Phase 4 and multi-cloud narratives. |

## Phases: how the platform was built

The project was intentionally divided into demoable increments. Start with the
phase sequence below, then follow the detailed narrative below.
Each phase document covers its plan, implementation design, infrastructure and
cost implications, challenges, remedies, verification evidence, and remaining
limits.

| Phase | Topic | Detailed document |
|---:|---|---|
| 0 | Baseline and project contract | [Phase 0](phases/phase-0.md) |
| 1 | Single-host deployment | [Phase 1](phases/phase-1.md) |
| 2 | Multi-host Docker runtime | [Phase 2](phases/phase-2.md) |
| 3 | Kubernetes runtime on Kind | [Phase 3](phases/phase-3.md) |
| 4 | GKE production landing zone | [Phase 4](phases/phase-4.md) |
| 5 | Environments and PR previews | [Phase 5](phases/phase-5.md) |
| 6 | Operations and observability | [Phase 6](phases/phase-6.md) |
| 7 | Frontends and permanent releases | [Phase 7](phases/phase-7.md) |
| 8 | Advisor and read-only AI assistance | [Phase 8](phases/phase-8.md) |
| 9 | Operator CLI parity | [Phase 9](phases/phase-9.md) |

### Evidence and verification

Each detailed phase narrative records its relevant tests, evidence, live
acceptance evidence, and operational limitations. Treat those records as
point-in-time evidence rather than a blanket production guarantee.

## Operational references

- [Phase 3 Kubernetes runtime](phases/phase-3.md)
- [Phase 4 GKE landing zone](phases/phase-4.md)
- [GKE operations](gke-operations.md)
- [Phase 4 controlled-beta evidence](evidence/phase-4-controlled-beta.md)
- [Phase 6 operations](phases/phase-6.md)

## Finding a specific capability

| If you want to understand… | Read… |
|---|---|
| GitHub import, OAuth, webhooks, and preview environments | [Features](features.md) and [Phase 5](phases/phase-5.md) |
| Why the CLI is not a second control plane | [Phase 9](phases/phase-9.md) and [architecture](architecture.md) |
| AI summary, Advisor, build diagnosis, or Ask Rudder | [Phase 8](phases/phase-8.md) and [features](features.md) |
| Stable versus deployment-pinned URLs | [Phase 7](phases/phase-7.md) |
| Logs, metrics, rollback, backups, and stateful workloads | [Phase 6](phases/phase-6.md) |
| Kubernetes isolation, GKE, Workload Identity, and CloudNativePG | [Phase 3](phases/phase-3.md), [Phase 4](phases/phase-4.md), and [multi-cloud mapping](multi-cloud.md) |
| Runtime, GitHub, backup, CLI, and AI configuration | [Configuration](configuration.md) |
| GKE preflight, bootstrap, verification, capacity, and recovery | [GKE operations](gke-operations.md) and [Phase 4 evidence](evidence/phase-4-controlled-beta.md) |
| What transfers to AWS or Azure | [Multi-cloud mapping](multi-cloud.md) |

## Documentation maintenance rule

When changing behavior, update the relevant phase document and this index if
navigation changes. Never turn a future design into a present-tense guarantee:
mark what is implemented, what has live evidence, and what is an intended next
step separately.
