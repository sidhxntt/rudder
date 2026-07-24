# Compose Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Deploy every GitHub-imported application as one Docker Compose project, using repository Compose when present and a generated manifest otherwise.

**Architecture:** The control plane resolves and persists a safe Compose manifest per import. The agent exclusively invokes allowlisted Docker Compose lifecycle commands; Rudder retains services, deployments, domains, volumes, health gates, and logs.

**Tech Stack:** FastAPI, SQLModel/Alembic, Docker Compose CLI, BuildKit, Traefik, Next.js, pytest.

---

### Task 1: Persist Compose import metadata and repair deletion

**Files:**
- Modify: control-plane/rudder_cp/models/github_import.py
- Create: control-plane/migrations/versions/0004_compose_runtime.py
- Modify: control-plane/rudder_cp/services/services.py
- Modify: control-plane/tests/test_runtime_deletion.py

- [ ] **Step 1: Write failing persistence/deletion tests**

~~~python
async def test_delete_project_removes_volumes_before_services(session, agent, settings):
    project, service, volume = await make_project_with_volume(session)
    await delete_project(session, project.id, agent=agent, settings=settings)
    assert session.get(Volume, volume.id) is None
    assert session.get(Service, service.id) is None
~~~

- [ ] **Step 2: Run it**

Run: cd control-plane && uv run pytest tests/test_runtime_deletion.py -q

Expected: FAIL with the current volume foreign-key violation.

- [ ] **Step 3: Implement fields and flush ordering**

~~~python
compose_source: str = Field(sa_column=sa.Column(sa.String(16), nullable=False))
compose_manifest: str = Field(sa_column=sa.Column(sa.Text, nullable=False))
compose_project_name: str = Field(sa_column=sa.Column(sa.String(96), unique=True, nullable=False))

for volume in volumes:
    session.delete(volume)
session.flush()
session.delete(service)
~~~

The migration backfills imported rows before non-null constraints apply.

- [ ] **Step 4: Verify and commit**

Run: cd control-plane && uv run pytest tests/test_runtime_deletion.py tests/test_import_provisioning.py -q

~~~bash
git add control-plane/rudder_cp/models/github_import.py control-plane/migrations/versions/0004_compose_runtime.py control-plane/rudder_cp/services/services.py control-plane/tests/test_runtime_deletion.py
git commit -m "feat: persist Compose imports and fix project cleanup"
~~~

### Task 2: Resolve repository and generated manifests

**Files:**
- Create: control-plane/rudder_cp/services/compose.py
- Modify: control-plane/rudder_cp/services/github_app.py
- Modify: control-plane/rudder_cp/services/imports.py
- Create: control-plane/tests/test_compose.py
- Modify: control-plane/tests/test_import_planner.py

- [ ] **Step 1: Write parser tests**

~~~python
def test_repository_compose_marks_only_web_as_public():
    plan = parse_compose("services:\n  web: {build: ., ports: ['3000:3000']}\n  db: {image: postgres:16}")
    assert plan.source == "repository"
    assert plan.services["web"].public_port == 3000
    assert plan.services["db"].public_port is None

def test_parser_rejects_host_bind():
    with pytest.raises(ComposeValidationError, match="host bind"):
        parse_compose("services: {web: {image: nginx, volumes: ['./:/app']}}")
~~~

- [ ] **Step 2: Run them**

Run: cd control-plane && uv run pytest tests/test_compose.py -q

Expected: FAIL because the parser does not exist.

- [ ] **Step 3: Implement safe resolution**

~~~python
COMPOSE_FILENAMES = ("compose.yaml", "compose.yml", "docker-compose.yaml", "docker-compose.yml")

@dataclass(frozen=True)
class ComposePlan:
    source: Literal["repository", "generated"]
    services: dict[str, ComposeService]
    yaml: str
~~~

Use yaml.safe_load. Reject host bind mounts, Docker socket mounts, container_name,
privileged mode, arbitrary network_mode, and custom networks. Rudder rewrites
project name, networks, named volumes, labels, and app image tags. Add a GitHub
file-at-ref client method.

- [ ] **Step 4: Verify and commit**

Run: cd control-plane && uv run pytest tests/test_compose.py tests/test_import_planner.py -q

~~~bash
git add control-plane/rudder_cp/services/compose.py control-plane/rudder_cp/services/github_app.py control-plane/rudder_cp/services/imports.py control-plane/tests/test_compose.py control-plane/tests/test_import_planner.py
git commit -m "feat: resolve repository and generated Compose manifests"
~~~

### Task 3: Add allowlisted Compose lifecycle commands to the agent

**Files:**
- Modify: agent/rudder_agent/schemas.py
- Modify: agent/rudder_agent/docker_ops.py
- Modify: agent/rudder_agent/main.py
- Modify: control-plane/rudder_cp/services/agent_client.py
- Create: agent/tests/test_compose.py

- [ ] **Step 1: Write agent test**

~~~python
async def test_compose_up_returns_output(fake_runner):
    fake_runner.output = "Container app Created\nContainer app Started\n"
    result = await ops.compose_up(project_name="rudder-env", manifest_path="/state/rudder-env/compose.yml")
    assert result.project_name == "rudder-env"
    assert "Started" in result.log
~~~

- [ ] **Step 2: Run it**

Run: cd agent && uv run pytest tests/test_compose.py -q

Expected: FAIL because the operation does not exist.

- [ ] **Step 3: Implement an allowlisted subprocess boundary**

