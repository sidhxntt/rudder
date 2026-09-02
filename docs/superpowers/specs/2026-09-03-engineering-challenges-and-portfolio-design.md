# Rudder Engineering Challenges and Portfolio Design

## Goal

Turn Rudder's scattered phase retrospectives into a beginner-friendly engineering
narrative, then use that verified narrative to add Rudder to Siddhant's portfolio.
The result must explain what was difficult, why it was difficult, how it was
solved, how the solution was verified, and which boundaries remain deliberate.

## Documentation structure

Create `docs/engineering-challenges.md` as the consolidated narrative. Follow
the useful shape of NotchFlow's engineering-challenges page without copying its
content:

1. define unfamiliar platform terms in plain language;
2. organize the story by Rudder's Phases 0–9;
3. give every phase a user/operator-facing problem, underlying technical cause,
   implemented treatment, verification evidence, and remaining boundary;
4. end with cross-phase lessons and direct links to relevant code and deeper
   phase documentation.

The page will cover the following through-line:

- Phase 0: preventing accidental architecture before implementation;
- Phase 1: deployment races, health-gated promotion, durable logs, and cleanup;
- Phase 2: delayed heartbeats, generation fencing, placement, and split-brain
  avoidance across Docker nodes;
- Phase 3: translating service intent to Kubernetes while protecting private and
  stateful workloads;
- Phase 4: production-reference GKE identity, DNS/TLS, backup, failure drills,
  quota, and cost constraints;
- Phase 5: transactional environment cloning, idempotent PR webhooks, preview
  cleanup, and capacity limits;
- Phase 6: truthful operations, bounded telemetry, immutable rollback, and safe
  stateful teardown;
- Phase 7: frontend detection, immutable releases, fresh entry documents,
  permanent release URLs, and their DNS/certificate cost;
- Phase 8: proposal-only and read-only AI surfaces with redacted context;
- Phase 9: CLI parity, browser-mediated authentication, stable output contracts,
  and secret-safe terminal behavior.

## GitHub integration boundaries

The consolidated page and supporting stack/configuration documents will make
three separate responsibilities explicit:

- **GitHub OAuth** authenticates a human. Web login and the CLI's browser handoff
  resolve a Rudder user from GitHub's immutable identity; OAuth is not the
  repository-deployment credential.
- **GitHub App installations** authorize selected repository access. Short-lived
  installation tokens support discovery, exact-source checkout, and PR comments;
  independently HMAC-verified webhooks drive push and pull-request lifecycle
  events.
- **GitHub Packages** distributes the scoped npm CLI package. It is not Rudder's
  application-image registry. Local development may use a local registry, while
  the GCP reference publishes deployment images to Artifact Registry.

These distinctions will also be added where readers configure or learn the
stack, rather than existing only in the CLI README.

## Navigation and publication

Add the new page to:

- `docs/index.md`;
- `docs/_Sidebar.md`;
- `docs/wiki-publishing.md` and its publication page map;
- the root README documentation list.

The generated/public Wiki convention will remain source-driven: repository docs
are edited first and the existing publishing workflow renders the Wiki target.

## Portfolio entry

Add Rudder to both portfolio content sources:

- `input/04-projects.json`;
- `src/data/portfolio.ts`.

The card will position Rudder as a self-hosted deployment control plane with a
visual canvas and CLI. It may describe implemented GitHub import/deployment,
immutable releases, health-gated promotion, preview environments, rollback,
logs/metrics, and the controlled GKE reference. It must explicitly avoid
claiming hosted multi-tenancy, six GKE clusters, or completed AWS/Azure support.

Use the repository URL as the primary link and an authentic Rudder UI screenshot
as the preview. If no suitable checked-in screenshot exists, capture the local
web UI rather than inventing product artwork.

## Verification

- Cross-check every challenge against phase docs, implementation, tests, or the
  controlled-beta evidence record.
- Validate documentation links and Wiki page-map entries.
- Parse the portfolio JSON and confirm the TypeScript project shape.
- Run Rudder's documentation checks, relevant test suites, and the portfolio's
  tests/typecheck/build.
- Preserve all pre-existing uncommitted portfolio changes.

## Non-goals

- Do not present planned multi-tenancy or multi-cloud mappings as implemented.
- Do not rewrite the existing phase retrospectives.
- Do not weaken security or operational caveats to make the portfolio copy more
  impressive.
- Do not add a new portfolio component or layout; use the existing project-card
  pipeline.
