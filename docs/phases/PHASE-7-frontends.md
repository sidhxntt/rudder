# Phase 7 — Frontends

**Target:** deploy static frontends and server-rendered web apps through the
same immutable-release platform that already serves APIs.

**Outcome:** a Vite SPA, static Next export, or CRA project is detected and
served from a small nginx image; a Next SSR project stays a normal app
container. Every successful release receives a permanent, deployment-pinned
URL. The existing service URL remains the promoted alias and rollback remains
an instant route change.

## Current baseline

Phase 6 already provides the parts this phase must reuse, not replace:

- `ServiceKind.STATIC` exists in the API and dashboard.
- every release has an immutable image and existing releases remain healthy for
  rollback;
- `Domain(target_type=deployment)` already routes to a specific immutable
  release, while a system domain follows the live release;
- the dashboard already has a deploy history and restore control;
- Phase 5 owns isolated PR environments. They remain the way to preview a
  full stack including cloned backing services.

The gaps are frontend-aware detection/building, automatic permanent release
URLs, and visibility of those URLs in the dashboard. Phase 7 deliberately does
not create a competing PR-environment lifecycle.

## Execution plan

1. **Detect frontend frameworks.** Preserve Dockerfile precedence. For a
   Node repository without a Dockerfile, inspect package dependencies and
   framework config to classify Vite, Next SSR/export, Astro static, or CRA.
   A static classification carries its output directory and SPA-fallback rule;
   all unknown Node projects retain the existing server template.
2. **Build static assets correctly.** Render a dedicated multi-stage
   Dockerfile: install dependencies, run the package-manager build command,
   copy only the detected output directory into non-root nginx, and serve it on
   the existing service port. Nginx returns the SPA shell for client routes only
   when the preset says it should; `index.html` is not cached and fingerprinted
   assets are immutable.
3. **Create permanent deployment URLs.** Once a release is healthy and is
   about to be routed, atomically create one user domain of the form
   `d-<deployment-id-prefix>.<base-domain>` targeting that deployment. It is
   never repointed or garbage-collected independently of the deployment. The
   normal system domain remains the promoted/live alias.
4. **Expose release URLs.** Add the permanent URL to the existing deploy
   history. “Restore” remains the promote/rollback action: it moves only the
   system domain to a prior healthy deployment and does not modify permanent
   URLs or rebuild an image.
5. **Protect build-time configuration.** Static presets accept build args only
   from `Service.build_config.build_env`, and only public keys appropriate to
   the preset (`VITE_*`, `NEXT_PUBLIC_*`, `PUBLIC_*`, or `REACT_APP_*`). Values
   are passed as Docker build args, never rendered into build logs or runtime
   environment. A later variable update requires a new deployment.
6. **Verify the actual delivery path.** Unit-test detection, templates,
   build-arg filtering, permanent-domain creation, and dashboard rendering.
   Run the focused control-plane suite plus dashboard typecheck/tests; local
   Docker verification deploys a static managed image and proves that its
   immutable route remains available after a second release.

## Framework contract

| Detection | Build output | Runtime | SPA fallback | Public build variables |
| --- | --- | --- | --- | --- |
| Vite | `dist/` | nginx | yes | `VITE_*` |
| Next with `output: 'export'` | `out/` | nginx | no | `NEXT_PUBLIC_*` |
| Next SSR | `.next/` | existing Node app | n/a | existing app contract |
| Astro without a server adapter | `dist/` | nginx | no | `PUBLIC_*` |
| Create React App | `build/` | nginx | yes | `REACT_APP_*` |

Dockerfile precedence is absolute: a repository Dockerfile or explicit
`dockerfile_path` always remains user-owned and bypasses presets.

## Preview model

A permanent deployment URL is the lightweight code-review URL for each build.
It is not a branch environment and it never gets overwritten. Phase 5 PR
environments remain the explicit full-stack preview path, with isolated
environment rows and their own cleanup. This avoids accidentally running two
preview systems against the same backing database.

## Explicitly not in this phase

- serverless functions or an edge runtime;
- ISR/on-demand revalidation;
- platform image optimization;
- a second branch-preview lifecycle alongside Phase 5 PR environments.

## Verification

```bash
# focused platform proof
cd control-plane
uv run pytest tests/test_detect.py tests/test_deploy.py tests/test_crud.py -q

# dashboard proof
cd ../web
npm test -- --run
npm run typecheck

# manual static delivery proof (local Docker stack)
# deploy two static releases, then verify both d-<id>.localhost URLs respond;
# restore the first release and confirm the service alias changes without a
# build or restart.
```

## Done when

- [x] Vite and CRA projects build into nginx images and SPA routes return the
  app shell.
- [x] static Next exports and Astro static projects use their correct output
  directory without SPA fallback.
- [x] Next SSR still uses the ordinary app-container path.
- [x] every successful deployment has one permanent deployment-pinned URL,
  visible in deploy history and still routable after later releases.
- [x] restore/promote is a sub-second routing operation with no rebuild and
  does not alter permanent URLs.
- [x] only safe public frontend build variables are accepted; values never
  appear in a build log and changes require redeploy.
- [x] Phase 5 remains the sole isolated full-stack PR-preview mechanism.
- [x] `README.md` has an accurate Phase 7 section and active roadmap references
  use Phase 7.
