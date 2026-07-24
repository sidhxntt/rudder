# GitHub OAuth Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Replace browser password login with GitHub OAuth and retain the GitHub App for repositories.

**Architecture:** GitHub OAuth identifies Rudder users by GitHub's immutable 64-bit numeric ID and sets the existing session cookie. GitHub App installations remain the server-side authority for repository access and webhooks.

**Tech Stack:** FastAPI, SQLModel/Alembic, httpx, GitHub OAuth, Next.js, pytest.

---

### Task 1: Store GitHub OAuth identities

**Files:**
- Modify: \`control-plane/rudder_cp/config.py\`
- Modify: \`control-plane/rudder_cp/models/user.py\`
- Create: \`control-plane/migrations/versions/0003_github_oauth_identity.py\`
- Modify: \`control-plane/tests/test_auth.py\`

- [ ] **Step 1: Write a failing service test**

\`\`\`python
async def test_find_or_create_github_user_links_stable_id(session: Session) -> None:
    one = await auth.find_or_create_github_user(session, github_id=123, login="one", email=None)
    two = await auth.find_or_create_github_user(session, github_id=123, login="two", email=None)
    assert one.id == two.id
    assert two.github_login == "two"
\`\`\`

- [ ] **Step 2: Run it**

Run: \`cd control-plane && uv run pytest tests/test_auth.py::test_find_or_create_github_user_links_stable_id -q\`

Expected: FAIL because the service does not exist.

- [ ] **Step 3: Add fields, configuration, and migration**

\`\`\`python
github_id: int | None = Field(sa_column=sa.Column(sa.BigInteger, unique=True, index=True))
github_login: str | None = Field(default=None, max_length=255)
github_oauth_client_id: str = ""
github_oauth_client_secret: str = ""
github_oauth_redirect_uri: str = ""
\`\`\`

The migration adds nullable identity fields, and the service creates or updates
OAuth users only by GitHub's stable 64-bit numeric ID. Mutable login names and
emails are profile data, never account-linking keys.

- [ ] **Step 4: Verify and commit**

Run: \`cd control-plane && uv run pytest tests/test_auth.py -q\`

\`\`\`bash
git add control-plane/rudder_cp/config.py control-plane/rudder_cp/models/user.py control-plane/migrations/versions/0003_github_oauth_identity.py control-plane/tests/test_auth.py control-plane/tests/test_github_oauth_migration.py
git commit -m "feat: persist GitHub OAuth identities"
\`\`\`

### Task 2: Implement authorization-code routes

**Files:**
- Create: \`control-plane/rudder_cp/services/github_oauth.py\`
- Modify: \`control-plane/rudder_cp/services/auth.py\`
- Modify: \`control-plane/rudder_cp/routers/auth.py\`
- Modify: \`control-plane/tests/test_app_auth.py\`

- [ ] **Step 1: Write failing route tests**

\`\`\`python
def test_github_start_redirects_with_state(client):
    response = client.get("/auth/github/start", follow_redirects=False)
    assert response.status_code == 307
    assert "state=" in response.headers["location"]

def test_callback_sets_session(client, monkeypatch):
    monkeypatch.setattr(GitHubOAuthClient, "exchange", fake_exchange)
    response = client.get("/auth/github/callback?code=code&state=valid", follow_redirects=False)
    assert "rudder_token=" in response.headers["set-cookie"]
\`\`\`

- [ ] **Step 2: Run it**

Run: \`cd control-plane && uv run pytest tests/test_app_auth.py -q\`

Expected: FAIL with route 404s.

- [ ] **Step 3: Implement OAuth client and routes**

\`\`\`python
class GitHubOAuthClient:
    async def exchange(self, code: str) -> GitHubIdentity:
        access_token = await self._exchange_code_for_token(code)
        profile = await self._fetch_profile(access_token)
        return GitHubIdentity(id=int(profile["id"]), login=str(profile["login"]), email=profile.get("email"))

@router.get("/github/start")
async def github_start(request: Request) -> RedirectResponse:
    return RedirectResponse(GitHubOAuthClient(request.app.state.settings).authorization_url())

@router.get("/github/callback")
async def github_callback(request: Request, code: str, state: str, response: Response, session: SessionDep) -> RedirectResponse:
    identity = await GitHubOAuthClient(request.app.state.settings).exchange_after_state_check(code, state)
    user = await auth_service.find_or_create_github_user(session, identity.id, identity.login, identity.email)
    _set_session_cookie(response, issue_token(user.id).token, get_settings())
    return RedirectResponse("/", status_code=307)
\`\`\`

Sign a short-lived state with the existing JWT secret and audience
\`github-oauth-state\`, reject invalid state, link the user, and call the
existing session-cookie helper.

- [ ] **Step 4: Verify and commit**

Run: \`cd control-plane && uv run pytest tests/test_auth.py tests/test_app_auth.py -q\`

\`\`\`bash
git add control-plane/rudder_cp/services/github_oauth.py control-plane/rudder_cp/services/auth.py control-plane/rudder_cp/routers/auth.py control-plane/tests/test_auth.py control-plane/tests/test_app_auth.py
git commit -m "feat: authenticate Rudder users with GitHub OAuth"
\`\`\`

### Task 3: Make the web login GitHub-only

**Files:**
- Modify: \`web/app/login-screen.tsx\`
- Modify: \`web/lib/session.tsx\`
- Modify: \`web/lib/api.ts\`
- Create: \`web/app/login-screen.test.tsx\`

- [ ] **Step 1: Write the UI test**

\`\`\`tsx
expect(screen.getByRole("link", { name: /continue with github/i })).toHaveAttribute(
  "href", "/api/auth/github/start",
);
expect(screen.queryByLabelText(/password/i)).not.toBeInTheDocument();
\`\`\`

- [ ] **Step 2: Implement and validate**

Replace the form with a \`Continue with GitHub\` link, proxy OAuth routes when
web and API origins differ, and remove \`signIn\` from session context.

Run: \`cd web && npm test -- login-screen.test.tsx && npm run typecheck && npm run build\`

- [ ] **Step 3: Commit**

\`\`\`bash
git add web/app/login-screen.tsx web/lib/session.tsx web/lib/api.ts web/app/login-screen.test.tsx web/app/api/auth/github
git commit -m "feat: use GitHub OAuth from the Rudder login screen"
\`\`\`
