# GitHub OAuth and Compose Import Verification

## Automated checks completed

- Compose import, catalog, routing, lifecycle, and rollback coverage: 78 passed.
- Current control-plane suite collection: 317 tests.
- Control plane lint: `uv run ruff check rudder_cp tests migrations/versions` — passed.
- Node agent: `uv run pytest tests -q` — 55 passed.
- Node agent lint: `uv run ruff check rudder_agent tests` — passed.
- Web: `npm test` (2 tests), `npm run typecheck`, and `npm run build` — passed.
- Alembic offline SQL was generated through revision `0005`; the Compose metadata
  backfill and the Compose child-service graph are rendered without parameters.

## Manual verification before release

Run these checks against a fresh local Rudder stack after applying migrations.

- [ ] GitHub OAuth login redirects to GitHub and returns to a Rudder session.
- [ ] The import dialog redirects to GitHub App installation automatically when
  the account has no installation, then lists only approved repositories.
- [ ] Changing a repository reloads its branches; changing a branch reloads its
  plan.
- [ ] A repository `compose.yml` appears as **Repository Compose detected**,
  shows every public/private service, its role, and its resolved manifest.
- [ ] A plain Express repository appears as **Rudder-generated Compose** and
  can provision any selected catalog add-on privately: PostgreSQL, MySQL,
  MariaDB, MongoDB, Redis, Memcached, RabbitMQ, NATS, Meilisearch, Typesense,
  MinIO, Qdrant, Prometheus, or Grafana.
- [ ] A repository with a `Procfile` or recognized npm scripts shows web,
  worker, scheduler, and realtime candidates. The generated release starts
  private process containers from the same immutable app image.
- [ ] Select a starter template and verify its catalog services appear in the
  reviewed Compose manifest. A template-selected service remains explicit and
  can be unchecked before confirmation.
- [ ] A repository Compose file with multiple published services requires an
  explicit public-service selection; only selected services receive domains.
- [ ] A successful import creates one versioned Docker Compose project; the
  selected public services get URLs, while workers and add-ons do not get routes.
- [ ] Select a private worker, database, broker, or observability service in
  the canvas. It must show **Managed by Compose**, share the owner release’s
  deployment history and build logs, and have no standalone Deploy action.
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
