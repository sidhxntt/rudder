 # GitHub Import and Managed Add-ons Implementation Plan

  Goal: Let a user import a GitHub repository like Vercel/Netlify, confirm detected Node.js dependencies, provision private
  Postgres/Redis services, build and deploy the app, and serve its public URL.

  Architecture: Use a GitHub App for installation-scoped repository access and per-repository webhooks. An import workflow
  creates a new project and production environment, detects Node dependencies from package.json, and—after confirmation—creates
  the public app plus private managed add-ons. Existing Dockerfile detection/build/deploy remains the sole app build path.

  ## Key changes

  - Add GitHub App configuration, installation callback, encrypted installation credentials, repository/branch listing, and
    setup-required UI when credentials are absent.

  - Add an import API/state model: create import, inspect selected repository, return detected express, Postgres, and Redis
    candidates, confirm provisioning, and expose import/build status.

  - Detect Node only:
      - app: express
      - Postgres: pg, Prisma, or Sequelize
      - Redis: redis or ioredis
      - never infer from source-code calls.

  - On confirmation, create a new project with production environment:
      - one app service using the selected repo/branch;
      - optional managed PostgreSQL 16 and Redis 7 services;
      - persistent volumes for managed data;
      - generated encrypted credentials;
      - DATABASE_URL / REDIS_URL references injected into the app.

  - Do not provision an add-on if the app already defines the matching variable; show it as externally managed instead.
  - Enforce private add-ons: no Domain row or Traefik route for Postgres/Redis. Only the app receives a public system URL.
  - Retain the existing Dockerfile-or-generated-Dockerfile build path, rollout health checks, immutable deployment records, and
    old-live-on-failed-deploy behavior.

  - Make imports idempotent per GitHub installation, repository, and branch so retries cannot create duplicate services or
    volumes.

  - Add UI flow: Connect GitHub → select repository/branch → review detected add-ons → Create and deploy → project canvas with
    app URL and private dependency nodes.

  - Preserve the current generic signed GitHub push webhook for manually configured services; imported repositories use GitHub
  ## Tests

  - GitHub App callback, webhook signature verification, repository authorization, and unavailable-configuration state.
  - Node manifest detection for supported dependencies, unsupported packages, and false-positive avoidance.
  - Import idempotency, existing-variable non-overwrite, encrypted generated credentials, service/volume creation, and private-
    routing enforcement.

  - Repository build with generated Dockerfile and supplied Dockerfile.
  - End-to-end Express import with confirmed Postgres and Redis: private URLs injected, add-ons live, app health check passes,
    public app URL serves.

  - Failure cases: clone failure, invalid manifest, add-on startup failure, app build failure, health-check failure, retry
    without duplicate resources, and subsequent failed deploy retaining the previous live app.

  - UI tests for setup-required, dependency confirmation, progress/error states, and canvas visibility.

  ## Assumptions

  - GitHub App credentials will be configured later; the first implementation is fully setup-ready and clearly disabled until
    then.

  - Rudder creates a new project/environment per import.
  - Postgres and Redis are private-only in Phase 1.
  - Detection is confirmation-based and Node.js-only; Python/Go detection and Docker Compose import remain out of scope.