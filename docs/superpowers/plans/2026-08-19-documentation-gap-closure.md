# Documentation Gap Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the audited documentation gaps and make README, product claims, evidence, terminology, configuration, operations, and Wiki output agree with the current Rudder codebase.

**Architecture:** Keep the concise consolidated documentation set and add only three focused references: configuration, GKE operations, and Phase 4 evidence. Update existing narrative pages with small claim corrections and publish the new references through the existing Wiki renderer.

**Tech Stack:** Markdown, Node.js Wiki renderer, repository shell/Make/Terraform interfaces.

---

### Task 1: Repair product and README truth

**Files:**
- Modify: `README.md`
- Modify: `PRODUCT.md`

- [ ] **Step 1: Remove stale SDK and deleted-source claims**

Change the product surface to canvas plus Node/TypeScript CLI and point evidence only to existing consolidated pages.

- [ ] **Step 2: Expand README navigation and operational entry points**

Link configuration, GKE operations, and Phase 4 evidence while retaining the concise single-tenant and controlled-beta framing.

- [ ] **Step 3: Verify stale claims are absent**

Run:

```bash
rg -n "canvas, CLI, and SDK|docs/PRD.md|PHASE-4-COMPLETION" README.md PRODUCT.md
```

Expected: no matches.

### Task 2: Correct autoscaling and isolation terminology

**Files:**
- Modify: `docs/architecture.md`
- Modify: `docs/features.md`
- Modify: `docs/conclusion.md`
- Modify: `docs/overview.md`
- Modify: `docs/multi-cloud.md`
- Modify: `docs/tech-stack.md`
- Modify: `docs/phases/phase-3.md`
- Modify: `docs/phases/phase-4.md`
- Modify: `docs/phases/phase-5.md`
- Modify: `docs/phases/phase-6.md`

- [ ] **Step 1: State the implemented HPA boundary**

Document that Kubernetes application workloads support persisted HPA intent while Docker autoscaling, cluster/node autoscaler provisioning, and guaranteed spare capacity remain unsupported.

- [ ] **Step 2: Normalize current isolation language**

Use environment/workload terminology for implemented namespaces. Keep tenant terminology only in passages explicitly describing future hardened multi-tenancy.

- [ ] **Step 3: Search for known contradictions**

Run:

```bash
rg -n "no autoscaling|not.*an autoscaler|Multi-tenant isolation model|tenant-owned graph|owns tenant namespaces" docs
```

Expected: no unintended present-day product claims.

### Task 3: Preserve Phase 4 evidence

**Files:**
- Create: `docs/evidence/phase-4-controlled-beta.md`
- Modify: `docs/phases/phase-4.md`
- Modify: `docs/index.md`
- Modify: `docs/overview.md`
- Modify: `docs/multi-cloud.md`

- [ ] **Step 1: Write the bounded evidence record**

Record the dated deployment, immutable build, readiness, HTTPS, rollback, backup/restore/PITR, isolation, failed candidate, drain, monitoring, secret, DNS/certificate, and 12-vCPU quota evidence already stated in the consolidated narrative. Label it point-in-time controlled-beta evidence.

- [ ] **Step 2: Link every checkpoint claim to the new record**

Replace generic or deleted checkpoint references with `docs/evidence/phase-4-controlled-beta.md`.

- [ ] **Step 3: Verify evidence pointers**

Run:

```bash
rg -n "Phase 4 checkpoint|controlled-beta checkpoint|documented checkpoints" docs
```

Expected: each Phase 4 evidence claim links to the focused record.

### Task 4: Restore focused configuration and operations guidance

**Files:**
- Create: `docs/configuration.md`
- Create: `docs/gke-operations.md`
- Modify: `docs/index.md`
- Modify: `docs/tech-stack.md`
- Modify: `docs/phases/phase-4.md`

- [ ] **Step 1: Write configuration guide**

Group current `.env.example`, control-plane, CLI, Kubernetes, GKE, backup, GitHub, and Advisor settings. Link to the authoritative files and never include live values.

- [ ] **Step 2: Write GKE operations guide**

Document prerequisites and the existing `make gke-preflight`, `make gke-bootstrap`, `make gke-verify`, Terraform, and kubectl configuration paths. Preserve the shared-pool quota gate and recovery boundaries.

- [ ] **Step 3: Verify referenced commands and files**

Run:

```bash
rg -n "^(gke-preflight|gke-bootstrap|gke-verify):" Makefile
test -f .env.example
test -f infra/gcp/scripts/preflight-gke.sh
test -f infra/gcp/scripts/bootstrap-platform.sh
test -f infra/gcp/scripts/verify-gke.sh
```

Expected: three Make targets and all files exist.

### Task 5: Publish and verify the complete documentation set

**Files:**
- Modify: `docs/_Sidebar.md`
- Modify: `docs/wiki-publishing.md`
- Modify: `scripts/render-github-wiki.mjs`

- [ ] **Step 1: Add the new pages to Wiki rendering and navigation**

Map configuration, GKE operations, and Phase 4 evidence to stable Wiki page names.

- [ ] **Step 2: Validate every relative Markdown target**

Run the repository-wide Node link check used in the audit. Expected: `ALL_RELATIVE_LINK_TARGETS_EXIST`.

- [ ] **Step 3: Render the Wiki**

Run:

```bash
node scripts/render-github-wiki.mjs /tmp/rudder-doc-gap-closure-wiki
```

Expected: successful rendering with the expanded page count.

- [ ] **Step 4: Inspect claims and diff hygiene**

Run:

```bash
git diff --check
rg -n "six GKE clusters|6 GKE clusters|canvas, CLI, and SDK|no autoscaling" README.md PRODUCT.md docs
```

Expected: no whitespace errors and no unsupported/contradictory claims.
