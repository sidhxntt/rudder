# CLI and web parity implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Phase 9 CLI a login-first client of the same authenticated control-plane API as the web workspace, then install it locally with `npm link` for operator testing.

**Architecture:** The CLI remains an API-only client. A first-run authentication guard obtains the existing GitHub OAuth CLI handoff before an operational command executes, and all project/service/deploy state continues to be read or changed through the same endpoints used by the web UI. A focused CLI integration test verifies the guard and a manual local-stack script proves bidirectional visibility.

**Tech Stack:** Node 20, TypeScript, Vitest, `@clack/prompts`, FastAPI control plane, Docker Compose.

---

### Task 1: Add a login-first command guard

**Files:**
- Modify: `cli/node/src/index.ts`
- Modify: `cli/node/src/client.test.ts`

- [ ] **Step 1: Write failing tests for an unauthenticated operational command**

Cover the public commands (`help`, `login`, `logout`) separately from an operator command. Assert that a non-interactive invocation without `RUDDER_TOKEN` fails with an instruction to authenticate, instead of issuing an unauthenticated API request.

- [ ] **Step 2: Run the targeted test and confirm it fails**

Run: `cd cli/node && npm test -- --run client.test.ts`

Expected: the guard is absent and the new assertion fails.

- [ ] **Step 3: Implement the minimal guard**

Before dispatching a command other than `help`, `login`, or `logout`, use the stored token or `RUDDER_TOKEN`. If neither exists, begin the existing GitHub browser-login flow for an interactive terminal; in non-interactive mode, fail with `Run rudder login or set RUDDER_TOKEN.` Persist only the issued API token through `saveConfig`.

- [ ] **Step 4: Run the targeted test and confirm it passes**

Run: `cd cli/node && npm test -- --run client.test.ts`

Expected: PASS.

### Task 2: Document and prove shared-state behavior

**Files:**
- Modify: `docs/phases/PHASE-9-cli.md`

- [ ] **Step 1: Add a web-to-CLI and CLI-to-web local-stack checklist**

Document this exact proof: authenticate the CLI, list a project created in the web UI, create a uniquely named test project through the CLI, reload the web dashboard and observe it, then delete that test project through the CLI and confirm it disappears from the dashboard.

- [ ] **Step 2: Run package verification**

Run: `cd cli/node && npm test && npm run typecheck && npm run build`

Expected: all tests pass and `dist/index.js` is generated.

### Task 3: Link and smoke-test the local binary

**Files:**
- No source files.

- [ ] **Step 1: Link the built package**

Run: `cd cli/node && npm link`

Expected: the local package is globally linked and `rudder help` resolves to this checkout.

- [ ] **Step 2: Verify the linked executable**

Run: `rudder help`

Expected: output starts with `rudder — Rudder control-plane CLI`.