~~~python
async def compose_up(self, project_name: str, manifest_path: str) -> ComposeResult:
    return await self._run_compose(["up", "--detach", "--remove-orphans"], project_name, manifest_path)

async def compose_down(self, project_name: str, manifest_path: str) -> ComposeResult:
    return await self._run_compose(["down", "--volumes", "--remove-orphans"], project_name, manifest_path)
~~~

Write manifests only under the agent state directory. Invoke only Docker Compose with
a fixed project name, manifest path, and command allowlist. Add up, ps, and down
HTTP endpoints.

- [ ] **Step 4: Verify and commit**

Run: cd agent && uv run pytest tests/test_compose.py tests/test_create.py -q

~~~bash
git add agent/rudder_agent control-plane/rudder_cp/services/agent_client.py agent/tests/test_compose.py
git commit -m "feat: let the node agent manage Compose projects"
~~~

### Task 4: Deploy Compose projects with health-gated routes and logs

**Files:**
- Modify: control-plane/rudder_cp/services/deploy.py
- Modify: control-plane/rudder_cp/services/worker.py
- Modify: control-plane/rudder_cp/services/traefik.py
- Modify: control-plane/rudder_cp/services/imports.py
- Modify: control-plane/tests/test_deploy.py
- Modify: control-plane/tests/test_logs.py
- Modify: control-plane/tests/test_traefik.py

- [ ] **Step 1: Write failed-release and per-service-log tests**

~~~python
async def test_compose_candidate_failure_keeps_old_route(session, agent, store):
    old = await make_live_compose_deployment(session)
    agent.compose_ps.return_value = unhealthy_candidate()
    outcome = await run_deployment(await queue_replacement(session), session=session, engine=engine, agent=agent, store=store, settings=settings)
    assert outcome.status is DeploymentStatus.FAILED
    assert current_route(session) == old.id
~~~

- [ ] **Step 2: Run them**

Run: cd control-plane && uv run pytest tests/test_deploy.py tests/test_logs.py tests/test_traefik.py -q

Expected: FAIL because deployments create individual containers.

- [ ] **Step 3: Switch imported deployments to Compose**

~~~python
result = await agent.compose_up(imported.compose_project_name, manifest_path(imported))
await append_compose_output(store, deployment.id, result.log)
state = await agent.compose_service(imported.compose_project_name, service.name)
~~~

Create Instance records from Compose service state. Route only a declared public
service after health succeeds and retain the old route after a failed candidate.
Append relevant Compose output to every service deployment log.

- [ ] **Step 4: Verify and commit**

Run: cd control-plane && uv run pytest tests/test_deploy.py tests/test_logs.py tests/test_traefik.py tests/test_import_provisioning.py -q

~~~bash
git add control-plane/rudder_cp/services/deploy.py control-plane/rudder_cp/services/worker.py control-plane/rudder_cp/services/traefik.py control-plane/rudder_cp/services/imports.py control-plane/tests/test_deploy.py control-plane/tests/test_logs.py control-plane/tests/test_traefik.py
git commit -m "feat: deploy imported services as Compose projects"
~~~

### Task 5: Show Compose plans in the import review

**Files:**
- Modify: web/lib/types.ts
- Modify: web/lib/api.ts
- Modify: web/lib/queries.ts
- Modify: web/app/projects/[projectId]/environments/[environmentId]/github-import-dialog.tsx
- Create: web/app/projects/[projectId]/environments/[environmentId]/github-import-dialog.test.tsx

- [ ] **Step 1: Write the review test**

~~~tsx
server.use(previewWithCompose({ services: ["web", "postgres", "redis"] }));
render(<GitHubImportDialog />);
await userEvent.click(screen.getByRole("button", { name: /continue/i }));
expect(await screen.findByText(/compose.yml detected/i)).toBeInTheDocument();
~~~

- [ ] **Step 2: Implement and validate**

Show compose.yml detected or Rudder generated Compose, public/private service
badges, and a collapsible resolved-manifest preview. Show add-on checkboxes only
for generated manifests.

Run: cd web && npm test -- github-import-dialog.test.tsx && npm run typecheck && npm run build

- [ ] **Step 3: Commit**

~~~bash
git add web/lib/types.ts web/lib/api.ts web/lib/queries.ts web/app/projects/[projectId]/environments/[environmentId]/github-import-dialog.tsx web/app/projects/[projectId]/environments/[environmentId]/github-import-dialog.test.tsx
git commit -m "feat: show Compose import plans in the UI"
~~~

### Task 6: Verify live imports and cleanup

**Files:**
- Create: docs/phases/checkpoints/COMPOSE-IMPORT-VERIFICATION.md

- [ ] **Step 1: Record verification checklist**

~~~markdown
- [ ] OAuth login establishes a Rudder session.
- [ ] Repository Compose starts one Compose project.
- [ ] Plain repository gets a generated manifest and live URL.
- [ ] Add-ons have no public route and each service has logs.
- [ ] Broken release preserves the prior live URL.
- [ ] Project deletion removes containers, volumes, routes, and rows.
~~~

- [ ] **Step 2: Run complete automated checks**

Run: cd control-plane && uv run ruff check rudder_cp tests && uv run pytest tests -q && cd ../agent && uv run ruff check rudder_agent tests && uv run pytest tests -q && cd ../web && npm run typecheck && npm run build

Expected: all commands exit 0.

- [ ] **Step 3: Run local smoke imports and cleanup**

Import the configured test repository once with Compose and once without. Verify
live URLs, private add-ons, service logs, and Compose grouping; delete both
projects and confirm no application Compose project or Rudder volume remains.

