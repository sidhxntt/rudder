# Rudder Control Plane Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Rudder's public landing page and authenticated workspace feel like one calm, observable deployment control plane while retaining its dark emerald identity.

**Architecture:** Public persuasion remains isolated in `LandingPage`; workspace navigation remains in the shell; project/environment operations remain in route-local components. Shared UI primitives own visual consistency, while the existing query hooks and backend APIs continue to own state and mutations.

**Tech Stack:** Next.js App Router, React, TypeScript, Tailwind CSS, TanStack Query, Vitest, React Flow.

---

### Task 1: Establish semantic public-page navigation and action hierarchy

**Files:**
- Modify: `web/app/landing-page.tsx`
- Modify: `web/app/landing-page.test.tsx`

- [ ] **Step 1: Write a failing landing-page navigation test**

```tsx
it("keeps public navigation and the signed-in workspace action distinct", () => {
  render(<LandingPage authenticated />);
  expect(screen.getByRole("link", { name: "Open workspace" })).toHaveAttribute("href", "/dashboard");
  expect(screen.getByRole("link", { name: "Deploy from GitHub" })).toHaveAttribute("href", "/dashboard?import=github");
});
```

- [ ] **Step 2: Run the focused test and confirm it fails before behavior is added**

Run: `cd web && npm test -- landing-page.test.tsx`

Expected: the new accessible navigation expectation fails.

- [ ] **Step 3: Refine the nav and hero in `LandingPage`**

```tsx
<nav aria-label="Primary" className="...">
  <div className="...">{/* Rudder mark + In development badge */}</div>
  <div className="...">
    <a href="#capabilities">Capabilities</a>
    <a href="#run-locally">Run locally</a>
    <Link href="/dashboard">Open workspace</Link>
  </div>
</nav>
```

Keep the hero primary action GitHub sign-in when anonymous and repository import when authenticated. Preserve all current capability truth and deployment target labels.

- [ ] **Step 4: Run the focused test**

Run: `cd web && npm test -- landing-page.test.tsx`

Expected: PASS.

### Task 2: Make the workspace landing an operational dashboard

**Files:**
- Modify: `web/app/workspace-page.tsx`
- Create: `web/app/workspace-page.test.tsx`

- [ ] **Step 1: Write a failing workspace test for a returning user's operational context**

```tsx
it("shows recent activity and a direct deployment action for a returning user", () => {
  render(<WorkspacePage />);
  expect(screen.getByRole("heading", { name: /your workspace/i })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /deploy from github/i })).toHaveAttribute("href", "/dashboard?import=github");
});
```

- [ ] **Step 2: Run the test and confirm it fails before the new structure is added**

Run: `cd web && npm test -- workspace-page.test.tsx`

Expected: FAIL because the dashboard heading or accessible action is missing.

- [ ] **Step 3: Restructure `WorkspacePage` into context, action, and evidence regions**

```tsx
<section aria-labelledby="workspace-heading">
  <p>Workspace</p>
  <h1 id="workspace-heading">{isReturning ? `Welcome back, ${userName}` : "Deploy from a repository you trust."}</h1>
  <Link href="/dashboard?import=github">Deploy from GitHub</Link>
</section>
<section aria-label="Recent activity">{/* recent event rows */}</section>
<section aria-label="Projects">{/* ordered project rows */}</section>
```

Use existing project/node query data only. Keep an explicit empty state for a first-time user and do not add fabricated activity.

- [ ] **Step 4: Run the focused test**

Run: `cd web && npm test -- workspace-page.test.tsx`

Expected: PASS.

### Task 3: Improve service-detail scanning without changing deployment behavior

**Files:**
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/detail-panel.tsx`
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/build-logs.tsx`
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/detail-panel.test.tsx` if present, otherwise create it

- [ ] **Step 1: Write failing tests for accessible tab selection and actionable build-log framing**

```tsx
expect(screen.getByRole("tab", { name: "Analytics" })).toHaveAttribute("aria-selected", "false");
await user.click(screen.getByRole("tab", { name: "Analytics" }));
expect(screen.getByRole("tab", { name: "Analytics" })).toHaveAttribute("aria-selected", "true");
```

- [ ] **Step 2: Run the focused test and confirm it fails**

Run: `cd web && npm test -- detail-panel.test.tsx`

Expected: FAIL because the tablist semantics are absent.

- [ ] **Step 3: Add semantic tablist behavior and compact log context**

```tsx
<div role="tablist" aria-label="Service views" className="...">
  <button role="tab" aria-selected={tab === entry.id} aria-controls={`${entry.id}-panel`}>
    {entry.label}
  </button>
</div>
<section id={`${tab}-panel`} role="tabpanel">{/* selected content */}</section>
```

Retain the existing immutable rollback mutation. Keep logs as source evidence with level-aware `[INFO]`, `[WARN]`, `[ERROR]`, and `[DEBUG]` color treatment; do not alter log data or deployment APIs.

- [ ] **Step 4: Run the focused test**

Run: `cd web && npm test -- detail-panel.test.tsx`

Expected: PASS.

### Task 4: Verify the surface and guard against regressions

**Files:**
- Verify: `web/app/landing-page.tsx`
- Verify: `web/app/workspace-page.tsx`
- Verify: `web/app/projects/[projectId]/environments/[environmentId]/detail-panel.tsx`

- [ ] **Step 1: Run focused frontend tests**

Run: `cd web && npm test -- landing-page.test.tsx workspace-page.test.tsx detail-panel.test.tsx`

Expected: PASS.

- [ ] **Step 2: Run the complete frontend verification**

Run: `cd web && npm test && npm run typecheck && npm run build`

Expected: all tests and TypeScript checks pass; Next.js build completes.

- [ ] **Step 3: Inspect generated UI at desktop and mobile widths**

Run the local web app, capture `/` and `/dashboard` at desktop and mobile widths, then check that the primary action, hierarchy, service topology, selected-service panel, and keyboard focus are visible without clipping.

- [ ] **Step 4: Run the Impeccable detector on changed surfaces**

Run: `node .agents/skills/impeccable/scripts/detect.mjs --json web/app/landing-page.tsx web/app/workspace-page.tsx web/app/projects/[projectId]/environments/[environmentId]/detail-panel.tsx`

Expected: no new mechanical design-system findings, or documented intentional exceptions only.
