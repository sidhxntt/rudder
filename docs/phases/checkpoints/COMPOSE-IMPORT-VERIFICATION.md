# GitHub OAuth and Compose Import Verification

## Automated checks completed

- Control plane: `uv run pytest tests -q` — 293 passed.
- Control plane lint: `uv run ruff check rudder_cp tests migrations/versions` — passed.
- Node agent: `uv run pytest tests -q` — 54 passed.
- Node agent lint: `uv run ruff check rudder_agent tests` — passed.
- Web: `npm run typecheck` and `npm run build` — passed.
- Alembic offline SQL was generated through revision `0004`; the Compose metadata
  backfill is rendered with a non-null literal manifest.

## Manual verification before release

Run these checks against a fresh local Rudder stack after applying migrations.

- [ ] GitHub OAuth login redirects to GitHub and returns to a Rudder session.
- [ ] The import dialog redirects to GitHub App installation automatically when
  the account has no installation, then lists only approved repositories.
- [ ] Changing a repository reloads its branches; changing a branch reloads its
  plan.
- [ ] A repository `compose.yml` appears as **Repository Compose detected**,
  shows its public/private services, and exposes its resolved manifest.
- [ ] A plain Express repository appears as **Rudder-generated Compose** and
  can provision selected PostgreSQL and Redis add-ons privately.
- [ ] A successful import creates one versioned Docker Compose project; the
  app service gets the public URL and add-ons do not get routes.
- [ ] A deliberately broken candidate marks its deployment failed while the
  old public URL still answers from the prior live release.
- [ ] Build/deployment logs show the Compose lifecycle output.
- [ ] Deleting an imported project removes its routes, service rows, volumes,
  containers, and Compose releases.

## Configuration required

GitHub user login and GitHub repository access are separate integrations.

- GitHub OAuth App: set `RUDDER_GITHUB_OAUTH_CLIENT_ID`,
  `RUDDER_GITHUB_OAUTH_CLIENT_SECRET`, and
  `RUDDER_GITHUB_OAUTH_REDIRECT_URI`.
- GitHub App: set `RUDDER_GITHUB_APP_ID`, `RUDDER_GITHUB_APP_SLUG`, and
  `RUDDER_GITHUB_APP_PRIVATE_KEY` (or its file-backed equivalent), then
  install the app for the desired account/repositories.
