# CLI Status Views Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the default raw JSON Status view with an interactive choice of compact, detailed, and OpenAI-generated status explanations.

**Architecture:** Keep `rudder status --json` as the existing script-safe detailed API payload. For the TTY launcher, route Status into a focused submenu: compact status is formatted deterministically in the CLI, detailed status preserves the current raw payload, and AI summary sends a bounded status snapshot to the existing read-only advisor diagnosis endpoint. The submenu always provides Back to the main menu.

**Tech Stack:** Node.js, TypeScript, Vitest, Clack prompts, existing Rudder API client and advisor endpoint.

---

### Task 1: Create deterministic status presentation

**Files:**
- Create: `cli/node/src/status.ts`
- Create: `cli/node/src/status.test.ts`

- [ ] **Step 1: Write failing formatter tests**

```ts
it("summarizes the latest deployment and healthy instances for each service", () => {
  expect(formatCompactStatus(rows)).toContain("app       live       1/1 healthy");
  expect(formatCompactStatus(rows)).toContain("latest 106b06e");
});

it("marks a failed latest deployment with its operator-readable reason", () => {
  expect(formatCompactStatus(rows)).toContain("failed");
  expect(formatCompactStatus(rows)).toContain("Registry unavailable");
});
```

- [ ] **Step 2: Run the formatter test and verify it fails**

Run: `cd cli/node && npm test -- status.test.ts`

Expected: FAIL because `./status.js` does not exist.

- [ ] **Step 3: Implement bounded status data and compact formatter**

```ts
export type StatusRow = {
  service: { id: string; name: string; kind?: string };
  deployments: Array<{ status?: string; commit_sha?: string | null; error_message?: string | null }>;
  instances: Array<{ status?: string }>;
};

export function formatCompactStatus(rows: StatusRow[]): string {
  // Use only the newest deployment, count healthy/total instances, and shorten
  // errors to one readable line. Do not expose variables, commands, or image tags.
}
```

- [ ] **Step 4: Run the formatter test and verify it passes**

Run: `cd cli/node && npm test -- status.test.ts`

Expected: PASS.

### Task 2: Add Status submenu and summary routing

**Files:**
- Modify: `cli/node/src/index.ts:59`
- Modify: `cli/node/src/launcher.ts:7-102`
- Modify: `cli/node/src/index.test.ts`
- Test: `cli/node/src/status.test.ts`

- [ ] **Step 1: Write failing command and submenu tests**

```ts
it("keeps --json status machine-readable", async () => {
  await command(state, ["status"]);
  expect(console.log).toHaveBeenCalledWith(expect.stringContaining('"service"'));
});

it("offers compact, detailed, AI summary, and Back in the status submenu", async () => {
  await runStatusMenu(actions);
  expect(prompts.select).toHaveBeenCalledWith(expect.objectContaining({
    options: expect.arrayContaining([
      expect.objectContaining({ label: "Compact status" }),
      expect.objectContaining({ label: "Detailed status" }),
      expect.objectContaining({ label: "AI summary" }),
      expect.objectContaining({ label: "Back to main menu" }),
    ]),
  }));
});
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `cd cli/node && npm test -- launcher.test.ts index.test.ts status.test.ts`

Expected: FAIL because the Status menu and compact status action do not exist.

- [ ] **Step 3: Implement the Status action boundary**

```ts
async function loadStatusRows(state: State): Promise<StatusRow[]> {
  const environment = await resolve(state, "environment");
  const services = await state.api.request("GET", `/environments/${environment}/services`);
  return Promise.all(services.map(async service => ({
    service,
    deployments: await state.api.request("GET", `/services/${service.id}/deployments`),
    instances: await state.api.request("GET", `/services/${service.id}/instances`),
  })));
}

async function status(state: State): Promise<void> {
  const rows = await loadStatusRows(state);
  if (state.out.json) return print(rows, state.out);
  // Direct command prints compact status. Launcher delegates to runStatusMenu.
  console.log(formatCompactStatus(rows));
}
```

```ts
// launcher.ts
{ value: "compact", label: "Compact status", hint: "Live services and latest release" }
{ value: "detailed", label: "Detailed status", hint: "Full deployment and instance data" }
{ value: "summary", label: "AI summary", hint: "Explain current state and next steps" }
{ value: "back", label: "Back to main menu" }
```

- [ ] **Step 4: Route AI summary through the existing read-only endpoint**

```ts
const response = await advisorRequest(state.api, "diagnose", undefined, {
  status: rows.map(toSafeStatusSnapshot),
});
print(response, state.out);
```

The snapshot contains only service name/kind, latest deployment state and short error, instance health counts, and abbreviated commit. It must not include encrypted variables, image tags, Redis commands, container IDs, or raw log bodies. If the endpoint reports that `OPENAI_API_KEY` is unavailable, print that message and preserve the compact status.

- [ ] **Step 5: Run focused tests and verify they pass**

Run: `cd cli/node && npm test -- launcher.test.ts index.test.ts status.test.ts`

Expected: PASS.

### Task 3: Verify all CLI contracts

**Files:**
- Modify: `cli/node/src/status.ts`
- Modify: `cli/node/src/status.test.ts`
- Modify: `cli/node/src/index.ts`
- Modify: `cli/node/src/launcher.ts`

- [ ] **Step 1: Run the complete CLI quality gate**

Run: `cd cli/node && npm test && npm run typecheck && npm run build && git diff --check`

Expected: all Vitest tests pass, TypeScript emits no diagnostics, build succeeds, and the diff has no whitespace errors.

- [ ] **Step 2: Commit local-only Phase 9 work**

```bash
git add cli/node/src/status.ts cli/node/src/status.test.ts cli/node/src/index.ts cli/node/src/launcher.ts cli/node/src/index.test.ts cli/node/src/launcher.test.ts docs/superpowers/plans/2026-08-18-cli-status-views.md
git commit -m "feat(cli): add guided status views"
```

Do not push, open a pull request, or merge this `phase-9` change.
