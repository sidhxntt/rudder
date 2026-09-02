# Rudder Engineering Challenges and Portfolio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a verified Phase 0–9 engineering-challenges narrative, clarify GitHub integration roles, and add Rudder to the portfolio with authentic copy and imagery.

**Architecture:** Repository documentation remains the source of truth and the existing Wiki publisher maps it to GitHub Wiki pages. The portfolio continues using its existing duplicated content pipeline: editable JSON input plus typed TypeScript data, with no new UI component.

**Tech Stack:** Markdown, Bash documentation validators, JSON, TypeScript, Next.js 16, Vitest

**Spec:** `docs/superpowers/specs/2026-09-03-engineering-challenges-and-portfolio-design.md`

## Global Constraints

- Every claim must trace to implemented code, tests, phase documentation, or controlled-beta evidence.
- GitHub OAuth authenticates humans; GitHub App installations authorize repository operations; signed webhooks deliver events; GitHub Packages distributes the CLI.
- GitHub Packages must not be described as Rudder's application-image registry.
- Do not claim hosted multi-tenancy, six GKE clusters, or completed AWS/Azure support.
- Preserve all unrelated uncommitted changes in both repositories.

---

### Task 1: Consolidated engineering narrative

**Files:**
- Create: `docs/engineering-challenges.md`
- Reference: `docs/phases/phase-0.md` through `docs/phases/phase-9.md`
- Reference: `docs/evidence/phase-4-controlled-beta.md`

**Interfaces:**
- Consumes: existing phase retrospectives and code/test references
- Produces: one beginner-friendly Wiki source page with stable section anchors

- [ ] **Step 1: Extract the authoritative challenge and resolution from each phase**

  Use the existing challenge/difficulty/failure sections and retain their evidence boundaries.

- [ ] **Step 2: Write the glossary and Phase 0–9 sections**

  Each phase section must contain `The problem`, `Why it was difficult`, `How Rudder handles it`, `How it was verified`, and `Remaining boundary` subsections.

- [ ] **Step 3: Add cross-phase lessons and source references**

  Link to phase docs, evidence, and representative implementation files.

- [ ] **Step 4: validate claims and links**

  Run: `bash scripts/validate-docs.sh`
  Expected: exit 0 with no broken local documentation links.

### Task 2: GitHub responsibility documentation

**Files:**
- Modify: `docs/tech-stack.md`
- Modify: `docs/configuration.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: OAuth, GitHub App, webhook, CLI publication, local registry, and Artifact Registry implementation
- Produces: an explicit responsibility map readers can use for setup and architecture decisions

- [ ] **Step 1: Add a four-part responsibility table**

  Cover human identity, repository authorization, event authenticity, and CLI distribution. Explicitly contrast GitHub Packages with deployment image registries.

- [ ] **Step 2: Add installation guidance**

  Link the GitHub Packages entry to `cli/node/README.md` and retain token-scope guidance there.

- [ ] **Step 3: Run documentation validation**

  Run: `bash scripts/validate-docs.sh`
  Expected: exit 0.

### Task 3: Documentation navigation and Wiki publication

**Files:**
- Modify: `docs/index.md`
- Modify: `docs/_Sidebar.md`
- Modify: `docs/wiki-publishing.md`
- Modify: `README.md`

**Interfaces:**
- Consumes: `docs/engineering-challenges.md`
- Produces: discoverable repository and GitHub Wiki navigation

- [ ] **Step 1: Add the Engineering Challenges page to every navigation surface**

  Use the Wiki slug `Engineering-Challenges` consistently.

- [ ] **Step 2: Add the page to the publisher command and page map**

  Ensure the source page is copied/rendered with the other canonical docs.

- [ ] **Step 3: Run the Wiki render in check mode**

  Run the repository's documented Wiki rendering command without publishing.
  Expected: the generated page map includes `Engineering-Challenges`.

### Task 4: Portfolio project entry and screenshot

**Files:**
- Modify: `/Users/sidhxntt/Desktop/Code/Portfolio/sidhxntt/input/04-projects.json`
- Modify: `/Users/sidhxntt/Desktop/Code/Portfolio/sidhxntt/src/data/portfolio.ts`
- Modify: `/Users/sidhxntt/Desktop/Code/Portfolio/sidhxntt/README.md`
- Create: `/Users/sidhxntt/Desktop/Code/Portfolio/sidhxntt/public/projects/rudder.png`

**Interfaces:**
- Consumes: verified Rudder documentation and a real local Rudder UI
- Produces: project card `id: "rudder"` using the existing `Project` type

- [ ] **Step 1: Select or capture an authentic Rudder canvas screenshot**

  Prefer an existing checked-in screenshot. If none exists, run the local app and capture the visible canvas; do not generate conceptual art.

- [ ] **Step 2: Add matching JSON and TypeScript entries**

  Use repository URL `https://github.com/sidhxntt/rudder`, preview paths `public/projects/rudder.png` and `/projects/rudder.png`, and an honest controlled-beta description.

- [ ] **Step 3: Add Rudder to the profile README project table**

  Label it as a deployment control plane / developer tool.

- [ ] **Step 4: Validate portfolio content**

  Run: `jq empty input/04-projects.json && npm test && npx tsc --noEmit && npm run build`
  Expected: valid JSON and all commands exit 0.

### Task 5: Completion audit

**Files:**
- Verify all files listed above

**Interfaces:**
- Consumes: completed documentation and portfolio artifacts
- Produces: evidence that every spec requirement is satisfied

- [ ] **Step 1: Search for required and forbidden claims**

  Confirm OAuth, GitHub App, webhooks, GitHub Packages, single operator, and shared regional cluster wording; reject any six-cluster or implemented multi-tenant claim.

- [ ] **Step 2: Review diffs against pre-existing changes**

  Confirm only intended hunks were added and media-automations/user work remains intact.

- [ ] **Step 3: Run final repository checks**

  Run Rudder documentation validation and the complete portfolio CI command sequence.
  Expected: every required check exits 0.
