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

## The seam

**The control plane does not exist yet.** Every data access in this tree goes
through `lib/api.ts`, which today delegates to an in-memory mock in
`lib/mock.ts`. Nothing else imports `lib/mock.ts`, and nothing anywhere calls
`fetch`. When the OpenAPI client is generated (PRD → "Interfaces", "TS SDK"),
each function body in `lib/api.ts` becomes one client call and the signatures do
not move.

`lib/queries.ts` is the TanStack Query layer over that seam. Components call
those hooks and nothing else.

## What is deliberately not here

- **Runtime logs.** D4 — build logs only in Phase 1. There is no runtime log view.
- **Variable values.** The API never returns them (they are `value_encrypted` on
  the table). They render masked with an edit affordance; the mask is not a
  reveal toggle, there is nothing to reveal.
- **Canvas edges.** Service-to-service links would have to be read out of
  reference variables, whose values the API never returns.
- **Reconciliation around `canvas_x/canvas_y`.** D6 — layout is UI metadata.
  Drag persists through `PATCH /services/{id}` and nothing reads it back.

## Tokens

`styles/tokens.css` is the source of truth. `tailwind.config.ts` maps every
token into the Tailwind theme by `var()` reference — there is not one hex
literal anywhere in this tree outside `styles/tokens.css`.
