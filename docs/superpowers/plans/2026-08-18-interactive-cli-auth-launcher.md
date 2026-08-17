# Interactive CLI Authentication and Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `rudder` a polished GitHub-authenticated terminal control plane while keeping explicit commands script-safe.

**Architecture:** A generic five-minute, opaque, single-use authorization handoff extends the existing GitHub OAuth flow. The CLI opens that server-issued URL, polls the handoff for an ordinary bearer token, and presents a Clack launcher whose actions reuse the existing command/API paths.

**Tech Stack:** FastAPI, PyJWT, Node 20, TypeScript, `@clack/prompts`, Vitest.

---

### Task 1: Generic authorization handoff

**Files:**
- Create: `control-plane/rudder_cp/services/authorization_handoff.py`
- Test: `control-plane/tests/test_authorization_handoff.py`

- [ ] **Step 1: Write the failing test**

```python
def test_completed_handoff_is_consumed_once() -> None:
    handoffs = AuthorizationHandoffs()
    authorization_id = handoffs.create()
    handoffs.complete(authorization_id, "jwt")
    assert handoffs.consume(authorization_id) == "jwt"
    with pytest.raises(InvalidAuthorizationHandoff):
        handoffs.consume(authorization_id)
```

- [ ] **Step 2: Verify RED**

Run: `cd control-plane && uv run pytest tests/test_authorization_handoff.py -q`

Expected: import failure because the service does not exist.

- [ ] **Step 3: Implement the lifecycle**

```python
class AuthorizationHandoffs:
    def create(self) -> str: ...
    def complete(self, authorization_id: str, token: str) -> None: ...
    def consume(self, authorization_id: str) -> str | None: ...
```

Use `secrets.token_urlsafe(32)`, `datetime.now(UTC)`, a five-minute TTL,
pruning on each operation, and deletion after a completed consume.

- [ ] **Step 4: Verify GREEN and commit**

Run: `cd control-plane && uv run pytest tests/test_authorization_handoff.py -q`

Expected: 1 passed.

Commit: `git add control-plane/rudder_cp/services/authorization_handoff.py control-plane/tests/test_authorization_handoff.py && git commit -m "feat(auth): add one-time authorization handoff"`

### Task 2: Attach the handoff to shared GitHub OAuth

**Files:**
- Modify: `control-plane/rudder_cp/schemas/auth.py`
- Modify: `control-plane/rudder_cp/services/github_oauth.py`
- Modify: `control-plane/rudder_cp/routers/auth.py`
- Modify: `control-plane/tests/test_app_auth.py`

- [ ] **Step 1: Write the failing router contract test**

```python
def test_authorization_handoff_consumes_once_after_github_callback(client, monkeypatch) -> None:
    started = client.post("/auth/authorizations")
    monkeypatch.setattr(GitHubOAuthClient, "exchange", _identity)
    callback = client.get(
        f"/auth/github/callback?code=valid&state={started.json()['state']}",
        follow_redirects=False,
    )
    assert callback.status_code == 200
    assert client.post(f"/auth/authorizations/{started.json()['id']}/consume").json()["access_token"]
    assert client.post(f"/auth/authorizations/{started.json()['id']}/consume").status_code == 401
```

- [ ] **Step 2: Verify RED**

Run: `cd control-plane && uv run pytest tests/test_app_auth.py::test_authorization_handoff_consumes_once_after_github_callback -q`

Expected: 404 because `/auth/authorizations` does not exist.

- [ ] **Step 3: Implement the generic endpoints**

Add `AuthorizationStartResponse(id, authorization_url, state)`. `POST
/auth/authorizations` returns 201 and `POST /auth/authorizations/{id}/consume`
returns 202 while pending, an existing `TokenResponse` once, and 401 afterward.
Extend signed GitHub state with optional `authorization_id`. Only callback state
with that ID completes a handoff and returns an HTML terminal-completion page;
normal web OAuth still sets its cookie and redirects to the dashboard.

- [ ] **Step 4: Verify GREEN and commit**

Run: `cd control-plane && uv run pytest tests/test_authorization_handoff.py tests/test_app_auth.py -q`

Expected: all focused tests pass.

Commit: `git add control-plane/rudder_cp/schemas/auth.py control-plane/rudder_cp/services/github_oauth.py control-plane/rudder_cp/routers/auth.py control-plane/tests/test_app_auth.py && git commit -m "feat(auth): share GitHub authorization handoff"`

### Task 3: Browser login client

