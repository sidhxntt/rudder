# Rudder Control Plane Redesign

## Purpose

Refresh both the public landing page and authenticated deployment workspace so they match the information hierarchy, calm interaction patterns, and product clarity associated with modern developer platforms, while preserving Rudder's dark, emerald operator identity.

## Audience and outcome

Solo developers should understand within the first landing viewport that Rudder turns a GitHub repository or Compose graph into an observable deployment system. In the workspace, they should be able to locate a project, choose an environment, understand service health, and act on the selected service without searching through competing UI layers.

## Direction: Rudder Control Plane

Rudder keeps its near-black canvas, graphite panels, mono operational detail, and emerald action/live-state accent. Supabase is a benchmark for hierarchy and restraint only: it is not a source for copy, color, brand assets, or cloned components. Rudder's distinctive proof remains its directional service topology, release information, logs, and recoverable deployments.

## Public landing page

- Preserve the existing factual positioning, local Docker/Kind capability, controlled-beta GKE status, and planned AWS/Azure labels.
- Tighten the global navigation into brand, concise product navigation, a single GitHub sign-in action, and an authenticated route into the workspace.
- Recompose the hero around one thesis, one primary action, one restrained secondary action, and a large service-topology proof.
- Replace repetitive card-group presentation with alternating evidence sections: deploy path, private-dependency topology, release/rollback visibility, and environment targets.
- Keep the current "In development" badge explicit and restrained.
- Add accessible hover/focus, reduced-motion behavior, and purposeful responsive stacking without changing claims or API behavior.

## Authenticated workspace

- Establish a three-layer shell: global workspace navigation, project/environment context, then a route-local action surface.
- Make the sidebar easier to scan with a compact workspace switcher, predictable project ordering, a clear selected environment, and a stable user/profile area.
- Make the top bar contextual: breadcrumbs, environment status, a primary deployment action only when relevant, and a back-to-workspace control where appropriate.
- Preserve the canvas as the main operational view. Improve its visual hierarchy through a quieter coordinate field, legible directional edges, service-type tags, and selected-service emphasis; do not replace it with a generic dashboard grid.
- Standardize service detail-panel tabs as consistent work surfaces: Build logs, Variables, Deploys, Operations, Analytics, and Service settings.
- Improve task states: first import, loading, empty projects, failed deploys, and unavailable services must explain what happened and expose the next valid action.

## Component and interaction rules

- Emerald is reserved for the primary action, healthy/live state, selected release path, and keyboard focus; failure and build states retain semantic red/yellow.
- Controls, inputs, checkboxes, tabs, and menus use the shared UI primitives already being introduced in `web/components/ui`.
- No UI element gains a decorative graph; resource trends live only in Analytics and use different chart types for time series, allocation/distribution, and release outcomes.
- Rename actions remain explicit double-click interactions with keyboard-accessible alternatives in the relevant settings surface.
- Rollback continues to point a deployment to an immutable previously recorded release; UI copy must not claim a rollback has succeeded until the backend reports its deployment state.

## Architecture boundaries

- `web/app/landing-page.tsx` owns public persuasion and sign-in/deploy calls to action.
- `web/app/workspace-page.tsx`, `sidebar.tsx`, and `top-bar.tsx` own workspace navigation and context.
- Environment route components own canvas, detail panel, and their focused tabs. Shared primitives in `web/components/ui` should absorb repeated control styling but not business state.
- Existing API and deployment semantics remain unchanged unless a UI state exposes a demonstrated contract bug; such a bug gets its own focused task and backend test.

## Acceptance criteria

1. The landing page visibly remains Rudder: dark operator surfaces, factual local/GKE positioning, and a service-graph proof; GitHub is the clear sign-in action.
2. A signed-in user can navigate between dashboard, project/environment, selected service, and profile controls without ambiguous or duplicated controls.
3. The service canvas, detail panel, logs, variables, deploy history, operations, analytics, and service settings remain functional and become more scannable at desktop and mobile widths.
4. All changed controls are keyboard reachable, have visible focus, and preserve semantic labels.
5. Focused frontend tests pass, TypeScript passes, and backend tests only change where behavior genuinely changed.
6. The result is visually inspected in desktop and mobile layouts before handoff; no copy, screenshots, or claims are taken from Supabase.

## Out of scope

- A new deployment backend, billing, provider support, or a claim that AWS/Azure are available.
- A wholesale rewrite of the React application, React Flow topology engine, authentication, or persistence model.
- Copying Supabase visual assets, source, product claims, screenshots, or proprietary interface details.
