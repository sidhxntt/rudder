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
| 3 | [PHASE-3-mesh.md](PHASE-3-mesh.md) | 2–3 wk | App reaches Postgres by hostname, DB has no public port |
| 4 | [PHASE-4-environments.md](PHASE-4-environments.md) | 2 wk | Clone production to staging, everything rewires |
| 5 | [PHASE-5-operations.md](PHASE-5-operations.md) | 2–3 wk | Volumes, DB templates, logs, metrics, instant rollback |
| 5.5 | [PHASE-5.5-frontends.md](PHASE-5.5-frontends.md) | 1 wk | Vite SPA + Next.js deploy, every push gets a permanent URL |
| 6 | [PHASE-6-advisor.md](PHASE-6-advisor.md) | 1–2 wk | Point at a repo, get a proposed service graph as ghost nodes |

Total: 14–19 weeks.

**Do not start a phase until the previous one is verified working end to end.**
"It compiles" and "the happy path worked once" are not verification. Each file
has a `## Verify` section with the actual commands.

## Reordering

Phase 4 is the easiest phase after 1 and has high payoff. If Phase 2 stalls —
and Phase 2 is the wall — doing 4 before 2 costs nothing architecturally.
Environment cloning does not need multi-host.

Phase 5.5 depends on D15 (the `Domain` table) landing in Phase 1, and on nothing
else. It can move earlier if frontends become urgent.

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