**Files:**
- Create: `cli/node/src/github-login.ts`
- Create: `cli/node/src/github-login.test.ts`
- Modify: `cli/node/src/index.ts`

- [ ] **Step 1: Write the failing polling test**

```ts
it("opens the server URL and consumes its token", async () => {
  const request = vi.fn()
    .mockResolvedValueOnce({ id: "opaque", authorization_url: "https://github.com/login/oauth/authorize?state=signed" })
    .mockResolvedValueOnce(null)
    .mockResolvedValueOnce({ access_token: "cli-token", expires_in: 3600 });
  await expect(completeGitHubLogin({ api: { request } as never, open: vi.fn(), wait: async () => undefined }))
    .resolves.toMatchObject({ access_token: "cli-token" });
});
```

- [ ] **Step 2: Verify RED**

Run: `cd cli/node && npm test -- github-login.test.ts`

Expected: module import failure.

- [ ] **Step 3: Implement and wire login-first**

Create via `POST /auth/authorizations`, open with `open`/`xdg-open`/`cmd
start`, print a copyable URL if open fails, and poll once/second for five
minutes. Interactive `requireAuthentication` and `rudder login` reuse it then
the existing `saveAccessToken`; `RUDDER_TOKEN` and `--no-interactive` remain
unchanged.

- [ ] **Step 4: Verify GREEN and commit**

Run: `cd cli/node && npm test -- github-login.test.ts auth-guard.test.ts && npm run typecheck`

Expected: all focused tests pass.

Commit: `git add cli/node/src/github-login.ts cli/node/src/github-login.test.ts cli/node/src/index.ts && git commit -m "feat(cli): authenticate through shared GitHub flow"`

### Task 4: Interactive visual launcher

**Files:**
- Create: `cli/node/src/launcher.ts`
- Create: `cli/node/src/launcher.test.ts`
- Modify: `cli/node/src/index.ts`

- [ ] **Step 1: Write the failing launcher delegation test**

```ts
it("delegates Deploy from the launcher", async () => {
  const calls: string[] = [];
  await runLauncher({ select: async () => "deploy", onDeploy: async () => calls.push("deploy") });
  expect(calls).toContain("deploy");
});
```

- [ ] **Step 2: Verify RED**

Run: `cd cli/node && npm test -- launcher.test.ts`

Expected: module import failure.

- [ ] **Step 3: Implement the Rudder terminal surface**

For TTYs only, clear the terminal, show a compact dark/emerald ANSI Rudder
wordmark and status line, then Clack `intro`, `select`, `spinner`, `cancel`,
and `outro`. Menu entries: Choose project/environment, Deploy, Status, Logs,
Services, Variables, Advisor, Sign out, Exit. Delegated actions reuse existing
command functions and make no independent fetch calls. Cancel leaves config
unchanged.

- [ ] **Step 4: Dispatch no-command TTY execution**

Use the launcher only when args are empty, stdin is a TTY, and `--json` /
`--no-interactive` are absent. Preserve `rudder help` for non-TTY execution.

- [ ] **Step 5: Verify GREEN and commit**

Run: `cd cli/node && npm test -- launcher.test.ts && npm run typecheck && npm run build`

Expected: test, compiler and build pass.

Commit: `git add cli/node/src/launcher.ts cli/node/src/launcher.test.ts cli/node/src/index.ts && git commit -m "feat(cli): add interactive Rudder launcher"`

### Task 5: Documentation and live proof

**Files:**
- Modify: `cli/README.md`
- Modify: `docs/phases/PHASE-9-cli.md`

- [ ] **Step 1: Document safe interactive and automation modes**

Document `rudder` as GitHub-authenticated launcher and `RUDDER_TOKEN rudder
--no-interactive project list --json` as automation.

- [ ] **Step 2: Verify full repository behavior**

Run: `cd control-plane && uv run pytest tests/test_authorization_handoff.py tests/test_app_auth.py -q && cd ../cli/node && npm test && npm run typecheck && npm run build && npm link && cd ../../web && npm test && npm run typecheck && npm run build`

Expected: every command exits 0.

- [ ] **Step 3: Capture live evidence and commit**

Run `rudder` in a TTY, complete GitHub sign-in, select an existing deployment,
and confirm it reaches the web console. Confirm `rudder --no-interactive
project list` without `RUDDER_TOKEN` refuses to open a browser.

Commit: `git add cli/README.md docs/phases/PHASE-9-cli.md && git commit -m "docs(cli): document interactive launcher"`
