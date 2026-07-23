# Phase 5.5 — Frontends

**Target:** 1 week

**Demo:** deploy a Vite SPA and a Next.js app from GitHub. Every push gets its
own permanent URL. Roll back by moving an alias.

Backends stay the moat. This phase exists so you do not need a second platform
for the other half of an app.

**Nothing here introduces a new execution model.** A static site is a build
artifact wrapped in nginx and run as a container. An SSR app is a long-running
container, which Rudder already does. Scheduler, reconciler, mesh, health checks —
all unchanged.

---

## Prerequisites

- [ ] D15 landed in Phase 1 — the `Domain` table is the whole foundation here
- [ ] Phase 1 verified

That's it. This phase does not depend on 2, 3, 4, or 5. It can move earlier if
frontends become urgent.

---

## Steps

### 1. Framework presets

Extend `detect.py`. Same heuristics-only rule as language detection — **no LLM.**

| Detected | Build | Output | Result |
|---|---|---|---|
| Vite (`vite.config.*`) | `npm run build` | `dist/` | static |
| Next.js (`next.config.*`) | `npm run build` | `.next/` | server (standalone) |
| Next.js with `output: 'export'` | `npm run build` | `out/` | static |
| Astro (`astro.config.*`) | `npm run build` | `dist/` | static, or server if adapter |
| SvelteKit (`svelte.config.*`) | `npm run build` | depends on adapter | either |
| CRA (`react-scripts` in deps) | `npm run build` | `build/` | static |

Each preset yields: build command, output dir, and static-vs-server.

Detection order matters — check for a `Dockerfile` first (user override), then
framework config files, then fall back to the Phase 1 language detection.

### 2. Static builds

When the preset resolves to static output:

1. Run the build in the builder stage
2. `COPY` the output dir into `nginx:alpine`
3. Generate an nginx config: SPA fallback to `index.html`, correct MIME types,
   long cache headers on hashed assets, no cache on `index.html`
4. Push that image

From there **the existing pipeline handles everything.** `Service.kind=static`
only changes two things: the health check becomes `GET /` expecting 200, and the
service is skipped for mesh membership.

Two-stage Dockerfile template in `control-plane/dockerfile_templates/static.Dockerfile.j2`.

### 3. SSR apps

No new work. `kind=app`, normal container, normal health check.

Next.js in standalone output mode, Nuxt, Remix, SvelteKit-node all just work
through the Phase 1 path. The preset only needs to set the right build command
and start command.

### 4. Immutable deployment URLs

Every successful Deployment gets a Domain row:

- `target_type=deployment`
- hostname `{deployment_short_id}.{base_domain}`
- permanent

**Never repointed. Never garbage collected.** That permanence is the whole
feature — a URL you can paste into a PR review and trust to still work in six
months.

`deployment_short_id` is the first 8 chars of the deployment UUID, or a
short-hash. Must be URL-safe and collision-checked.

### 5. Branch previews

Push to any non-default branch → build and deploy → upsert a Domain:

- hostname `{branch-slug}.{service}.{env}.{base_domain}`
- `target_type=deployment`, pointed at the new Deployment

Branch slug must pass the D9 hostname regex — slugify and truncate.

Branch deleted → drop the Domain, drain the Instances.

**Different from Phase 4 PR environments.** A branch preview deploys new code
against the environment's *existing* backing services. A PR environment clones
everything including the database. Both are legitimate; let the project choose
per-service. This step builds the first one.

### 6. UI

Deployment list per service. Each entry shows its permanent URL, plus:

- **Promote** — repoint the production Domain at this Deployment
- **Rollback** — the same operation, backwards

Custom domain form: add a hostname, choose `target_type`, show the DNS record the
user needs to create.

---

## Explicitly not in this phase

See `../PRD.md` → "Explicit Non-Goals" for the reasoning.

- Serverless functions
- Edge runtime
- ISR / on-demand revalidation
- Platform-level image optimization

If you want Next.js API routes, run the app as a normal container. That's 90% of
the value for none of the machinery.

---

## Where this goes wrong

**Build-time env vars.** Frontend builds bake env vars into the bundle at build
time, not runtime. `VITE_*` and `NEXT_PUBLIC_*` must be injected during the
build, not into the container. This surprises people constantly — a variable
changed after build has no effect until rebuild. Surface that in the UI.

**SPA fallback vs real 404s.** Fallback-everything-to-`index.html` means genuine
404s return 200 with the app shell. Correct for SPAs, wrong for static sites with
real routes. Make it a preset property, not a global.

**Cache headers.** `index.html` must not be cached or users get stuck on an old
build forever while hashed assets rotate underneath. Hashed assets should be
cached hard. Getting this backwards produces bugs that only appear for returning
visitors.

**Deployment URL collisions.** 8 chars of UUID is fine, but check for collision
on insert rather than assuming.

**Branch slug collisions.** `feat/auth` and `feat-auth` slugify identically.
Detect and disambiguate.

**Orphaned domains.** Branch deleted while a deploy for it is in flight. The
deploy completes and creates a Domain for a branch that no longer exists. Clean
up on both paths.

---

## Verify

```bash
# 1. Vite SPA
rudder service create web --repo <vite-repo>
rudder deploy web --follow
curl <url>                          # → index.html
curl <url>/some/client/route        # → 200, index.html (SPA fallback)

# 2. Immutable deployment URLs
#    push twice
rudder deployment list web
curl <deployment-1-url>             # → first build
curl <deployment-2-url>             # → second build
# Both still serving. This is the key assertion.

# 3. Promote an older deployment
time rudder promote web <deployment-1-id>
curl <production-url>               # → first build
# → sub-second, no rebuild

# 4. Next.js SSR
rudder service create app --repo <next-repo>
rudder deploy app --follow
curl <url>                          # → server-rendered HTML

# 5. Branch preview
git push origin feat-auth
# → feat-auth.app.production.localhost serves the branch
git push origin --delete feat-auth
# → domain gone, instances drained

# 6. Cache headers
curl -I <url>/index.html            # → no-cache
curl -I <url>/assets/main.<hash>.js # → immutable, long max-age
```

---

## Done when

- [ ] Vite SPA deploys and serves with working client-side routing
- [ ] Next.js SSR deploys through the unchanged Phase 1 path
- [ ] Every deployment has a permanent URL that keeps working after later pushes
- [ ] Promote and rollback are sub-second with no rebuild
- [ ] Branch push creates a preview URL, branch delete removes it
- [ ] Build-time env vars are injected at build and documented as such in the UI
- [ ] Cache headers correct — `index.html` uncached, hashed assets immutable
- [ ] No serverless function code exists anywhere in the repo
- [ ] `README.md` Phase 5.5 section
