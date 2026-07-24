# Compose Service Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support safe multi-service Compose imports and deterministic starter templates for common app processes, managed add-ons, and observability services.

**Architecture:** Repository Compose remains authoritative and is normalized into a service graph with public/private roles. When no Compose file exists, detection proposes only a versioned catalog of templates; the user reviews roles, add-ons, manifest, and public services before Rudder provisions one Compose release. All child services inherit the lifecycle and logs of their owning Compose release.

**Tech Stack:** FastAPI, SQLModel/Alembic, Docker Compose v2, Next.js/React, TypeScript, Vitest, pytest, PyYAML.

---

## File structure

- Modify `control-plane/rudder_cp/services/compose.py`: catalog definitions, generated manifest factory, service role/public metadata, and safe validation.
- Create `control-plane/rudder_cp/services/processes.py`: manifest/Procfile process detection with explicit evidence.
- Modify `control-plane/rudder_cp/services/imports.py`: turn reviewed process/add-on choices into service records, variables, and one release owner.
- Modify `control-plane/rudder_cp/routers/imports.py`: preview/confirm schemas and starter-template endpoints.
- Modify `control-plane/rudder_cp/models/github_import.py` and add Alembic migration: persist service-to-Compose-release mapping and template metadata.
- Modify `control-plane/rudder_cp/services/deploy.py`: map Compose status/log events to every child service without standalone deployments.
- Modify `web/app/projects/[projectId]/environments/[environmentId]/github-import-dialog.tsx`: four-step repository/template wizard.
- Modify `web/app/projects/[projectId]/environments/[environmentId]/canvas.tsx`, `service-node.tsx`, and `detail-panel.tsx`: child role, public/private state, shared deployment lifecycle/log UX.
- Modify `web/app/page.tsx`: starter template cards and GitHub import entry point.
- Create/modify focused pytest and Vitest files under `control-plane/tests/` and `web/app/**/__tests__/`.

### Task 1: Model Compose services and catalog templates

**Files:**
- Modify: `control-plane/rudder_cp/services/compose.py`
- Test: `control-plane/tests/test_compose.py`

- [ ] Write failing tests for a repository manifest containing `web`, `worker`, `postgres`, `prometheus`, and `grafana`; assert roles, private/public state, and two explicit public-port candidates are preserved.
- [ ] Add a `ComposeService` role (`web`, `worker`, `scheduler`, `realtime`, `database`, `cache`, `broker`, `search`, `storage`, `observability`, `other`) and a `public` boolean derived only from a declared port plus an approved review choice.
- [ ] Define immutable catalog templates for PostgreSQL, MySQL, MariaDB, MongoDB, Redis, Memcached, RabbitMQ, NATS, Meilisearch, Typesense, MinIO, Qdrant, Prometheus, and Grafana. Include named volumes for stateful services and private `expose` ports.
- [ ] Add tests that generated templates parse successfully, include their required named volumes, and never contain host bindings or privileged settings.
- [ ] Commit: `feat: add safe Compose service catalog`.

### Task 2: Detect app process roles without guessing source code

**Files:**
- Create: `control-plane/rudder_cp/services/processes.py`
- Modify: `control-plane/rudder_cp/services/imports.py`
- Test: `control-plane/tests/test_import_planner.py`

- [ ] Write failing tests for `package.json` scripts `start`, `worker`, `start:worker`, `queue`, `schedule`, and `cron`, plus Procfile entries `web`, `worker`, and `clock`.
- [ ] Implement evidence records with source, name, command, and proposed role. Map only known script/Procfile names; leave unknown scripts unproposed.
- [ ] Extend add-on detection with exact dependency evidence for the catalog, and ensure existing connection variables always suppress automatic provisioning.
- [ ] Run `uv run pytest tests/test_import_planner.py tests/test_compose.py -q`; expect pass.
- [ ] Commit: `feat: detect reviewed process roles and add-ons`.

### Task 3: Persist Compose release ownership for every child service

**Files:**
- Modify: `control-plane/rudder_cp/models/github_import.py`
- Create: `control-plane/migrations/versions/<revision>_compose_service_graph.py`
- Modify: `control-plane/rudder_cp/services/imports.py`
- Test: `control-plane/tests/test_import_provisioning.py`

