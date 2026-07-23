# web

Next.js 15 App Router + React Flow canvas. Scaffolded in Phase 1 step 10.
Design tokens already live in `styles/tokens.css` (D5).

---

## Running it

```bash
npm install
npm run dev        # http://localhost:3000
npm run typecheck  # tsc --noEmit
npm run build
```

The control plane must be running on `:8000` (`docker compose -f
../docker-compose.dev.yml up -d`). Point elsewhere with `RUDDER_API_URL`.

## The seam

Every data access in this tree goes through `lib/api.ts`, and it is the only
file that calls `fetch`. `lib/types.ts` is transcribed from the live
`GET /openapi.json`, schema by schema. `lib/queries.ts` is the TanStack Query
layer over that seam; components call those hooks and nothing else.

Build logs are the exception to "everything is a query": `GET
/deployments/{id}/build-log` is an SSE stream, not a document, so
`build-logs.tsx` subscribes to `api.streamBuildLog` directly. It is read with
`fetch` + `AbortSignal` rather than `EventSource`, because `EventSource` cannot
see a 404 and would reconnect forever against a deployment that never built.

## Auth

`POST /auth/token` returns a bearer token *and* sets an httpOnly `rudder_token`
cookie. This app uses the cookie and nothing else — the token in the response
body is dropped on the floor, and no JWT is ever written to `localStorage`.

That only works same-origin. The control plane mounts no CORS middleware, so a
browser fetch from `:3000` to `:8000` is cross-origin and unreadable — ports are
not part of a *site* (so the `SameSite=Lax` cookie is content) but they are part
of an *origin*. So `next.config.ts` rewrites `/api/*` onto the control plane and
`lib/api.ts` only ever calls `/api/...`. No preflight, no CORS config, cookie
sent automatically, SSE passes through unbuffered.

A 401 from any query or mutation lands in the cache-level handler in
`app/providers.tsx`, which drops the whole app back to `app/login-screen.tsx`.

## Service status

`Service` has no status column. `lib/status.ts` derives one from Deployments
(intent) and Instances (fact). The case that matters: a Deployment can sit at
`live` while its Instance is `stopped` — the control plane shifted traffic and
the container died afterwards. The URL 503s. That renders `failed`, never
`live`.

## What is deliberately not here

- **Runtime logs.** D4 — build logs only in Phase 1. There is no runtime log view.
- **Variable values.** The API never returns them (they are `value_encrypted` on
  the table). They render masked with an edit affordance; the mask is not a
  reveal toggle, there is nothing to reveal.
- **Canvas edges.** Service-to-service links would have to be read out of
  reference variables, whose values the API never returns.
- **Reconciliation around `canvas_x/canvas_y`.** D6 — layout is UI metadata.
  Drag persists through `PATCH /services/{id}` carrying nothing but the two
  coordinates, and nothing reads it back. A stored `(0, 0)` — the server-side
  default — is treated as "never placed" and drawn in a fallback grid slot, so a
  fresh environment does not stack every node on one point. That fallback is not
  written back; only a drag persists.

## Tokens

`styles/tokens.css` is the source of truth. `tailwind.config.ts` maps every
token into the Tailwind theme by `var()` reference — there is not one hex
literal anywhere in this tree outside `styles/tokens.css`.
