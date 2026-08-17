# Phases

One file per phase. Each is a build instruction set, not a summary — read the
whole file before starting that phase.

`../PRD.md` remains the source of truth for goal, architecture, data model,
interfaces, decisions, and non-goals. Phase files never redefine those; they
reference them. If a phase file and the PRD disagree, the PRD wins and the phase
file is a bug.

## Order

| Phase | File | Target | Demo |
|---|---|---|---|
| 1 | [PHASE-1-single-host.md](PHASE-1-single-host.md) | 3–4 wk | Push to GitHub, container comes up, public URL serves it |
| 2 | [PHASE-2-multi-host.md](PHASE-2-multi-host.md) | 3–4 wk | Two nodes, service lands on the less loaded one, node dies, service reschedules |
| 3 | [PHASE-3-kubernetes-runtime.md](PHASE-3-kubernetes-runtime.md) | 3–5 wk | Isolated Kubernetes namespace deploys an imported app and rolls back a failed revision |
| 4 | [PHASE-4-gke-production-runtime.md](PHASE-4-gke-production-runtime.md) | 3–5 wk | GKE landing zone: the Phase 3 namespace model runs on a private regional cluster, only the app is publicly routed |
| 5 | [PHASE-5-environments.md](PHASE-5-environments.md) | 2 wk | Clone production to staging, everything rewires |
| 6 | [PHASE-6-operations.md](PHASE-6-operations.md) | 2–3 wk | Volumes, DB templates, logs, metrics, instant rollback |
| 7 | [PHASE-7-frontends.md](PHASE-7-frontends.md) | 1 wk | Vite SPA + Next.js deploy, every push gets a permanent URL |
| 8 | [PHASE-8-advisor.md](PHASE-8-advisor.md) | 1–2 wk | Point at a repo, get a proposed service graph as ghost nodes |
| 9 | [PHASE-9-cli.md](PHASE-9-cli.md) | 2–3 wk | Run every operator workflow from an interactive or scriptable terminal |

Total: 20–29 weeks on the Kubernetes production track.

## Production runtime track

Phase 3 is the Kubernetes runtime, verified locally on Kind: Kubernetes
Services, CoreDNS, namespaces, and NetworkPolicies provide internal discovery
and isolation. Phase 4 carries that same resource contract to a private regional
GKE cluster and adds the production concerns Kind cannot prove — Artifact
Registry, Workload Identity, managed HTTPS edge, durable state, and
infrastructure-as-code.

**WireGuard is cancelled as a Rudder deliverable.** The private service network
is Kubernetes networking. The GKE landing-zone plan is
`PHASE-4-gke-production-runtime.md`. See
[ADR 0004](../decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md)
for the decision and for which `wg_*` data-model fields are now deprecated.

**Do not start a phase until the previous one is verified working end to end.**
"It compiles" and "the happy path worked once" are not verification. Each file
has a `## Verify` section with the actual commands.

## Reordering

Phase 5 is the easiest phase after 1 and has high payoff, and environment
cloning does not need multi-host — it can run any time after Phase 1. Phase 4
can no longer move earlier: it depends on the Phase 3 Kubernetes resource
contract existing and being verified.

Phase 7 depends on D15 (the `Domain` table) landing in Phase 1, and on nothing
else. It can move earlier if frontends become urgent.

Phase 9 is intentionally last: it establishes CLI parity with the complete web
console through Phase 8. Its command surface must not outrun the API or invent
direct runtime mutation paths.

## Structure of each file

Every phase file has the same sections:

- **Demo** — the one sentence you should be able to show at the end
- **Prerequisites** — what must be true before starting
- **Steps** — numbered, each one a proposable unit of work
- **Where this goes wrong** — the failure modes to reason about before writing
- **Verify** — exact commands, not vibes
- **Done when** — the checklist

## Definition of Done (every phase)

- Runs from `docker-compose.dev.yml` with no manual steps beyond documented env
  (one known exception: the Docker `insecure-registries` change, see
  `../NEED-FROM-YOU.md`)
- Tests pass, including at least one concurrency test for anything touching
  scheduling or deploy ordering
- `README.md` updated with what this phase added and how to demo it
- One architecture decision written up in `../decisions/` — what you chose, what
  you rejected, why

## Working agreement reminder

Do not write code until the approach for that step is agreed. Propose files
touched, data model changes, and interfaces first. If a change touches more than
~4 files, stop and propose splitting it.