- [ ] Write failing provisioning tests that confirm one release-owner deployment is created for web, worker, Postgres, and Grafana children; verify each child is mapped to its Compose service name and does not receive its own queued deployment.
- [ ] Add persisted graph metadata to `GitHubImport` sufficient to map a child service to its owning deployment, role, public state, and Compose service name.
- [ ] Update `provision_import` to create one Rudder service per Compose entry, inject private connection variables into app processes, and create domains only for selected public services.
- [ ] Generate SQL with `uv run alembic upgrade head --sql` and run `uv run pytest tests/test_import_provisioning.py -q`; expect pass.
- [ ] Commit: `feat: persist Compose import service graphs`.

### Task 4: Extend import API and starter-template workflow

**Files:**
- Modify: `control-plane/rudder_cp/routers/imports.py`
- Test: `control-plane/tests/test_github_import_api.py`

- [ ] Write failing endpoint tests for previewing repository Compose, previewing a named starter template, selecting public services, and rejecting unlisted process/add-on/public-service choices.
- [ ] Return detected processes, catalog proposals, all Compose services with roles, and public eligibility from preview.
- [ ] Add `GET /github/import/templates` and allow preview/confirm payloads to select either repository+branch or a starter template; preserve repository Compose priority.
- [ ] Run `uv run pytest tests/test_github_import_api.py tests/test_import_provisioning.py -q`; expect pass.
- [ ] Commit: `feat: expose Compose catalog through import API`.

### Task 5: Propagate release status and logs to Compose children

**Files:**
- Modify: `control-plane/rudder_cp/services/deploy.py`
- Modify: `control-plane/rudder_cp/services/imports.py`
- Test: `control-plane/tests/test_deploy.py`
- Test: `control-plane/tests/test_deployments_api.py`

- [ ] Write failing tests for child services reporting `queued`, `building`, `live`, and `failed` from the owning release, including shared logs and a failed release retaining the prior live route.
- [ ] Implement a single release-state lookup used by deployment/list/log endpoints for Compose-managed children.
- [ ] Ensure standalone Deploy is rejected with an explicit `managed_by_compose` response for all Compose children, rather than a generic 422 failure.
- [ ] Run `uv run pytest tests/test_deploy.py tests/test_deployments_api.py -q`; expect pass.
- [ ] Commit: `fix: share Compose release lifecycle with child services`.

### Task 6: Implement the import wizard and dashboard templates

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/github-import-dialog.tsx`
- Create: `web/app/projects/[projectId]/environments/[environmentId]/github-import-dialog.test.tsx`

- [ ] Write failing UI tests for the four steps: source/template, repository/branch, roles/add-ons, and final manifest/public-service review.
- [ ] Add starter-template cards; preserve OAuth-first GitHub flow for repository imports.
- [ ] Move runtime/add-on detection to the review step, show detection evidence, and require an explicit confirmation before creating infrastructure.
- [ ] Run `npm run typecheck` and the focused UI tests; expect pass.
- [ ] Commit: `feat: add Compose import and starter-template wizard`.

### Task 7: Present every Compose service correctly on the canvas

**Files:**
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/canvas.tsx`
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/service-node.tsx`
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/detail-panel.tsx`
- Test: focused tests adjacent to these components

- [ ] Write failing tests for private worker/database/broker nodes and public web/Grafana nodes inheriting release status and log availability.
- [ ] Render role badges, private-network labels, public-domain labels, and a "Managed by Compose release" state.
- [ ] Replace child deploy buttons with a link to the owning release and filter shared logs with the selected Compose-service name when available.
- [ ] Run `npm run typecheck`; manually verify a repository `web + worker + postgres + prometheus + grafana` topology and a generated Node + Postgres + Redis topology.
- [ ] Commit: `feat: display Compose service roles and shared release state`.

### Task 8: Full verification and operational documentation

**Files:**
- Modify: `docs/phases/checkpoints/COMPOSE-IMPORT-VERIFICATION.md`
- Modify: `docs/superpowers/specs/2026-07-24-compose-service-catalog-design.md`

- [ ] Add an end-to-end checklist for generated catalog imports, repository Compose imports, private routing, selected public Grafana routing, logs, and failed-release rollback.
- [ ] Run `uv run pytest tests -q`, `uv run ruff check rudder_cp tests`, and `npm run typecheck`.
- [ ] With the dev server stopped, run `npm run build`; then restart `npm run dev` and verify a project route returns HTTP 200. Do not run the build alongside dev because Next’s shared `.next` cache can corrupt vendor chunks.
- [ ] Commit: `test: verify Compose service catalog workflows`.
