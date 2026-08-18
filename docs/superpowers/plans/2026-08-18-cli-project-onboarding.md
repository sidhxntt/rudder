# CLI Project Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `rudder` require an existing-project selection or the shared GitHub import flow before displaying operational commands.

**Architecture:** The Node CLI calls the same authenticated GitHub-import routes as the web dialog and saves the returned project/environment IDs through its existing context store. A focused wizard module contains prompts and typed API orchestration; the launcher only owns entry ordering and the existing operational menu.

**Tech Stack:** Node 20+, TypeScript, Vitest, `@clack/prompts`, existing Rudder REST API.

---

### Task 1: Add a testable GitHub import wizard

**Files:**
- Create: `cli/node/src/github-import-wizard.ts`
- Test: `cli/node/src/github-import-wizard.test.ts`

- [x] **Step 1: Write failing wizard tests**

```ts
it("posts the reviewed GitHub selection and returns the created context", async () => {
  prompts.select
    .mockResolvedValueOnce(7)
    .mockResolvedValueOnce("acme/api")
    .mockResolvedValueOnce("main")
    .mockResolvedValueOnce("repository")
    .mockResolvedValueOnce("confirm");
  api.request.mockResolvedValueOnce([{ id: 7, account_login: "acme" }])
    .mockResolvedValueOnce([{ full_name: "acme/api", default_branch: "main", private: true }])
    .mockResolvedValueOnce(["main"])
    .mockResolvedValueOnce({ addons: ["postgres"], services: [{ name: "app", role: "web", is_public: true }] })
    .mockResolvedValueOnce({ project_id: "project", environment_id: "environment", import_id: "import" });

  await expect(runGitHubImportWizard({ api, prompts })).resolves.toEqual({ projectId: "project", environmentId: "environment" });
  expect(api.request).toHaveBeenLastCalledWith("POST", "/github/imports", expect.objectContaining({
    installation_id: 7, repository: "acme/api", branch: "main", public_services: ["app"],
  }));
});
```

- [x] **Step 2: Run the test to verify it fails**

Run: `cd cli/node && npm test -- github-import-wizard.test.ts`

Expected: failure because `github-import-wizard.ts` does not exist.

- [x] **Step 3: Implement the minimal wizard**

```ts
export async function runGitHubImportWizard({ api, prompts }: WizardDependencies): Promise<ImportContext | undefined> {
  const installation = await prompts.select({ message: "Choose GitHub connection", options: installationOptions(await api.request("GET", "/github/import/installations")) });
  if (prompts.isCancel(installation)) return;
  const repository = await chooseRepository(api, prompts, installation);
  if (!repository) return;
  const preview = await api.request("POST", "/github/import/preview", repository);
  const confirmed = await prompts.confirm({ message: "Create this Rudder project?" });
  if (prompts.isCancel(confirmed) || !confirmed) return;
  const created = await api.request("POST", "/github/imports", confirmationPayload(repository, preview));
  return importContext(created);
}
```

- [x] **Step 4: Run the focused test to verify it passes**

Run: `cd cli/node && npm test -- github-import-wizard.test.ts`

Expected: PASS with the request sequence and returned IDs asserted.

- [x] **Step 5: Commit the wizard**

```bash
git add cli/node/src/github-import-wizard.ts cli/node/src/github-import-wizard.test.ts
git commit -m "feat(cli): add GitHub import wizard"
```

### Task 2: Gate the launcher on project context

**Files:**
- Modify: `cli/node/src/launcher.ts`
- Modify: `cli/node/src/launcher.test.ts`
- Modify: `cli/node/src/index.ts`
- Modify: `cli/node/src/index.test.ts`

- [x] **Step 1: Write failing project-gate tests**

```ts
it("asks for a project before rendering the operational launcher menu", async () => {
  prompts.select.mockResolvedValueOnce("create-from-github").mockResolvedValueOnce("exit");
  await runLauncher({ authenticated: true, projectSelected: false, actions });
  expect(actions.createFromGitHub).toHaveBeenCalledOnce();
  expect(prompts.select.mock.calls[0]?.[0].message).toBe("Choose a project");
});
```

- [x] **Step 2: Run tests to verify they fail**

Run: `cd cli/node && npm test -- launcher.test.ts index.test.ts`

Expected: failure because `projectSelected` and `createFromGitHub` do not exist.

- [x] **Step 3: Implement the project-first launcher contract**

```ts
if (!projectSelected) {
  const selected = await prompts.select({
    message: "Choose a project",
    options: [...projectOptions, { value: "create-from-github", label: "Create new from GitHub" }, { value: "exit", label: "Exit" }],
  });
  if (selected === "create-from-github") await actions.createFromGitHub();
  if (selected === "exit" || prompts.isCancel(selected)) return;
}
```

`index.ts` must provide `projectOptions` from `GET /projects`, persist an existing selection with `saveConfig`, and call the wizard for creation. The returned import context replaces project/environment/service context only after the API confirms creation.

- [x] **Step 4: Run tests to verify they pass**

Run: `cd cli/node && npm test -- launcher.test.ts index.test.ts`

Expected: PASS with no config write after cancellation and a saved context after either selection path.

- [x] **Step 5: Commit the project gate**

```bash
git add cli/node/src/launcher.ts cli/node/src/launcher.test.ts cli/node/src/index.ts cli/node/src/index.test.ts
git commit -m "feat(cli): gate launcher on project selection"
```

### Task 3: Verify the local CLI handoff

**Files:**
- Modify: `docs/phases/PHASE-9-cli.md`

- [x] **Step 1: Add one operator-facing test path**

```md
1. Run `rudder` in a new TTY and select **Sign in with GitHub**.
2. Complete browser authorization, then select **Create new from GitHub**.
3. Complete the repository wizard and confirm the release.
4. Verify `rudder` saves the returned project/environment and `rudder status` shows the same services as the web workspace.
```

- [x] **Step 2: Run complete CLI verification**

Run: `cd cli/node && npm test && npm run typecheck && npm run build && npm link`

Expected: all Vitest files pass, TypeScript exits zero, and npm reports the linked package is current.

- [ ] **Step 3: Commit locally only**

```bash
git add docs/phases/PHASE-9-cli.md
git commit -m "docs(cli): describe project onboarding"
```

Do not push or open a pull request.
