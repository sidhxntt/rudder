# Phase 8: advisor and Rudder AI

> **Status:** the deterministic scanner, scoped acceptance flow, diagnosis boundary, and read-only assistant are implemented/tested where indicated by the codebase. Model output is optional and requires an operator-supplied OpenAI key; it is never deployment authority.

## Purpose

Phase 8 helps an operator understand a repository or failure without allowing a probabilistic model to alter infrastructure. This is a crucial boundary: scheduling, build detection, reconciliation, routing, and mutations remain deterministic. The advisor proposes; an operator accepts individual normal resource changes.

## Two distinct systems

### Deterministic repository advisor

`scan_repository` reads only recognised, bounded source/dependency files (max file count and bytes, excludes `.git`, virtual environments and dependencies), orders paths deterministically, and emits a stable proposal. It recognizes app frameworks, workers, Postgres/Redis use, potential S3 dependency, a health route, and a conservative memory suggestion. Workers are deliberately proposed without a public domain. A ping endpoint is preferred over a health route when both exist because it is less likely to depend on the database.

The web canvas renders proposals as ghost nodes. Acceptance is per item and routes through ordinary service/variable APIs; scan code itself has no DB session or Rudder HTTP client. That separation makes “scan” unable to deploy by construction.

### Model-assisted explanation

Failure diagnosis sends only a bounded tail (last 100 lines, line-clipped) plus scoped service configuration to an injectable OpenAI Responses API boundary. The prompt says logs/config are untrusted data, asks for uncertain concise explanation, and forbids automatic action. Empty output is represented as no diagnosis. The UI must retain raw logs and label the prose as model-generated.

Ask Rudder is a read-only browser-session assistant over current project/environment context, redacted failure context and approved docs. It has no tool or endpoint permitting deploy, rollback, variable writes, or advisor acceptance. When no `OPENAI_API_KEY` is configured, Rudder continues working and reports that only model-backed explanation is unavailable.

## Risks, controls, and cost

Repository text is untrusted and may contain prompt-injection-shaped strings. Deterministic scans treat it as data; model prompts explicitly do the same; lack of mutation authority limits blast radius to bad advice. Context caps prevent oversized repositories/logs from becoming unbounded latency/cost. The practical cost is OpenAI token/API usage only for optional diagnosis/assistant requests; static scanning is local and deterministic. Operators should budget/monitor API usage and never rely on model output as incident ground truth.

## Verification and limitations

Repeat scans of the same checkout should be byte-identical; verify a Django/Celery/Postgres/Redis example; accept one item and prove no other mutation; and exercise a failed deploy with raw logs alongside diagnosis. The full contract is summarized here. The advisor does not promise perfect framework inference, security scanning, or autonomous remediation; those would need separate, explicitly bounded products.
