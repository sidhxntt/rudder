# Compose Runtime and GitHub OAuth

## Goal

Make GitHub the only user-facing login and import surface. A signed-in user
selects a GitHub repository and branch, then Rudder deploys the application as
one Docker Compose project per Rudder environment.

If the repository provides a Compose file, Rudder uses that file after
validation and normalization. If it does not, Rudder detects the application
and requested managed add-ons, generates an equivalent Compose file, and uses
that generated file for the deployment.

## Authentication and repository access

GitHub OAuth authenticates Rudder users. The `/auth/github/start` endpoint
redirects to GitHub, and the callback creates or links a Rudder `User` only by
GitHub's stable 64-bit numeric user ID. The nullable `github_id` and
`github_login` fields are introduced by
`control-plane/migrations/versions/0003_github_oauth_identity.py`; login names
and emails remain mutable profile data, never account-linking keys. It then
issues the existing Rudder session cookie.

The GitHub App remains a server-side integration. It supplies repository
contents, branch discovery, installation access, and webhook authentication.
It is never configured by a Rudder user. If an authenticated user's account
has no eligible GitHub App installation, Rudder redirects them to the App's
installation flow and resumes the import flow after GitHub returns them.

The existing email/password endpoint may remain temporarily for local
bootstrap and tests, but the web UI exposes only **Continue with GitHub**.

## Import flow

1. The user signs in with GitHub and opens **Import from GitHub**.
2. Rudder discovers the user's GitHub App installations, repositories, and
   branches. Installation selection is automatic when only one applies.
3. The user chooses a repository and branch.
4. Rudder inspects the selected revision for these Compose filenames, in
   precedence order: `compose.yaml`, `compose.yml`, `docker-compose.yaml`,
   `docker-compose.yml`.
5. The review screen displays either the discovered Compose services or the
   generated app plus managed add-ons. The user confirms deployment.
6. Rudder persists the resolved, normalized Compose manifest as part of the
   import/deployment record and starts one Compose project for the environment.

## Compose normalization and safety

Rudder accepts a deliberately small, production-safe Compose subset:

- `services.*.build`, `image`, `command`, `environment`, `env_file`, `ports`,
  `expose`, `depends_on`, `volumes`, and service health checks.
- Named volumes only; host bind mounts, privileged mode, Docker socket mounts,
  arbitrary `network_mode`, and `container_name` are rejected.
- Rudder owns the project name, container names, networks, public route
  labels, resource limits, image tags, and persistent-volume names.
- Only explicitly selected/exposed application services receive a public URL.
  Databases, Redis, workers, and internal services remain private.

For a repository without Compose, Rudder generates a manifest containing the
detected app service and any selected managed add-ons such as PostgreSQL and
Redis. It injects private DNS aliases and encrypted connection variables into
the app service. The generated manifest is visible in the review/deployment
details but is not written back to the user repository.

## Runtime model

Each Rudder environment maps to one Compose project named from its immutable
environment ID. That project has:

- an environment-private network for app-to-add-on communication;
- the existing shared `rudder` edge network only for services that need a
  Traefik route;
- persistent named volumes owned by the project;
- a deployment-specific image tag for built application services.

Rudder invokes `docker compose` through the node agent. It captures Compose
build/pull/start output and attributes it to the corresponding Rudder service
deployment. Rudder continues to store services, deployments, domains, and
volumes as first-class records for the UI and API, but Compose becomes the
runtime owner of the containers.

Rolling release safety remains explicit: build a new app image, create the
candidate container through the Compose project, verify its health, update the
Traefik route only after success, then stop the previous candidate. A failed
candidate remains marked failed and the old live route continues serving.

## UI

The signed-out entry point is a GitHub OAuth button. The import dialog has two
steps:

1. **Source**: GitHub connection, repository, and branch. When needed, the
   browser is redirected to GitHub App installation automatically.
2. **Review and deploy**: Compose-file detected/generated status, service list,
   add-on choices only when Rudder is generating Compose, public-service
   selection, and the resolved Compose preview.

The canvas renders each Compose service as a Rudder service card. Selecting a
card shows that service's deployment history and its individual Compose
build/pull/start logs. Add-on cards show lifecycle logs as app cards do.

## Cleanup and recovery

Deleting a Rudder project runs `docker compose down --volumes` for every
environment project before deleting database records and routes. It then
removes generated manifests and build logs. The database cascade must flush
service volumes before deleting services; this fixes the foreign-key failure
observed during the pre-Compose clear-slate cleanup.

If runtime cleanup fails, Rudder keeps the project record and reports the
failure so deletion can be retried. It never deletes database state first and
leaves unmanaged containers behind.

## Tests and acceptance criteria

- GitHub OAuth callback creates/links a Rudder user and session; the UI has no
  password login path.
- An installed GitHub App can list the test repository and its branches after
  OAuth login.
- Importing a repository with `compose.yml` produces a validated normalized
  manifest and starts a single Compose project with the declared services.
- Importing a simple repository without Compose produces a generated manifest
  and starts app, PostgreSQL, and Redis as one Compose project.
- Only the app URL is publicly reachable; PostgreSQL and Redis resolve only on
  the private environment network.
- Logs exist for every service in both generated and repository-provided
  Compose deployments.
- A broken replacement remains failed while the prior public URL serves the
  live version.
- Project deletion removes containers, volumes, routes, manifests, and
  database records; repeating deletion is safe.
